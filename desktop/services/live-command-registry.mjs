import {
  LIVE_COMMAND_ACTIONS,
  LiveCommandContractError,
  assertBaseRevision,
  classifyActionAccess,
  createLiveCommandRequest,
  idempotencyFingerprint,
  requiresApproval,
  validateApplyResult,
  validatePreviewResult,
} from "./live-command-contract.mjs";

const DEFAULT_MAX_PREVIEWS = 128;
const DEFAULT_MAX_EVENTS = 512;
const DEFAULT_MAX_IDEMPOTENCY = 512;
const DEFAULT_MAX_JOBS = 128;

function registryError(code, message, field = "$", { retryable = false } = {}) {
  return new LiveCommandContractError(code, message, [{ field, code, message }], { retryable });
}

function positiveBound(value, fallback, field) {
  if (value == null) return fallback;
  if (!Number.isInteger(value) || value < 1 || value > 10_000) {
    throw registryError("REGISTRY_CONFIG_INVALID", `${field} must be an integer from 1 to 10000`, field);
  }
  return value;
}

function clone(value) {
  return structuredClone(value);
}

/**
 * In-process command broker. Transport adapters (IPC/MCP) remain responsible
 * only for authentication and serialization; all commands share this registry.
 */
export class LiveCommandRegistry {
  constructor({
    approve = null,
    now = () => Date.now(),
    maxPreviews = DEFAULT_MAX_PREVIEWS,
    maxEvents = DEFAULT_MAX_EVENTS,
    maxIdempotency = DEFAULT_MAX_IDEMPOTENCY,
    maxJobs = DEFAULT_MAX_JOBS,
  } = {}) {
    if (approve != null && typeof approve !== "function") {
      throw registryError("REGISTRY_CONFIG_INVALID", "approve must be a function", "approve");
    }
    if (typeof now !== "function") throw registryError("REGISTRY_CONFIG_INVALID", "now must be a function", "now");
    this.approve = approve;
    this.now = now;
    this.maxPreviews = positiveBound(maxPreviews, DEFAULT_MAX_PREVIEWS, "maxPreviews");
    this.maxEvents = positiveBound(maxEvents, DEFAULT_MAX_EVENTS, "maxEvents");
    this.maxIdempotency = positiveBound(maxIdempotency, DEFAULT_MAX_IDEMPOTENCY, "maxIdempotency");
    this.maxJobs = positiveBound(maxJobs, DEFAULT_MAX_JOBS, "maxJobs");
    this.handlers = new Map();
    this.previews = new Map();
    this.idempotency = new Map();
    this.inFlight = new Map();
    this.events = [];
    this.nextCursor = 1;
    this.subscribers = new Set();
    this.jobs = new Map();
    this.disposed = false;
  }

  register(action, handler) {
    this.#assertActive();
    if (!LIVE_COMMAND_ACTIONS[action]) {
      throw registryError("UNSUPPORTED_ACTION", `Cannot register unsupported action: ${String(action)}`, "action");
    }
    if (typeof handler !== "function") {
      throw registryError("HANDLER_INVALID", `Handler for ${action} must be a function`, "handler");
    }
    if (this.handlers.has(action)) {
      throw registryError("HANDLER_ALREADY_REGISTERED", `A handler is already registered for ${action}`, "action");
    }
    this.handlers.set(action, handler);
    let registered = true;
    return () => {
      if (registered && this.handlers.get(action) === handler) this.handlers.delete(action);
      registered = false;
    };
  }

  actionInventory() {
    this.#assertActive();
    return [...this.handlers.keys()].sort().map((action) => ({
      action,
      access: classifyActionAccess(action),
      approval: LIVE_COMMAND_ACTIONS[action].approval,
    }));
  }

  subscribe(listener) {
    this.#assertActive();
    if (typeof listener !== "function") {
      throw registryError("LISTENER_INVALID", "listener must be a function", "listener");
    }
    this.subscribers.add(listener);
    let subscribed = true;
    return () => {
      if (subscribed) this.subscribers.delete(listener);
      subscribed = false;
    };
  }

  async execute(input, { currentRevision, approvalContext = {} } = {}) {
    this.#assertActive();
    const request = createLiveCommandRequest(input);
    const handler = this.handlers.get(request.action);
    if (!handler) {
      throw registryError("HANDLER_NOT_REGISTERED", `No live command handler is registered for ${request.action}`, "action");
    }
    const access = classifyActionAccess(request.action);

    if (access === "mutation" && request.mode === "apply") {
      const fingerprint = idempotencyFingerprint(request);
      const remembered = this.idempotency.get(request.idempotencyKey);
      if (remembered) {
        if (remembered.fingerprint !== fingerprint) throw this.#idempotencyConflict(request.idempotencyKey);
        return clone(remembered.result);
      }
      const active = this.inFlight.get(request.idempotencyKey);
      if (active) {
        if (active.fingerprint !== fingerprint) throw this.#idempotencyConflict(request.idempotencyKey);
        return clone(await active.promise);
      }
      const promise = this.#executeFresh(request, handler, access, currentRevision, approvalContext);
      this.inFlight.set(request.idempotencyKey, { fingerprint, promise });
      try {
        const result = await promise;
        this.#rememberIdempotent(request.idempotencyKey, fingerprint, result);
        return clone(result);
      } finally {
        if (this.inFlight.get(request.idempotencyKey)?.promise === promise) {
          this.inFlight.delete(request.idempotencyKey);
        }
      }
    }

    return this.#executeFresh(request, handler, access, currentRevision, approvalContext);
  }

  async #executeFresh(request, handler, access, currentRevision, approvalContext) {
    if (access === "mutation") assertBaseRevision(request, currentRevision);
    if (requiresApproval(request, approvalContext)) {
      if (!this.approve) {
        throw registryError("APPROVAL_REQUIRED", `Approval is required for ${request.action}`, "action");
      }
      const approved = await this.approve({ request: clone(request), access, context: clone(approvalContext) });
      if (approved !== true) {
        throw registryError("APPROVAL_DECLINED", `Approval was declined for ${request.action}`, "action");
      }
    }

    const rawResult = await handler(clone(request), {
      currentRevision,
      approvalContext: clone(approvalContext),
      registry: this,
    });

    if (request.mode === "preview" && access !== "read") {
      const result = validatePreviewResult(rawResult);
      const expiresAt = Date.parse(result.expiresAt);
      if (expiresAt <= this.now()) {
        throw registryError("PREVIEW_EXPIRED", `Preview ${result.previewId} is already expired`, "expiresAt", { retryable: true });
      }
      const storedResult = this.#storePreview(request, result, expiresAt);
      return clone(storedResult);
    }
    if (request.mode === "apply") {
      const result = validateApplyResult(rawResult);
      this.#emitApplyEvent(request, result);
      return clone(result);
    }
    return clone(rawResult);
  }

  #idempotencyConflict(key) {
    return registryError(
      "IDEMPOTENCY_CONFLICT",
      `Idempotency key ${key} was already used for a different command`,
      "idempotencyKey",
    );
  }

  #rememberIdempotent(key, fingerprint, result) {
    this.idempotency.delete(key);
    this.idempotency.set(key, { fingerprint, result: clone(result) });
    while (this.idempotency.size > this.maxIdempotency) {
      this.idempotency.delete(this.idempotency.keys().next().value);
    }
  }

  #storePreview(request, result, expiresAt) {
    this.cleanup();
    const fingerprint = idempotencyFingerprint(request);
    const existing = this.previews.get(result.previewId);
    if (existing) {
      const identicalReplay = existing.commandId === request.commandId
        && existing.idempotencyKey === request.idempotencyKey
        && existing.fingerprint === fingerprint
        && existing.result.baseRevision === result.baseRevision;
      if (!identicalReplay) {
        throw registryError(
          "PREVIEW_ID_CONFLICT",
          `Preview ID ${result.previewId} already belongs to a different command`,
          "previewId",
        );
      }
      // An active preview is immutable. A retry returns the originally stored
      // bytes and expiry rather than silently replacing them with a later run.
      return existing.result;
    }
    this.previews.set(result.previewId, {
      commandId: request.commandId,
      idempotencyKey: request.idempotencyKey,
      fingerprint,
      request: clone(request),
      result: clone(result),
      expiresAt,
    });
    while (this.previews.size > this.maxPreviews) {
      this.previews.delete(this.previews.keys().next().value);
    }
    return result;
  }

  getPreview(previewId) {
    this.#assertActive();
    this.cleanup();
    const entry = this.previews.get(previewId);
    return entry ? clone(entry.result) : null;
  }

  #emitApplyEvent(request, result) {
    const event = Object.freeze({
      cursor: this.nextCursor++,
      type: "command.applied",
      timestamp: new Date(this.now()).toISOString(),
      commandId: request.commandId,
      correlationId: request.correlationId,
      projectId: request.projectId,
      pageId: request.pageId,
      action: request.action,
      baseRevision: request.baseRevision,
      newRevision: result.newRevision,
    });
    this.events.push(event);
    while (this.events.length > this.maxEvents) this.events.shift();
    for (const listener of [...this.subscribers]) {
      try {
        const pending = listener(clone(event));
        if (pending && typeof pending.then === "function") pending.catch(() => {});
      } catch {
        // Event observers are transport adapters. Their failure must never
        // roll back or duplicate an Apply that has already been committed.
      }
    }
  }

  changesSince(cursor = 0) {
    this.#assertActive();
    if (!Number.isSafeInteger(cursor) || cursor < 0) {
      throw registryError("CURSOR_INVALID", "cursor must be a non-negative safe integer", "cursor");
    }
    const earliestCursor = this.events[0]?.cursor ?? this.nextCursor;
    return {
      events: this.events.filter((event) => event.cursor > cursor).map(clone),
      latestCursor: this.nextCursor - 1,
      truncated: cursor < earliestCursor - 1,
    };
  }

  registerJob(jobId, cancel) {
    this.#assertActive();
    if (typeof jobId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(jobId)) {
      throw registryError("JOB_ID_INVALID", "jobId must be a bounded identifier", "jobId");
    }
    if (typeof cancel !== "function") throw registryError("JOB_CANCEL_INVALID", "cancel must be a function", "cancel");
    if (this.jobs.has(jobId)) throw registryError("JOB_ALREADY_REGISTERED", `Job ${jobId} is already registered`, "jobId");
    if (this.jobs.size >= this.maxJobs) throw registryError("JOB_LIMIT", `At most ${this.maxJobs} jobs may be registered`, "jobId");
    this.jobs.set(jobId, cancel);
    return () => this.jobs.delete(jobId);
  }

  async cancelJob(jobId, reason = "cancelled") {
    this.#assertActive();
    const cancel = this.jobs.get(jobId);
    if (!cancel) throw registryError("JOB_NOT_FOUND", `No active job exists for ${String(jobId)}`, "jobId");
    this.jobs.delete(jobId);
    await cancel(reason);
    return { jobId, cancelled: true };
  }

  cleanup() {
    this.#assertActive();
    const now = this.now();
    let removedPreviews = 0;
    for (const [previewId, entry] of this.previews) {
      if (entry.expiresAt <= now) {
        this.previews.delete(previewId);
        removedPreviews += 1;
      }
    }
    return { removedPreviews };
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.handlers.clear();
    this.previews.clear();
    this.idempotency.clear();
    this.inFlight.clear();
    this.events.length = 0;
    this.subscribers.clear();
    this.jobs.clear();
  }

  #assertActive() {
    if (this.disposed) throw registryError("REGISTRY_DISPOSED", "Live command registry is disposed");
  }
}

export const LiveCommandBroker = LiveCommandRegistry;
