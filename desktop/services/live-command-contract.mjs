import { createHash } from "node:crypto";

/**
 * Transport-neutral contract for the DesignDNA live command bus.
 *
 * Actions are intentionally explicit. Adding a UI or MCP operation requires a
 * registry entry first, so an unknown command can never be silently treated as
 * a harmless read. `access` describes what the command can do; `approval`
 * describes the default native approval policy.
 */
export const LIVE_COMMAND_ACTIONS = Object.freeze({
  "session.get": { access: "read", approval: "never" },
  "project.get": { access: "read", approval: "never" },
  "pages.list": { access: "read", approval: "never" },
  "graph.get": { access: "read", approval: "never" },
  "selection.get": { access: "read", approval: "never" },
  "command.list": { access: "read", approval: "never" },
  "changes.since": { access: "read", approval: "never" },
  "job.get": { access: "read", approval: "never" },
  "designSystem.list": { access: "read", approval: "never" },
  "designIr.validate": { access: "preview", approval: "never" },
  "quality.check": { access: "preview", approval: "never" },
  "editor.style.patch": { access: "mutation", approval: "apply" },
  "project.open": { access: "mutation", approval: "apply" },
  "project.save": { access: "mutation", approval: "apply" },
  "selection.set": { access: "mutation", approval: "apply" },
  "graph.node.create": { access: "mutation", approval: "apply" },
  "graph.node.delete": { access: "mutation", approval: "always" },
  "graph.node.move": { access: "mutation", approval: "apply" },
  "graph.edge.connect": { access: "mutation", approval: "apply" },
  "graph.edge.delete": { access: "mutation", approval: "always" },
  "source.capture": { access: "mutation", approval: "network" },
  "designSystem.select": { access: "mutation", approval: "apply" },
  "generate.run": { access: "mutation", approval: "paid-or-apply" },
  "derive.run": { access: "mutation", approval: "paid-or-apply" },
  "reskin.run": { access: "mutation", approval: "paid-or-apply" },
  "quality.repair": { access: "mutation", approval: "paid-or-apply" },
  "history.undo": { access: "mutation", approval: "apply" },
  "history.redo": { access: "mutation", approval: "apply" },
  "motion.create": { access: "mutation", approval: "apply" },
  "motion.edit": { access: "mutation", approval: "apply" },
  "export.start": { access: "mutation", approval: "external-path" },
  "job.cancel": { access: "mutation", approval: "apply" },
});

export const LIVE_COMMAND_LIMITS = Object.freeze({
  maxIdBytes: 128,
  maxIntentBytes: 2_048,
  maxArgumentsBytes: 65_536,
  maxRequestBytes: 131_072,
  maxResultBytes: 262_144,
  maxScopeEntries: 256,
  maxPatchEntries: 2_048,
  minTimeoutMs: 100,
  maxTimeoutMs: 600_000,
});

const MODES = new Set(["preview", "apply"]);
const VIEWPORTS = new Set(["desktop", "tablet", "mobile"]);
const POLLUTION_KEYS = new Set(["__proto__", "prototype", "constructor"]);
const REQUEST_FIELDS = new Set([
  "commandId", "idempotencyKey", "projectId", "pageId", "baseRevision",
  "intent", "scope", "action", "arguments", "mode", "correlationId", "timeoutMs",
]);
const SCOPE_FIELDS = new Set(["nodeIds", "sourceKeys", "viewports"]);
const PREVIEW_FIELDS = new Set([
  "previewId", "baseRevision", "patch", "inversePatch", "affectedObjects",
  "preservedRules", "violations", "qualityReport", "expiresAt",
]);
const APPLY_FIELDS = new Set([
  "newRevision", "inverseCommand", "undoEntry", "affectedObjects", "qualityReport",
]);
const UTF8 = new TextEncoder();

function utf8Bytes(value) {
  return UTF8.encode(value).length;
}

function issue(field, code, message) {
  return { field, code, message };
}

export class LiveCommandContractError extends Error {
  constructor(code, message, issues = [], { retryable = false } = {}) {
    super(message);
    this.name = "LiveCommandContractError";
    this.code = code;
    this.issues = issues;
    this.retryable = retryable;
  }

  toJSON() {
    return commandError(this.code, this.message, this.issues, { retryable: this.retryable });
  }
}

export function commandError(code, message, issues = [], { retryable = false } = {}) {
  return {
    ok: false,
    error: {
      code: String(code),
      message: String(message),
      issues: Array.isArray(issues) ? issues.map((item) => ({ ...item })) : [],
      retryable: Boolean(retryable),
    },
  };
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function rejectUnknownKeys(value, allowed, field, issues) {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) issues.push(issue(field ? `${field}.${key}` : key, "UNKNOWN_FIELD", "unknown field"));
  }
}

function validateJsonValue(value, field, issues, seen = new Set(), depth = 0) {
  if (depth > 32) {
    issues.push(issue(field, "NESTING_LIMIT", "JSON nesting exceeds 32 levels"));
    return;
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) issues.push(issue(field, "INVALID_JSON", "number must be finite"));
    return;
  }
  if (typeof value !== "object") {
    issues.push(issue(field, "INVALID_JSON", `unsupported JSON value type: ${typeof value}`));
    return;
  }
  if (seen.has(value)) {
    issues.push(issue(field, "CYCLIC_VALUE", "cyclic values are not supported"));
    return;
  }
  if (!Array.isArray(value) && !isPlainObject(value)) {
    issues.push(issue(field, "NON_PLAIN_OBJECT", "value must contain only plain JSON objects"));
    return;
  }
  seen.add(value);
  try {
    for (const [key, child] of Object.entries(value)) {
      if (POLLUTION_KEYS.has(key)) {
        issues.push(issue(`${field}.${key}`, "PROTOTYPE_POLLUTION", "prototype-pollution key is forbidden"));
        continue;
      }
      validateJsonValue(child, `${field}.${key}`, issues, seen, depth + 1);
    }
  } finally {
    seen.delete(value);
  }
}

function boundedIdentifier(value, field, issues, { required = true } = {}) {
  if (value == null && !required) return null;
  if (typeof value !== "string" || !value) {
    issues.push(issue(field, "INVALID_ID", `${field} must be a non-empty string`));
    return "";
  }
  if (utf8Bytes(value) > LIVE_COMMAND_LIMITS.maxIdBytes) {
    issues.push(issue(field, "SIZE_LIMIT", `${field} exceeds ${LIVE_COMMAND_LIMITS.maxIdBytes} UTF-8 bytes`));
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)) {
    issues.push(issue(field, "INVALID_ID", `${field} contains unsupported characters`));
  }
  return value;
}

function boundedText(value, field, maxBytes, issues, { required = true } = {}) {
  if (value == null && !required) return null;
  if (typeof value !== "string" || (required && !value.trim())) {
    issues.push(issue(field, "INVALID_STRING", `${field} must be a non-empty string`));
    return "";
  }
  if (utf8Bytes(value) > maxBytes) issues.push(issue(field, "SIZE_LIMIT", `${field} exceeds ${maxBytes} UTF-8 bytes`));
  return value;
}

function normalizeScope(value, issues) {
  if (value == null) return { nodeIds: [], sourceKeys: [], viewports: [] };
  if (!isPlainObject(value)) {
    issues.push(issue("scope", "INVALID_TYPE", "scope must be a plain object"));
    return { nodeIds: [], sourceKeys: [], viewports: [] };
  }
  rejectUnknownKeys(value, SCOPE_FIELDS, "scope", issues);
  const normalizeList = (name, validator) => {
    const input = value[name] ?? [];
    if (!Array.isArray(input)) {
      issues.push(issue(`scope.${name}`, "INVALID_TYPE", `${name} must be an array`));
      return [];
    }
    if (input.length > LIVE_COMMAND_LIMITS.maxScopeEntries) {
      issues.push(issue(`scope.${name}`, "COUNT_LIMIT", `${name} supports at most ${LIVE_COMMAND_LIMITS.maxScopeEntries} entries`));
    }
    const output = input.slice(0, LIVE_COMMAND_LIMITS.maxScopeEntries).map((item, index) => validator(item, index));
    if (new Set(output).size !== output.length) issues.push(issue(`scope.${name}`, "DUPLICATE", `${name} must not contain duplicates`));
    return output;
  };
  return {
    nodeIds: normalizeList("nodeIds", (item, index) => boundedIdentifier(item, `scope.nodeIds[${index}]`, issues)),
    sourceKeys: normalizeList("sourceKeys", (item, index) => {
      const text = boundedText(item, `scope.sourceKeys[${index}]`, 256, issues);
      if (typeof item === "string" && /[\u0000-\u001f\u007f]/.test(item)) {
        issues.push(issue(`scope.sourceKeys[${index}]`, "INVALID_STRING", "sourceKey contains a control character"));
      }
      return text;
    }),
    viewports: normalizeList("viewports", (item, index) => {
      if (typeof item !== "string" || !VIEWPORTS.has(item)) {
        issues.push(issue(`scope.viewports[${index}]`, "UNSUPPORTED_VIEWPORT", `unsupported viewport: ${String(item)}`));
      }
      return item;
    }),
  };
}

function stableJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
}

function throwIssues(kind, issues) {
  if (issues.length) {
    throw new LiveCommandContractError(
      `${kind.toUpperCase()}_INVALID`,
      `Invalid live command ${kind}: ${issues.map((item) => `${item.field}: ${item.message}`).join("; ")}`,
      issues,
    );
  }
}

export function classifyActionAccess(action) {
  const entry = LIVE_COMMAND_ACTIONS[action];
  if (!entry) throw new LiveCommandContractError("UNSUPPORTED_ACTION", `Unsupported live command action: ${String(action)}`, [
    issue("action", "UNSUPPORTED_ACTION", `unsupported action: ${String(action)}`),
  ]);
  return entry.access;
}

/** Context flags describe effects not knowable from the action name alone. */
export function requiresApproval(requestOrAction, context = {}) {
  const action = typeof requestOrAction === "string" ? requestOrAction : requestOrAction?.action;
  const mode = typeof requestOrAction === "object" ? requestOrAction?.mode : context.mode;
  const rule = LIVE_COMMAND_ACTIONS[action]?.approval;
  if (!rule) classifyActionAccess(action);
  if (rule === "never") return Boolean(context.paidModel || context.network || context.externalPath);
  if (rule === "always") return true;
  if (rule === "network") return mode === "apply" || context.network !== false;
  if (rule === "external-path") return mode === "apply" || Boolean(context.externalPath);
  if (rule === "paid-or-apply") return mode === "apply" || Boolean(context.paidModel);
  return mode === "apply";
}

export function createLiveCommandRequest(input) {
  const issues = [];
  if (!isPlainObject(input)) {
    throw new LiveCommandContractError("REQUEST_INVALID", "Invalid live command request: request must be a plain object", [
      issue("$", "INVALID_TYPE", "request must be a plain object"),
    ]);
  }
  rejectUnknownKeys(input, REQUEST_FIELDS, "", issues);
  validateJsonValue(input, "$", issues);

  const commandId = boundedIdentifier(input.commandId, "commandId", issues);
  const idempotencyKey = boundedIdentifier(input.idempotencyKey, "idempotencyKey", issues);
  const projectId = boundedIdentifier(input.projectId, "projectId", issues);
  const pageId = boundedIdentifier(input.pageId, "pageId", issues, { required: false });
  const correlationId = boundedIdentifier(input.correlationId, "correlationId", issues);
  const intent = boundedText(input.intent, "intent", LIVE_COMMAND_LIMITS.maxIntentBytes, issues);
  const scope = normalizeScope(input.scope, issues);

  if (typeof input.action !== "string" || !LIVE_COMMAND_ACTIONS[input.action]) {
    issues.push(issue("action", "UNSUPPORTED_ACTION", `unsupported action: ${String(input.action)}`));
  }
  const access = LIVE_COMMAND_ACTIONS[input.action]?.access ?? null;
  if (!MODES.has(input.mode)) issues.push(issue("mode", "INVALID_MODE", "mode must be preview or apply"));
  if (input.mode === "apply" && access !== "mutation") {
    issues.push(issue("mode", "INVALID_MODE", "only mutation actions may use apply mode"));
  }
  if (access === "read" && input.mode !== "preview") {
    issues.push(issue("mode", "INVALID_MODE", "read actions use preview mode"));
  }
  const revisionRequired = input.mode === "apply" || access === "mutation";
  const baseRevision = boundedIdentifier(input.baseRevision, "baseRevision", issues, { required: revisionRequired });

  if (!isPlainObject(input.arguments)) {
    issues.push(issue("arguments", "INVALID_TYPE", "arguments must be a plain object"));
  }
  const args = isPlainObject(input.arguments) ? input.arguments : {};
  let argumentsBytes = Infinity;
  try { argumentsBytes = utf8Bytes(stableJson(args)); } catch { /* validateJsonValue reports the cause */ }
  if (argumentsBytes > LIVE_COMMAND_LIMITS.maxArgumentsBytes) {
    issues.push(issue("arguments", "SIZE_LIMIT", `arguments exceed ${LIVE_COMMAND_LIMITS.maxArgumentsBytes} UTF-8 bytes`));
  }

  if (!Number.isInteger(input.timeoutMs)
      || input.timeoutMs < LIVE_COMMAND_LIMITS.minTimeoutMs
      || input.timeoutMs > LIVE_COMMAND_LIMITS.maxTimeoutMs) {
    issues.push(issue("timeoutMs", "OUT_OF_RANGE", `timeoutMs must be an integer from ${LIVE_COMMAND_LIMITS.minTimeoutMs} to ${LIVE_COMMAND_LIMITS.maxTimeoutMs}`));
  }

  const normalized = {
    commandId,
    idempotencyKey,
    projectId,
    pageId,
    baseRevision,
    intent,
    scope,
    action: input.action,
    arguments: args,
    mode: input.mode,
    correlationId,
    timeoutMs: input.timeoutMs,
  };
  let requestBytes = Infinity;
  try { requestBytes = utf8Bytes(stableJson(normalized)); } catch { /* issue already collected */ }
  if (requestBytes > LIVE_COMMAND_LIMITS.maxRequestBytes) {
    issues.push(issue("$", "SIZE_LIMIT", `request exceeds ${LIVE_COMMAND_LIMITS.maxRequestBytes} UTF-8 bytes`));
  }
  throwIssues("request", issues);
  return normalized;
}

/** Stable across object key ordering and transport-only command/correlation IDs. */
export function idempotencyFingerprint(request) {
  const normalized = createLiveCommandRequest(request);
  const semantic = {
    projectId: normalized.projectId,
    pageId: normalized.pageId,
    baseRevision: normalized.baseRevision,
    intent: normalized.intent,
    scope: normalized.scope,
    action: normalized.action,
    arguments: normalized.arguments,
    mode: normalized.mode,
  };
  return createHash("sha256").update(stableJson(semantic), "utf8").digest("hex");
}

/** Compare-and-swap guard used immediately before preview/apply execution. */
export function assertBaseRevision(request, currentRevision) {
  const normalized = createLiveCommandRequest(request);
  const revisionIssues = [];
  boundedIdentifier(currentRevision, "currentRevision", revisionIssues);
  if (revisionIssues.length) {
    throw new LiveCommandContractError(
      "REVISION_INVALID",
      `Invalid current project revision: ${revisionIssues.map((item) => item.message).join("; ")}`,
      revisionIssues,
    );
  }
  if (normalized.baseRevision !== currentRevision) {
    throw new LiveCommandContractError("STALE_REVISION", "The project changed after this command was prepared", [
      issue("baseRevision", "STALE_REVISION", `expected ${currentRevision}, received ${normalized.baseRevision}`),
    ], { retryable: true });
  }
  return normalized;
}

function validateResultObject(input, allowed, kind, issues) {
  if (!isPlainObject(input)) {
    issues.push(issue("$", "INVALID_TYPE", `${kind} result must be a plain object`));
    return {};
  }
  rejectUnknownKeys(input, allowed, "", issues);
  validateJsonValue(input, "$", issues);
  return input;
}

function requiredArray(input, field, issues) {
  if (!Array.isArray(input)) {
    issues.push(issue(field, "INVALID_TYPE", `${field} must be an array`));
    return [];
  }
  if (input.length > LIVE_COMMAND_LIMITS.maxPatchEntries) {
    issues.push(issue(field, "COUNT_LIMIT", `${field} supports at most ${LIVE_COMMAND_LIMITS.maxPatchEntries} entries`));
  }
  return input;
}

function checkResultSize(input, issues) {
  let bytes = Infinity;
  try { bytes = utf8Bytes(stableJson(input)); } catch { /* validateJsonValue reports the cause */ }
  if (bytes > LIVE_COMMAND_LIMITS.maxResultBytes) {
    issues.push(issue("$", "SIZE_LIMIT", `result exceeds ${LIVE_COMMAND_LIMITS.maxResultBytes} UTF-8 bytes`));
  }
}

export function validatePreviewResult(input) {
  const issues = [];
  const raw = validateResultObject(input, PREVIEW_FIELDS, "preview", issues);
  boundedIdentifier(raw.previewId, "previewId", issues);
  boundedIdentifier(raw.baseRevision, "baseRevision", issues);
  requiredArray(raw.patch, "patch", issues);
  requiredArray(raw.inversePatch, "inversePatch", issues);
  requiredArray(raw.affectedObjects, "affectedObjects", issues);
  requiredArray(raw.preservedRules, "preservedRules", issues);
  requiredArray(raw.violations, "violations", issues);
  if (!isPlainObject(raw.qualityReport)) issues.push(issue("qualityReport", "INVALID_TYPE", "qualityReport must be a plain object"));
  const parsedExpiry = typeof raw.expiresAt === "string" ? new Date(raw.expiresAt) : null;
  const strictUtcExpiry = parsedExpiry
    && Number.isFinite(parsedExpiry.getTime())
    && parsedExpiry.toISOString() === raw.expiresAt;
  if (!strictUtcExpiry) {
    issues.push(issue("expiresAt", "INVALID_TIMESTAMP", "expiresAt must be a strict UTC ISO-8601 timestamp with milliseconds"));
  }
  checkResultSize(raw, issues);
  throwIssues("preview result", issues);
  return raw;
}

export function validateApplyResult(input) {
  const issues = [];
  const raw = validateResultObject(input, APPLY_FIELDS, "apply", issues);
  boundedIdentifier(raw.newRevision, "newRevision", issues);
  if (!isPlainObject(raw.inverseCommand)) issues.push(issue("inverseCommand", "INVALID_TYPE", "inverseCommand must be a plain object"));
  if (!isPlainObject(raw.undoEntry)) issues.push(issue("undoEntry", "INVALID_TYPE", "undoEntry must be a plain object"));
  if (raw.affectedObjects != null) requiredArray(raw.affectedObjects, "affectedObjects", issues);
  if (raw.qualityReport != null && !isPlainObject(raw.qualityReport)) {
    issues.push(issue("qualityReport", "INVALID_TYPE", "qualityReport must be a plain object"));
  }
  checkResultSize(raw, issues);
  throwIssues("apply result", issues);
  return raw;
}
