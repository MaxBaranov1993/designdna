import { createHash } from "node:crypto";
import {
  LIVE_COMMAND_ACTIONS,
  LiveCommandContractError,
  classifyActionAccess,
  idempotencyFingerprint,
} from "./live-command-contract.mjs";

export const DEFAULT_MAX_PROJECT_BYTES = 8 * 1024 * 1024;
const DEFAULT_MAX_EVENTS = 512;
const DEFAULT_MAX_UNDO_ENTRIES = 256;
const SHA256_REVISION = /^[a-f0-9]{64}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const POLLUTION_KEYS = new Set(["__proto__", "prototype", "constructor"]);

function sessionError(code, message, field = "$", { retryable = false } = {}) {
  return new LiveCommandContractError(code, message, [{ field, code, message }], { retryable });
}

function assertId(value, field) {
  if (typeof value !== "string" || !SAFE_ID.test(value)) {
    throw sessionError("SESSION_ID_INVALID", `${field} must be a bounded identifier`, field);
  }
  return value;
}

export function assertSha256Revision(value, field = "revision") {
  if (typeof value !== "string" || !SHA256_REVISION.test(value)) {
    throw sessionError("REVISION_INVALID", `${field} must be a lowercase SHA-256 revision`, field);
  }
  return value;
}

function parseTimestamp(value, field = "updatedAt") {
  if (typeof value !== "string") throw sessionError("TIMESTAMP_INVALID", `${field} must be a strict UTC ISO timestamp`, field);
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== value) {
    throw sessionError("TIMESTAMP_INVALID", `${field} must be a strict UTC ISO timestamp with milliseconds`, field);
  }
  return date.getTime();
}

function stableJson(value, field = "project", seen = new Set(), depth = 0) {
  if (depth > 64) throw sessionError("STATE_INVALID", `${field} exceeds 64 levels of nesting`, field);
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw sessionError("STATE_INVALID", `${field} contains a non-finite number`, field);
    return JSON.stringify(value);
  }
  if (typeof value !== "object") throw sessionError("STATE_INVALID", `${field} is not JSON-serializable`, field);
  const prototype = Object.getPrototypeOf(value);
  if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) {
    throw sessionError("STATE_INVALID", `${field} contains a non-plain object`, field);
  }
  if (seen.has(value)) throw sessionError("STATE_INVALID", `${field} contains a cycle`, field);
  seen.add(value);
  try {
    if (Array.isArray(value)) return `[${value.map((item, index) => stableJson(item, `${field}[${index}]`, seen, depth + 1)).join(",")}]`;
    const keys = Object.keys(value).sort();
    for (const key of keys) {
      if (POLLUTION_KEYS.has(key)) throw sessionError("STATE_INVALID", `${field}.${key} is forbidden`, `${field}.${key}`);
    }
    return `{${keys.map((key) => `${JSON.stringify(key)}:${stableJson(value[key], `${field}.${key}`, seen, depth + 1)}`).join(",")}}`;
  } finally {
    seen.delete(value);
  }
}

function clone(value) {
  return structuredClone(value);
}

function positiveBound(value, fallback, field) {
  if (value == null) return fallback;
  if (!Number.isInteger(value) || value < 1 || value > 100_000_000) {
    throw sessionError("SESSION_CONFIG_INVALID", `${field} must be a positive bounded integer`, field);
  }
  return value;
}

function canonicalState(value, maxBytes, field = "project", precomputed = null) {
  // precomputed — результат canonicalOnly() для ТОГО ЖЕ объекта из этого же
  // запроса (prepare → synchronize): канонизация 8-МБ проекта дорога, и
  // считать её дважды на каждый автосейв нельзя.
  const canonical = precomputed && precomputed.value === value
    ? precomputed.canonical
    : stableJson(value, field);
  const bytes = Buffer.byteLength(canonical, "utf8");
  if (bytes > maxBytes) {
    throw sessionError("STATE_TOO_LARGE", `${field} exceeds ${maxBytes} UTF-8 bytes`, field);
  }
  return { canonical, value: clone(value), bytes };
}

/** Канонизация без клонирования — для валидации и переиспользования в рамках
 *  одного запроса. Результат привязан к идентичности объекта. */
function canonicalOnly(value, maxBytes, field = "project") {
  const canonical = stableJson(value, field);
  const bytes = Buffer.byteLength(canonical, "utf8");
  if (bytes > maxBytes) {
    throw sessionError("STATE_TOO_LARGE", `${field} exceeds ${maxBytes} UTF-8 bytes`, field);
  }
  return { canonical, bytes, value };
}

function applyFingerprint(input, projectCanonical) {
  return createHash("sha256").update(stableJson({
    baseRevision: input.baseRevision,
    newRevision: input.newRevision,
    project: JSON.parse(projectCanonical),
    inverseCommand: input.inverseCommand,
    undoEntry: input.undoEntry,
  }, "apply"), "utf8").digest("hex");
}

export class LiveProjectSession {
  constructor({
    userId,
    projectId,
    registry = null,
    now = () => Date.now(),
    maxProjectBytes = DEFAULT_MAX_PROJECT_BYTES,
    maxEvents = DEFAULT_MAX_EVENTS,
    maxUndoEntries = DEFAULT_MAX_UNDO_ENTRIES,
  }) {
    this.userId = assertId(userId, "userId");
    this.projectId = assertId(projectId, "projectId");
    if (registry != null && (typeof registry.execute !== "function" || typeof registry.getPreview !== "function")) {
      throw sessionError("SESSION_CONFIG_INVALID", "registry must provide execute and getPreview", "registry");
    }
    if (typeof now !== "function") throw sessionError("SESSION_CONFIG_INVALID", "now must be a function", "now");
    this.registry = registry;
    this.now = now;
    this.maxProjectBytes = positiveBound(maxProjectBytes, DEFAULT_MAX_PROJECT_BYTES, "maxProjectBytes");
    this.maxEvents = positiveBound(maxEvents, DEFAULT_MAX_EVENTS, "maxEvents");
    this.maxUndoEntries = positiveBound(maxUndoEntries, DEFAULT_MAX_UNDO_ENTRIES, "maxUndoEntries");
    this.project = null;
    this.projectCanonical = null;
    this.revision = null;
    this.persistedRevision = null;
    this.pendingBaseRevision = null;
    this.updatedAt = null;
    this.updatedAtMs = null;
    this.dirty = false;
    this.rendererGeneration = 0;
    this.renderer = null;
    this.events = [];
    this.nextCursor = 1;
    this.subscribers = new Set();
    this.idempotency = new Map();
    this.undoEntries = [];
    this.disposed = false;
  }

  get key() {
    return `${this.userId}:${this.projectId}`;
  }

  hydrateFromLoad(project, revision, updatedAt, { precomputed = null } = {}) {
    this.#assertActive();
    const nextRevision = assertSha256Revision(revision);
    const nextUpdatedAtMs = parseTimestamp(updatedAt);
    const next = canonicalState(project, this.maxProjectBytes, "project", precomputed);
    if (this.revision !== null) {
      if (nextRevision === this.revision) {
        if (next.canonical !== this.projectCanonical) {
          throw sessionError("EXTERNAL_WRITE_CONFLICT", "The same revision contains different project bytes", "revision");
        }
        if (nextUpdatedAtMs < this.updatedAtMs) {
          throw sessionError("STALE_LOAD", "Loaded project timestamp is older than the live session", "updatedAt", { retryable: true });
        }
        return this.getSnapshot();
      }
      if (this.dirty) {
        throw sessionError("EXTERNAL_WRITE_CONFLICT", "External project revision conflicts with unsaved live changes", "revision");
      }
      if (nextUpdatedAtMs < this.updatedAtMs) {
        throw sessionError("STALE_LOAD", "Loaded project revision is older than the live session", "revision", { retryable: true });
      }
      if (nextUpdatedAtMs === this.updatedAtMs) {
        throw sessionError("EXTERNAL_WRITE_CONFLICT", "Different revisions have the same update timestamp", "revision");
      }
    }
    this.project = next.value;
    this.projectCanonical = next.canonical;
    this.revision = nextRevision;
    this.persistedRevision = nextRevision;
    this.pendingBaseRevision = null;
    this.updatedAt = updatedAt;
    this.updatedAtMs = nextUpdatedAtMs;
    this.dirty = false;
    this.idempotency.clear();
    this.undoEntries.length = 0;
    this.#emit("session.hydrated", { revision: nextRevision, updatedAt });
    return this.getSnapshot();
  }

  notePersistedSave(project, baseRevision, newRevision, updatedAt, { precomputed = null } = {}) {
    this.#assertInitialized();
    const base = assertSha256Revision(baseRevision, "baseRevision");
    const nextRevision = assertSha256Revision(newRevision, "newRevision");
    const nextUpdatedAtMs = parseTimestamp(updatedAt);
    const next = canonicalState(project, this.maxProjectBytes, "project", precomputed);
    if (nextUpdatedAtMs < this.updatedAtMs) {
      throw sessionError("STALE_SAVE", "Persisted save timestamp is older than the live session", "updatedAt", { retryable: true });
    }

    const acknowledgesDirtyApply = this.dirty
      && this.revision === nextRevision
      && this.pendingBaseRevision === base;
    const savesCurrentCleanBase = !this.dirty && this.revision === base;
    if (!acknowledgesDirtyApply && !savesCurrentCleanBase) {
      const code = this.dirty ? "EXTERNAL_WRITE_CONFLICT" : "STALE_SAVE";
      throw sessionError(code, "Persisted save does not match the authoritative live revision", "baseRevision", { retryable: true });
    }
    if (acknowledgesDirtyApply && next.canonical !== this.projectCanonical) {
      throw sessionError("EXTERNAL_WRITE_CONFLICT", "Persisted bytes differ from the live project at the same revision", "project");
    }

    this.project = next.value;
    this.projectCanonical = next.canonical;
    this.revision = nextRevision;
    this.persistedRevision = nextRevision;
    this.pendingBaseRevision = null;
    this.updatedAt = updatedAt;
    this.updatedAtMs = nextUpdatedAtMs;
    this.dirty = false;
    this.#emit("session.persisted", { baseRevision: base, newRevision: nextRevision, updatedAt });
    return this.getSnapshot();
  }

  getSnapshot() {
    this.#assertInitialized();
    return {
      userId: this.userId,
      projectId: this.projectId,
      project: clone(this.project),
      revision: this.revision,
      persistedRevision: this.persistedRevision,
      updatedAt: this.updatedAt,
      dirty: this.dirty,
    };
  }

  currentRevision() {
    this.#assertInitialized();
    return this.revision;
  }

  validateProject(project) {
    this.#assertActive();
    // canonicalOnly: валидация не хранит состояние — клонировать проект незачем.
    // Возвращаем canonical, чтобы save-путь переиспользовал его в
    // notePersistedSave/hydrateFromLoad вместо повторной канонизации.
    return canonicalOnly(project, this.maxProjectBytes);
  }

  async beginPreview(request, { approvalContext = {} } = {}) {
    this.#assertInitialized();
    if (!this.registry) throw sessionError("REGISTRY_REQUIRED", "A command registry is required for previews", "registry");
    if (request?.projectId !== this.projectId) {
      throw sessionError("PROJECT_MISMATCH", "Preview request targets a different project", "projectId");
    }
    if (request?.mode !== "preview") throw sessionError("PREVIEW_MODE_REQUIRED", "beginPreview requires preview mode", "mode");
    const access = LIVE_COMMAND_ACTIONS[request?.action] ? classifyActionAccess(request.action) : null;
    if (access === "mutation" && request.baseRevision !== this.revision) {
      throw sessionError("STALE_REVISION", "Preview base revision is not current", "baseRevision", { retryable: true });
    }
    // The session-owned revision is the only value passed as execution truth.
    return this.registry.execute(request, { currentRevision: this.revision, approvalContext });
  }

  resolvePreview(previewId) {
    this.#assertInitialized();
    if (!this.registry) throw sessionError("REGISTRY_REQUIRED", "A command registry is required for previews", "registry");
    const preview = this.registry.getPreview(previewId);
    if (!preview) throw sessionError("PREVIEW_NOT_FOUND", `Preview ${String(previewId)} is missing or expired`, "previewId", { retryable: true });
    if (preview.baseRevision !== this.revision) {
      throw sessionError("PREVIEW_STALE", "Preview no longer matches the authoritative project revision", "baseRevision", { retryable: true });
    }
    return preview;
  }

  compareAndSwapApply(input) {
    this.#assertInitialized();
    if (input === null || typeof input !== "object" || Array.isArray(input)) {
      throw sessionError("APPLY_INVALID", "Apply input must be an object");
    }
    const idempotencyKey = assertId(input.idempotencyKey, "idempotencyKey");
    const commandId = assertId(input.commandId, "commandId");
    const baseRevision = assertSha256Revision(input.baseRevision, "baseRevision");
    const newRevision = assertSha256Revision(input.newRevision, "newRevision");
    if (input.inverseCommand === null || typeof input.inverseCommand !== "object" || Array.isArray(input.inverseCommand)) {
      throw sessionError("APPLY_INVALID", "inverseCommand must be a plain object", "inverseCommand");
    }
    if (input.undoEntry === null || typeof input.undoEntry !== "object" || Array.isArray(input.undoEntry)) {
      throw sessionError("APPLY_INVALID", "undoEntry must be a plain object", "undoEntry");
    }
    const next = canonicalState(input.project, this.maxProjectBytes);
    // Validate and bound inverse/undo metadata using the same JSON discipline.
    canonicalState(input.inverseCommand, Math.min(this.maxProjectBytes, 262_144), "inverseCommand");
    canonicalState(input.undoEntry, Math.min(this.maxProjectBytes, 262_144), "undoEntry");
    const fingerprint = applyFingerprint(input, next.canonical);
    const remembered = this.idempotency.get(idempotencyKey);
    if (remembered) {
      if (remembered.fingerprint !== fingerprint) {
        throw sessionError("IDEMPOTENCY_CONFLICT", "Idempotency key was used for a different Apply", "idempotencyKey");
      }
      return { ...clone(remembered.result), replayed: true };
    }
    if (baseRevision !== this.revision) {
      throw sessionError("STALE_REVISION", "Apply base revision is not authoritative", "baseRevision", { retryable: true });
    }
    if (newRevision === baseRevision) {
      throw sessionError("REVISION_INVALID", "Apply must advance to a new revision", "newRevision");
    }

    const appliedAt = new Date(this.now()).toISOString();
    this.project = next.value;
    this.projectCanonical = next.canonical;
    this.pendingBaseRevision = baseRevision;
    this.revision = newRevision;
    this.updatedAt = appliedAt;
    this.updatedAtMs = Date.parse(appliedAt);
    this.dirty = true;
    const undoRecord = {
      commandId,
      baseRevision,
      newRevision,
      inverseCommand: clone(input.inverseCommand),
      undoEntry: clone(input.undoEntry),
    };
    this.undoEntries.push(undoRecord);
    while (this.undoEntries.length > this.maxUndoEntries) this.undoEntries.shift();
    const result = {
      commandId,
      baseRevision,
      newRevision,
      inverseCommand: clone(input.inverseCommand),
      undoEntry: clone(input.undoEntry),
      dirty: true,
      replayed: false,
    };
    this.idempotency.set(idempotencyKey, { fingerprint, result: clone(result) });
    this.#emit("session.applied", { commandId, baseRevision, newRevision, dirty: true });
    return clone(result);
  }

  attachRenderer(rendererId) {
    this.#assertActive();
    assertId(rendererId, "rendererId");
    this.rendererGeneration += 1;
    this.renderer = { rendererId, generation: this.rendererGeneration };
    this.#emit("renderer.attached", this.renderer);
    return clone(this.renderer);
  }

  isRendererGenerationCurrent(rendererId, generation) {
    this.#assertActive();
    return this.renderer?.rendererId === rendererId && this.renderer.generation === generation;
  }

  subscribe(listener) {
    this.#assertActive();
    if (typeof listener !== "function") throw sessionError("LISTENER_INVALID", "listener must be a function", "listener");
    this.subscribers.add(listener);
    let active = true;
    return () => {
      if (active) this.subscribers.delete(listener);
      active = false;
    };
  }

  changesSince(cursor = 0) {
    this.#assertActive();
    if (!Number.isSafeInteger(cursor) || cursor < 0) throw sessionError("CURSOR_INVALID", "cursor must be a non-negative safe integer", "cursor");
    const earliest = this.events[0]?.cursor ?? this.nextCursor;
    return {
      events: this.events.filter((event) => event.cursor > cursor).map(clone),
      latestCursor: this.nextCursor - 1,
      truncated: cursor < earliest - 1,
    };
  }

  #emit(type, detail) {
    const event = Object.freeze({
      cursor: this.nextCursor++,
      type,
      timestamp: new Date(this.now()).toISOString(),
      userId: this.userId,
      projectId: this.projectId,
      ...clone(detail),
    });
    this.events.push(event);
    while (this.events.length > this.maxEvents) this.events.shift();
    for (const listener of [...this.subscribers]) {
      try {
        const pending = listener(clone(event));
        if (pending && typeof pending.then === "function") pending.catch(() => {});
      } catch { /* observer failure cannot affect canonical state */ }
    }
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.project = null;
    this.projectCanonical = null;
    this.idempotency.clear();
    this.undoEntries.length = 0;
    this.events.length = 0;
    this.subscribers.clear();
    this.renderer = null;
  }

  #assertInitialized() {
    this.#assertActive();
    if (this.revision === null) throw sessionError("SESSION_NOT_HYDRATED", "Live project session is not hydrated");
  }

  #assertActive() {
    if (this.disposed) throw sessionError("SESSION_DISPOSED", "Live project session is disposed");
  }
}
