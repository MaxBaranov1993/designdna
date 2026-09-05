import { randomUUID } from "node:crypto";

/* Typed provider-neutral request envelope.
 *
 * Every provider chat path (desktop IPC → provider-router → adapter, and the
 * Python worker's llm_client) funnels requests through this shape so no
 * parameter is lost silently between the caller and the wire format. Two
 * explicit mechanisms replace silent dropping:
 *
 *  1. assertEnvelopeSupported() throws EnvelopeValidationError when the target
 *     provider cannot represent a requested capability at all (e.g. streaming
 *     against the local ZCode CLI transport).
 *  2. adaptEnvelopeForProvider() removes value-level mismatches (e.g. Kimi k3
 *     only accepts temperature=1) and RETURNS every removal as
 *     {field, reason} so callers surface them; nothing disappears quietly.
 *
 * Secrets never live in the envelope — credentials are resolved by adapters
 * from the CredentialStore at call time. redactForLog() additionally strips
 * key/token-like values before logging or echoing an envelope back. */

export const ENVELOPE_VERSION = 1;

export const REASONING_EFFORTS = new Set(["minimal", "low", "medium", "high", "max", "xhigh"]);
export const MESSAGE_ROLES = new Set(["system", "user", "assistant", "tool"]);
export const TOOL_CHOICES = new Set(["auto", "none", "required"]);

const MAX_TIMEOUT_MS = 600_000;
const MIN_TIMEOUT_MS = 1_000;
const MAX_MESSAGE_CHARS = 400_000;
const MAX_TOOLS = 64;

/* Allowed nested-shape keys — anything else is a loud validation issue. */
const MESSAGE_FIELDS = new Set(["role", "content", "tool_calls", "toolCalls", "tool_call_id", "toolCallId", "name", "toolName"]);
const TOOL_CALL_FIELDS = new Set(["id", "type", "function", "name", "arguments"]); // name/arguments: flat UI alias
const TOOL_CALL_FN_FIELDS = new Set(["name", "arguments"]);
const REASONING_FIELDS = new Set(["effort", "budgetTokens", "budget_tokens"]);
const RESPONSE_FORMAT_FIELDS = new Set(["type", "jsonSchema", "json_schema"]);
const JSON_SCHEMA_FIELDS = new Set(["name", "schema"]);
const TOOL_CHOICE_FIELDS = new Set(["name"]);
const TOOL_WRAPPER_FIELDS = new Set(["type", "function"]);
const TOOL_FN_FIELDS = new Set(["name", "description", "parameters"]);
const TEXT_PART_FIELDS = new Set(["type", "text"]);
const IMAGE_PART_FIELDS = new Set(["type", "image_url"]);
const IMAGE_URL_FIELDS = new Set(["url", "detail"]);
/** Tool-argument/result limits are UTF-8 BYTES, not UTF-16 code units. */
export const MAX_TOOL_ARGUMENTS_CHARS = 16_000;
const UTF8 = new TextEncoder();
const utf8Bytes = (value) => UTF8.encode(value).length;

/* No silent clipping anywhere in this module: every cap is a structured
 * EnvelopeValidationError issue. The bounded fallback values below exist only
 * so validation can finish collecting ALL issues — createEnvelope throws
 * before any network activity whenever issues is non-empty. */
function boundedString(value, field, maxBytes, issues) {
  const text = String(value);
  if (utf8Bytes(text) > maxBytes) {
    issues.push(issue(field, `exceeds ${maxBytes} UTF-8 bytes`));
    return text.slice(0, maxBytes);
  }
  return text; // accepted bytes pass through unchanged
}

function boundedCount(items, field, max, issues) {
  if (items.length > max) issues.push(issue(field, `at most ${max} entries are supported`));
  return items.slice(0, max);
}

export class EnvelopeValidationError extends Error {
  constructor(issues) {
    super(`Invalid chat request envelope: ${issues.map((i) => i.message || String(i)).join("; ")}`);
    this.name = "EnvelopeValidationError";
    this.issues = issues;
    this.code = "ENVELOPE_INVALID";
  }
}

export class UnsupportedCapabilityError extends Error {
  constructor(provider, issues) {
    super(`Provider "${provider}" does not support: ${issues.map((i) => i.field).join(", ")}`);
    this.name = "UnsupportedCapabilityError";
    this.code = "UNSUPPORTED_CAPABILITY";
    this.provider = provider;
    this.issues = issues;
  }
}

/** Structured tool_call arguments failure: field + code so callers surface the
 *  exact location instead of a text match. Thrown BEFORE MCP execution or a
 *  second network round — never after bytes hit the wire. */
export class ToolArgumentsError extends Error {
  constructor(field, reason) {
    super(`Invalid tool_call arguments at ${field}: ${reason}`);
    this.name = "ToolArgumentsError";
    this.code = "TOOL_ARGUMENTS_INVALID";
    this.field = field;
  }
}

/* Z.AI GLM-5.3 documents tool_calls[].function.arguments as an OBJECT in
 * responses, while the OpenAI-compatible request wire form is a JSON string.
 * One canonicalization rule for both directions:
 *  - strings pass VERBATIM (never reformatted, never truncated);
 *  - plain objects/arrays serialize deterministically (recursively sorted
 *    keys) so round-two resubmission is byte-stable;
 *  - null, primitives, cyclic structures, non-plain/non-serializable values
 *    and oversized payloads are rejected loudly via ToolArgumentsError. */
function canonicalizeJson(value, field, seen) {
  if (value === null) return "null";
  const type = typeof value;
  if (type === "string" || type === "boolean") return JSON.stringify(value);
  if (type === "number") {
    if (!Number.isFinite(value)) throw new ToolArgumentsError(field, "non-finite number is not valid JSON");
    return JSON.stringify(value);
  }
  if (Array.isArray(value) || type === "object") {
    if (seen.has(value)) throw new ToolArgumentsError(field, "cyclic structure cannot be serialized");
    const prototype = Object.getPrototypeOf(value);
    if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) {
      throw new ToolArgumentsError(field, `non-plain object (${value.constructor?.name || "unknown"}) is not serializable`);
    }
    seen.add(value);
    try {
      if (Array.isArray(value)) {
        // Index-based walk: sparse-array holes serialize as null, matching
        // JSON.stringify semantics instead of producing invalid "[,]".
        const parts = [];
        for (let i = 0; i < value.length; i++) {
          parts.push(canonicalizeJson(i in value ? value[i] : null, field, seen));
        }
        return `[${parts.join(",")}]`;
      }
      const parts = Object.keys(value).sort()
        .map((key) => `${JSON.stringify(key)}:${canonicalizeJson(value[key], field, seen)}`);
      return `{${parts.join(",")}}`;
    } finally {
      seen.delete(value);
    }
  }
  throw new ToolArgumentsError(field, `non-serializable type "${type}"`);
}

export function canonicalToolArguments(value, field = "arguments") {
  if (typeof value === "string") {
    // Limits are UTF-8 bytes — a 6000-char string can exceed 16000 bytes.
    if (utf8Bytes(value) > MAX_TOOL_ARGUMENTS_CHARS) {
      throw new ToolArgumentsError(field, `string exceeds ${MAX_TOOL_ARGUMENTS_CHARS} UTF-8 bytes`);
    }
    // The wire form stays byte-for-byte verbatim, but the string must be
    // parseable JSON encoding an object or array — never null/primitives.
    let parsed;
    try {
      parsed = JSON.parse(value);
    } catch {
      throw new ToolArgumentsError(field, "malformed JSON string");
    }
    if (parsed === null || typeof parsed !== "object") {
      throw new ToolArgumentsError(field, "arguments must encode a JSON object or array");
    }
    return value;
  }
  if (value == null) {
    throw new ToolArgumentsError(field, 'null/missing arguments are not allowed — use an object or "{}"');
  }
  if (typeof value !== "object") {
    throw new ToolArgumentsError(field, `primitive "${typeof value}" is not a valid tool arguments payload`);
  }
  const out = canonicalizeJson(value, field, new Set());
  if (utf8Bytes(out) > MAX_TOOL_ARGUMENTS_CHARS) {
    throw new ToolArgumentsError(field, `serialized arguments exceed ${MAX_TOOL_ARGUMENTS_CHARS} UTF-8 bytes`);
  }
  return out;
}

function issue(field, message) {
  return { field, message };
}

/* Nested-shape discipline: unknown nested fields are rejected the same way as
 * unknown top-level ones — a silently dropped key would let a caller believe
 * an ignored parameter was transported. */
function rejectUnknownKeys(obj, allowed, field, issues) {
  for (const key of Object.keys(obj)) {
    if (!allowed.has(key)) {
      issues.push(issue(`${field}.${key}`, "unknown field — it would be silently ignored"));
    }
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Normalize + validate a caller-supplied request into a typed envelope.
 *  Throws EnvelopeValidationError listing every problem at once. */
const KNOWN_ENVELOPE_FIELDS = new Set([
  "version", "id", "provider", "model", "system", "messages", "temperature",
  "topP", "maxOutputTokens", "reasoning", "responseFormat", "stop", "seed",
  "stream", "toolChoice", "parallelToolCalls", "tools", "providerOptions",
  "timeoutMs", "metadata",
  // documented snake_case aliases
  "top_p", "max_output_tokens", "response_format", "tool_choice",
  "parallel_tool_calls", "provider_options", "timeout_ms",
  // legacy desktop transport field consumed by the router (codex profile),
  // never forwarded to the wire
  "profile",
]);

export function createEnvelope(input) {
  const inputIsObject = isPlainObject(input);
  const raw = inputIsObject ? input : {};
  const issues = [];

  if (!inputIsObject) issues.push(issue("$", "request envelope must be an object"));

  // Unknown top-level fields are rejected: a caller must never believe an
  // ignored parameter was transported.
  for (const key of Object.keys(raw)) {
    if (!KNOWN_ENVELOPE_FIELDS.has(key)) {
      issues.push(issue(key, `unknown envelope field "${key}" — it would be silently ignored`));
    }
  }

  if (raw.version != null && raw.version !== ENVELOPE_VERSION) {
    issues.push(issue("version", `version must be ${ENVELOPE_VERSION}`));
  }
  if (raw.provider != null && typeof raw.provider !== "string") {
    issues.push(issue("provider", "provider must be a string"));
  }
  const provider = typeof raw.provider === "string" && raw.provider ? raw.provider : "auto";
  if (!new Set(["auto", "codex", "claude", "openai", "astra", "kimi", "glm", "zai", "zcode", "grok"]).has(provider)) {
    issues.push(issue("provider", `unknown provider "${provider}"`));
  }

  if (raw.model != null && typeof raw.model !== "string") {
    issues.push(issue("model", "model must be a string"));
  } else if (raw.model != null && !/^[A-Za-z0-9][A-Za-z0-9._\/-]{0,127}$/.test(raw.model)) {
    issues.push(issue("model", "model must be a short provider model id"));
  }

  if (raw.system != null && typeof raw.system !== "string") {
    issues.push(issue("system", "system prompt must be a string"));
  }
  const system = typeof raw.system === "string" ? raw.system : null;
  if (system && utf8Bytes(system) > MAX_MESSAGE_CHARS) {
    issues.push(issue("system", `system prompt exceeds ${MAX_MESSAGE_CHARS} UTF-8 bytes`));
  }

  const messages = normalizeMessages(raw.messages, issues);

  const envelope = {
    version: ENVELOPE_VERSION,
    id: typeof raw.id === "string" && raw.id ? raw.id : randomUUID(),
    provider,
    model: typeof raw.model === "string" ? raw.model : null,
    system,
    messages,
    temperature: numberOrNull(raw.temperature, "temperature", 0, 2, issues),
    topP: numberOrNull(raw.topP ?? raw.top_p, "topP", 0, 1, issues),
    maxOutputTokens: positiveIntOrNull(raw.maxOutputTokens ?? raw.max_output_tokens, "maxOutputTokens", issues),
    reasoning: normalizeReasoning(raw.reasoning, issues),
    responseFormat: normalizeResponseFormat(raw.responseFormat ?? raw.response_format, issues),
    stop: normalizeStop(raw.stop, issues),
    seed: nonNegativeIntOrNull(raw.seed, "seed", issues),
    stream: booleanOrNull(raw.stream, "stream", issues),
    toolChoice: normalizeToolChoice(raw.toolChoice ?? raw.tool_choice, issues),
    parallelToolCalls: booleanOrNull(raw.parallelToolCalls ?? raw.parallel_tool_calls, "parallelToolCalls", issues),
    tools: normalizeTools(raw.tools, issues),
    providerOptions: normalizeProviderOptions(raw.providerOptions ?? raw.provider_options, issues),
    timeoutMs: boundedTimeout(raw.timeoutMs ?? raw.timeout_ms, issues),
    metadata: isPlainObject(raw.metadata)
      ? normalizeMetadata(raw.metadata, issues)
      : {},
  };

  if (raw.id != null && (typeof raw.id !== "string" || !raw.id)) {
    issues.push(issue("id", "id must be a non-empty string"));
  } else if (typeof raw.id === "string" && utf8Bytes(raw.id) > 128) {
    issues.push(issue("id", "id exceeds 128 UTF-8 bytes"));
  }
  if (raw.metadata != null && !isPlainObject(raw.metadata)) {
    issues.push(issue("metadata", "metadata must be an object of string values"));
  }

  if (envelope.tools?.length && envelope.toolChoice === "none") {
    issues.push(issue("toolChoice", "tools are attached but toolChoice is 'none'"));
  }
  if (envelope.stream === true) {
    issues.push(issue("stream", "streaming is not supported by desktop transports; use a non-streaming request"));
  }
  if (issues.length) throw new EnvelopeValidationError(issues);
  return envelope;
}

function normalizeMetadata(input, issues) {
  const entries = Object.entries(input);
  if (entries.length > 16) issues.push(issue("metadata", "at most 16 entries are supported"));
  return Object.fromEntries(entries.slice(0, 16).map(([key, value], index) => {
    if (typeof value !== "string") {
      // Нет молчаливой String()-коэрции: значение либо строка, либо ошибка.
      issues.push(issue(`metadata.${String(key)}`, "metadata values must be strings"));
    }
    return [
      boundedString(key, `metadata[${index}].key`, 64, issues),
      boundedString(typeof value === "string" ? value : "", `metadata.${String(key)}`, 256, issues),
    ];
  }));
}

function normalizeMessages(input, issues) {
  if (!Array.isArray(input) || !input.length) {
    issues.push(issue("messages", "at least one message is required"));
    return [];
  }
  return boundedCount(input, "messages", 128, issues).map((message, index) => {
    if (!isPlainObject(message)) {
      issues.push(issue(`messages[${index}]`, "message must be an object"));
      return null;
    }
    const role = String(message.role || "");
    rejectUnknownKeys(message, MESSAGE_FIELDS, `messages[${index}]`, issues);
    if (!MESSAGE_ROLES.has(role)) {
      issues.push(issue(`messages[${index}].role`, `unsupported role "${role}"`));
    }
    const normalized = { role, content: null, name: null, toolCalls: null, toolCallId: null, toolName: null };
    if (role === "tool") {
      if (message.tool_call_id != null && message.toolCallId != null) {
        issues.push(issue(`messages[${index}].tool_call_id`, "provide only one of tool_call_id or toolCallId"));
      }
      if (message.name != null && message.toolName != null) {
        issues.push(issue(`messages[${index}].name`, "provide only one of name or toolName"));
      }
      const rawToolCallId = message.tool_call_id ?? message.toolCallId ?? "";
      const rawToolName = message.name ?? message.toolName ?? "";
      if (typeof rawToolCallId !== "string") issues.push(issue(`messages[${index}].tool_call_id`, "tool_call_id must be a string"));
      if (rawToolName !== "" && typeof rawToolName !== "string") issues.push(issue(`messages[${index}].name`, "tool name must be a string"));
      if (message.tool_calls != null || message.toolCalls != null) {
        issues.push(issue(`messages[${index}].tool_calls`, "tool messages cannot contain assistant tool_calls"));
      }
      normalized.toolCallId = boundedString(typeof rawToolCallId === "string" ? rawToolCallId : "", `messages[${index}].tool_call_id`, 128, issues);
      normalized.toolName = boundedString(typeof rawToolName === "string" ? rawToolName : "", `messages[${index}].name`, 128, issues);
      if (!normalized.toolCallId) {
        issues.push(issue(`messages[${index}].tool_call_id`, "tool message requires tool_call_id"));
      }
      normalized.content = normalizeContent(message.content, index, issues);
      if (!normalized.content) {
        issues.push(issue(`messages[${index}].content`, "tool message content is empty"));
      }
      return normalized;
    }
    if (message.tool_call_id != null || message.toolCallId != null || message.toolName != null) {
      issues.push(issue(`messages[${index}].tool_call_id`, "only tool messages may carry tool_call_id/toolName"));
    }
    if (message.name != null) {
      if (typeof message.name !== "string") issues.push(issue(`messages[${index}].name`, "message name must be a string"));
      else normalized.name = boundedString(message.name, `messages[${index}].name`, 128, issues);
    }
    if (role === "assistant") {
      // Accept both the wire shape (tool_calls) and the UI history shape
      // (toolCalls) — the desktop AgentWorkspace stores camelCase history and
      // resubmits it verbatim as envelope.messages on later rounds.
      if (message.tool_calls != null && message.toolCalls != null) {
        issues.push(issue(`messages[${index}].tool_calls`, "provide only one of tool_calls or toolCalls"));
      }
      if ((message.tool_calls != null && !Array.isArray(message.tool_calls))
        || (message.toolCalls != null && !Array.isArray(message.toolCalls))) {
        issues.push(issue(`messages[${index}].tool_calls`, "tool_calls must be an array"));
      }
      const calls = Array.isArray(message.tool_calls) ? message.tool_calls
        : Array.isArray(message.toolCalls) ? message.toolCalls
        : null;
      if (calls) normalized.toolCalls = normalizeToolCalls(calls, index, issues);
    } else if (message.tool_calls != null || message.toolCalls != null) {
      issues.push(issue(`messages[${index}].tool_calls`, "only assistant messages may contain tool_calls"));
    }
    normalized.content = normalizeContent(message.content, index, issues);
    if (!normalized.content && !normalized.toolCalls?.length) {
      issues.push(issue(`messages[${index}].content`, "message content is empty"));
    }
    return normalized;
  }).filter(Boolean);
}

function normalizeToolCalls(input, index, issues) {
  return boundedCount(input, `messages[${index}].tool_calls`, 32, issues).map((call, callIndex) => {
    if (!isPlainObject(call)) {
      issues.push(issue(`messages[${index}].tool_calls[${callIndex}]`, "tool_call must be an object"));
      return null;
    }
    const callField = `messages[${index}].tool_calls[${callIndex}]`;
    rejectUnknownKeys(call, TOOL_CALL_FIELDS, callField, issues);
    if (call.type != null && call.type !== "function") issues.push(issue(`${callField}.type`, 'tool_call type must be "function"'));
    if (call.function != null && !isPlainObject(call.function)) issues.push(issue(`${callField}.function`, "function must be an object"));
    if (isPlainObject(call.function) && (call.name != null || call.arguments != null)) {
      issues.push(issue(callField, "use either nested function or flat UI aliases, not both"));
    }
    if (typeof call.id !== "string") issues.push(issue(`${callField}.id`, "tool_call id must be a string"));
    const id = boundedString(typeof call.id === "string" ? call.id : "", `${callField}.id`, 128, issues);
    const fn = isPlainObject(call.function) ? call.function : {};
    if (isPlainObject(call.function)) rejectUnknownKeys(call.function, TOOL_CALL_FN_FIELDS, `${callField}.function`, issues);
    // Wire shape is {function: {name, arguments}}; the UI history shape is the
    // flat {id, name, arguments} — both normalize to the wire shape.
    const rawName = fn.name ?? call.name ?? "";
    if (typeof rawName !== "string") issues.push(issue(`${callField}.function.name`, "tool_call function.name must be a string"));
    const name = boundedString(typeof rawName === "string" ? rawName : "", `${callField}.function.name`, 128, issues);
    const argsField = `messages[${index}].tool_calls[${callIndex}].function.arguments`;
    let args = "{}";
    try {
      args = canonicalToolArguments(fn.arguments ?? call.arguments, argsField);
    } catch (error) {
      if (!(error instanceof ToolArgumentsError)) throw error;
      // Aggregated with the other envelope issues → one loud structured
      // EnvelopeValidationError before any network round.
      issues.push(issue(argsField, error.message));
    }
    if (!id) issues.push(issue(`messages[${index}].tool_calls[${callIndex}].id`, "tool_call requires id"));
    if (!name) issues.push(issue(`messages[${index}].tool_calls[${callIndex}].function.name`, "tool_call requires function.name"));
    return { id, type: "function", function: { name, arguments: args } };
  }).filter(Boolean);
}

/** Content stays structured: a plain string becomes [{type:"text"}] so
 *  multimodal parts survive every hop instead of being stringified away. */
function normalizeContent(content, index, issues) {
  if (typeof content === "string") {
    const text = boundedString(content, `messages[${index}].content`, MAX_MESSAGE_CHARS, issues);
    return text.trim() ? [{ type: "text", text }] : null;
  }
  if (!Array.isArray(content)) {
    issues.push(issue(`messages[${index}].content`, "content must be a string or an array of parts"));
    return null;
  }
  const parts = boundedCount(content, `messages[${index}].content`, 32, issues).map((part, partIndex) => {
    if (!isPlainObject(part)) {
      issues.push(issue(`messages[${index}].content[${partIndex}]`, "part must be an object"));
      return null;
    }
    if (part.type === "text") {
      rejectUnknownKeys(part, TEXT_PART_FIELDS, `messages[${index}].content[${partIndex}]`, issues);
      if (typeof part.text !== "string") {
        issues.push(issue(`messages[${index}].content[${partIndex}].text`, "text must be a string"));
        return null;
      }
      const text = boundedString(part.text, `messages[${index}].content[${partIndex}].text`, MAX_MESSAGE_CHARS, issues);
      return text.trim() ? { type: "text", text } : null;
    }
    if (part.type === "image_url") {
      const partField = `messages[${index}].content[${partIndex}]`;
      rejectUnknownKeys(part, IMAGE_PART_FIELDS, partField, issues);
      if (!isPlainObject(part.image_url)) {
        issues.push(issue(`${partField}.image_url`, "image_url must be an object"));
        return null;
      }
      rejectUnknownKeys(part.image_url, IMAGE_URL_FIELDS, `${partField}.image_url`, issues);
      if (typeof part.image_url.url !== "string") {
        issues.push(issue(`${partField}.image_url.url`, "url must be a string"));
        return null;
      }
      const url = boundedString(part.image_url.url, `${partField}.image_url.url`, 8_000_000, issues);
      if (!/^data:image\/[a-z0-9.+-]+;base64,/.test(url) && !/^https:\/\//.test(url)) {
        issues.push(issue(`${partField}.image_url.url`, "image_url must be a data: or https: url"));
        return null;
      }
      const detail = part.image_url.detail;
      if (detail != null && !new Set(["auto", "low", "high"]).has(detail)) {
        issues.push(issue(`${partField}.image_url.detail`, "detail must be auto|low|high"));
      }
      return { type: "image_url", image_url: { url, ...(detail == null ? {} : { detail }) } };
    }
    issues.push(issue(`messages[${index}].content[${partIndex}]`, `unsupported part type "${part.type}"`));
    return null;
  }).filter(Boolean);
  return parts.length ? parts : null;
}

function normalizeReasoning(input, issues) {
  if (input == null) return null;
  if (typeof input === "string") {
    if (!REASONING_EFFORTS.has(input)) {
      issues.push(issue("reasoning", `effort must be one of ${[...REASONING_EFFORTS].join("/")}`));
      return null;
    }
    return { effort: input, budgetTokens: null };
  }
  if (!isPlainObject(input)) {
    issues.push(issue("reasoning", "reasoning must be {effort, budgetTokens?}"));
    return null;
  }
  rejectUnknownKeys(input, REASONING_FIELDS, "reasoning", issues);
  const effort = String(input.effort || "");
  if (!REASONING_EFFORTS.has(effort)) {
    issues.push(issue("reasoning.effort", `effort must be one of ${[...REASONING_EFFORTS].join("/")}`));
  }
  const budgetTokens = positiveIntOrNull(input.budgetTokens ?? input.budget_tokens, "reasoning.budgetTokens", issues);
  if (budgetTokens != null && budgetTokens > 128_000) {
    issues.push(issue("reasoning.budgetTokens", "budgetTokens must be ≤ 128000"));
  }
  return { effort, budgetTokens };
}

function normalizeResponseFormat(input, issues) {
  if (input == null) return null;
  if (typeof input === "string") {
    if (!new Set(["json_object", "text"]).has(input)) {
      issues.push(issue("responseFormat", `type must be json_object|json_schema|text, got "${input}"`));
      return null;
    }
    return { type: input };
  }
  if (!isPlainObject(input)) {
    issues.push(issue("responseFormat", "responseFormat must be {type, jsonSchema?}"));
    return null;
  }
  rejectUnknownKeys(input, RESPONSE_FORMAT_FIELDS, "responseFormat", issues);
  const type = String(input.type || "");
  if (!new Set(["json_object", "json_schema", "text"]).has(type)) {
    issues.push(issue("responseFormat.type", `type must be json_object|json_schema|text, got "${type}"`));
    return null;
  }
  if (type === "json_schema") {
    const schema = input.jsonSchema ?? input.json_schema;
    if (!isPlainObject(schema) || !isPlainObject(schema.schema)) {
      issues.push(issue("responseFormat.jsonSchema", "json_schema requires {name, schema}"));
      return { type };
    }
    rejectUnknownKeys(schema, JSON_SCHEMA_FIELDS, "responseFormat.jsonSchema", issues);
    return {
      type,
      jsonSchema: {
        name: (() => {
          if (schema.name != null && typeof schema.name !== "string") {
            issues.push(issue("responseFormat.jsonSchema.name", "schema name must be a string"));
            return "response";
          }
          return boundedString(schema.name || "response", "responseFormat.jsonSchema.name", 128, issues);
        })(),
        schema: schema.schema,
      },
    };
  }
  return { type };
}

function normalizeStop(input, issues) {
  if (input == null) return null;
  if (typeof input === "string") return input ? [boundedString(input, "stop[0]", 256, issues)] : null;
  if (!Array.isArray(input)) {
    issues.push(issue("stop", "stop must be a string or an array of strings"));
    return null;
  }
  const stops = boundedCount(input, "stop", 4, issues)
    .map((stop, index) => {
      if (typeof stop !== "string") {
        issues.push(issue(`stop[${index}]`, "stop entries must be strings"));
        return "";
      }
      return boundedString(stop, `stop[${index}]`, 256, issues);
    })
    .filter(Boolean);
  return stops.length ? stops : null;
}

function normalizeToolChoice(input, issues) {
  if (input == null) return null;
  if (typeof input === "string") {
    if (!TOOL_CHOICES.has(input)) {
      issues.push(issue("toolChoice", `toolChoice must be auto|none|required|{name}, got "${input}"`));
      return null;
    }
    return input;
  }
  if (isPlainObject(input) && input.name) {
    rejectUnknownKeys(input, TOOL_CHOICE_FIELDS, "toolChoice", issues);
    if (typeof input.name !== "string") {
      issues.push(issue("toolChoice.name", "toolChoice name must be a string"));
      return null;
    }
    return { name: boundedString(input.name, "toolChoice.name", 128, issues) };
  }
  issues.push(issue("toolChoice", "toolChoice must be auto|none|required|{name}"));
  return null;
}

function normalizeTools(input, issues) {
  if (input == null) return null;
  if (!Array.isArray(input) || !input.length) return null;
  if (input.length > MAX_TOOLS) {
    issues.push(issue("tools", `at most ${MAX_TOOLS} tools are supported`));
  }
  const tools = input.slice(0, MAX_TOOLS).map((tool, index) => {
    if (isPlainObject(tool)) {
      rejectUnknownKeys(tool, isPlainObject(tool.function) ? TOOL_WRAPPER_FIELDS : TOOL_FN_FIELDS, `tools[${index}]`, issues);
    }
    if (isPlainObject(tool) && isPlainObject(tool.function) && tool.type != null && tool.type !== "function") {
      issues.push(issue(`tools[${index}].type`, 'tool type must be "function"'));
    }
    const fn = isPlainObject(tool) && isPlainObject(tool.function) ? tool.function : tool;
    if (isPlainObject(fn)) rejectUnknownKeys(fn, TOOL_FN_FIELDS, `tools[${index}].function`, issues);
    if (!isPlainObject(fn)) {
      issues.push(issue(`tools[${index}].function`, "tool function must be an object"));
      return null;
    }
    if (typeof fn.name !== "string") issues.push(issue(`tools[${index}].name`, "tool name must be a string"));
    const name = typeof fn.name === "string" ? fn.name : "";
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(name)) {
      issues.push(issue(`tools[${index}].name`, "tool name must be 1-128 [A-Za-z0-9_-]"));
      return null;
    }
    if (fn.description != null && typeof fn.description !== "string") {
      issues.push(issue(`tools[${index}].function.description`, "tool description must be a string"));
    }
    if (fn.parameters != null && !isPlainObject(fn.parameters)) {
      issues.push(issue(`tools[${index}].function.parameters`, "tool parameters must be a JSON Schema object"));
    }
    const parameters = isPlainObject(fn.parameters) ? fn.parameters : { type: "object", properties: {} };
    return {
      type: "function",
      function: {
        name,
        description: boundedString(typeof fn.description === "string" ? fn.description : "", `tools[${index}].function.description`, 1024, issues),
        parameters,
      },
    };
  }).filter(Boolean);
  return tools.length ? tools : null;
}

/* providerOptions carry provider-specific extras to the wire via
 * Object.assign(payload, extras) — so they must be bounded, JSON-safe plain
 * data and must never collide with reserved canonical wire fields. */
const PROVIDER_OPTIONS_MAX_BYTES = 8_192;
const PROVIDER_OPTIONS_MAX_DEPTH = 8;
const RESERVED_WIRE_FIELDS = new Set([
  "model", "messages", "system", "tools", "tool_choice", "response_format",
  "reasoning", "reasoning_effort", "thinking", "stream",
  "temperature", "top_p", "max_tokens", "max_completion_tokens", "seed",
  "stop", "parallel_tool_calls", "user", "user_id", "request_id", "metadata",
]);
const FORBIDDEN_OPTION_KEYS = new Set(["__proto__", "constructor", "prototype"]);

function checkJsonSafe(value, field, issues, seen, depth) {
  if (value === null) return;
  const type = typeof value;
  if (type === "string" || type === "boolean") return;
  if (type === "number") {
    if (!Number.isFinite(value)) issues.push(issue(field, "non-finite number is not JSON-safe"));
    return;
  }
  if (Array.isArray(value) || type === "object") {
    if (!Array.isArray(value)) {
      const prototype = Object.getPrototypeOf(value);
      if (prototype !== Object.prototype && prototype !== null) {
        issues.push(issue(field, "non-plain object is not JSON-safe"));
        return;
      }
    }
    if (seen.has(value)) {
      issues.push(issue(field, "cyclic structure is not JSON-safe"));
      return;
    }
    if (depth > PROVIDER_OPTIONS_MAX_DEPTH) {
      issues.push(issue(field, `nesting deeper than ${PROVIDER_OPTIONS_MAX_DEPTH} is not supported`));
      return;
    }
    seen.add(value);
    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index++) {
        checkJsonSafe(value[index], `${field}[${index}]`, issues, seen, depth + 1);
      }
    } else {
      for (const key of Object.keys(value)) {
        if (FORBIDDEN_OPTION_KEYS.has(key)) {
          issues.push(issue(`${field}.${key}`, "forbidden key (prototype-pollution risk)"));
          continue;
        }
        checkJsonSafe(value[key], `${field}.${key}`, issues, seen, depth + 1);
      }
    }
    seen.delete(value);
    return;
  }
  issues.push(issue(field, `non-serializable type "${type}"`));
}

function normalizeProviderOptions(input, issues) {
  if (input == null) return {};
  if (!isPlainObject(input)) {
    issues.push(issue("providerOptions", "providerOptions must be an object keyed by provider"));
    return {};
  }
  const out = {};
  for (const [key, value] of Object.entries(input)) {
    const provider = String(key);
    if (!new Set(["openai", "kimi", "glm", "zai", "zcode", "grok", "codex"]).has(provider)) {
      issues.push(issue(`providerOptions.${key}`, `unknown provider key "${key}"`));
      continue;
    }
    if (!isPlainObject(value)) {
      issues.push(issue(`providerOptions.${provider}`, "provider options must be a plain object"));
      continue;
    }
    for (const option of Object.keys(value)) {
      if (RESERVED_WIRE_FIELDS.has(option)) {
        issues.push(issue(`providerOptions.${provider}.${option}`, `reserved canonical wire field "${option}" cannot be overridden via providerOptions`));
      }
    }
    checkJsonSafe(value, `providerOptions.${provider}`, issues, new Set(), 1);
    try {
      if (utf8Bytes(JSON.stringify(value)) > PROVIDER_OPTIONS_MAX_BYTES) {
        issues.push(issue(`providerOptions.${provider}`, `exceeds ${PROVIDER_OPTIONS_MAX_BYTES} UTF-8 bytes`));
      }
    } catch {
      // cyclic/bigint payloads are already reported by checkJsonSafe
    }
    out[provider] = value; // allowed extras are preserved exactly
  }
  return out;
}

function numberOrNull(value, field, min, max, issues) {
  if (value == null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
    issues.push(issue(field, `must be a number in [${min}, ${max}]`));
    return null;
  }
  return value;
}

function positiveIntOrNull(value, field, issues) {
  if (value == null) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0 || value > 1_000_000) {
    issues.push(issue(field, "must be a positive integer"));
    return null;
  }
  return value;
}

function nonNegativeIntOrNull(value, field, issues) {
  if (value == null) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 1_000_000) {
    issues.push(issue(field, "must be a non-negative integer"));
    return null;
  }
  return value;
}

function booleanOrNull(value, field, issues) {
  if (value == null) return null;
  if (typeof value !== "boolean") {
    issues.push(issue(field, "must be a boolean"));
    return null;
  }
  return value;
}

function boundedTimeout(value, issues) {
  if (value == null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < MIN_TIMEOUT_MS) {
    issues.push(issue("timeoutMs", `timeoutMs must be ≥ ${MIN_TIMEOUT_MS}ms`));
    return null;
  }
  if (value > MAX_TIMEOUT_MS) {
    // Loud, not clamped: a caller must never believe a longer timeout applies.
    issues.push(issue("timeoutMs", `timeoutMs must be ≤ ${MAX_TIMEOUT_MS}ms`));
    return null;
  }
  return value;
}

/* ---------- capability matrix ----------
 *
 * "hard" — the provider cannot represent the field at all; requests carrying
 *          it fail loudly via assertEnvelopeSupported().
 * "value" — the provider accepts the field only with specific values; other
 *          values are removed by adaptEnvelopeForProvider() and returned in
 *          `dropped` (explicit, surfaced to callers — never silent).
 * unset   — fully supported. */

/* Kimi coding API (k3 series) capability model.
 * Tool calling, tool_choice and parallel_tool_calls are supported.
 * Reasoning controls, forced response_format, stop sequences and seed are not
 * accepted on the managed coding endpoint; temperature/top_p are controlled
 * server-side for the coding profile. */
const KIMI_LIMITS = {
  temperature: { reason: "kimi/k3 managed coding endpoint applies temperature server-side" },
  topP: { reason: "kimi/k3 managed endpoint ignores top_p" },
  responseFormat: { reason: "kimi/k3 rejects response_format for most models; the prompt already requests JSON" },
  reasoning: { reason: "kimi/k3 has no reasoning controls on this endpoint" },
  stop: { reason: "kimi/k3 managed endpoint rejects stop sequences" },
  seed: { reason: "kimi/k3 is not deterministic; seed is not accepted" },
};

const GLM_LIMITS = {
  reasoningBudget: { reason: "GLM-5.3 exposes reasoning_effort low|high|max, not a token budget" },
  seed: { reason: "GLM v4 endpoint rejects seed" },
};

export const PROVIDER_CAPABILITIES = {
  codex: {
    hard: ["topP", "maxOutputTokens", "reasoning", "responseFormat", "stop", "seed", "toolChoice", "parallelToolCalls", "tools", "providerOptions", "multimodal", "metadata"],
    value: {
      temperature: { reason: "Codex chat profiles control sampling server-side; temperature is ignored" },
    },
  },
  openai: { hard: [], value: {} },
  kimi: {
    // metadata is not documented on the managed coding endpoint — loud, not silent.
    hard: ["metadata"],
    value: KIMI_LIMITS,
  },
  glm: {
    hard: ["parallelToolCalls", "metadata"],
    value: GLM_LIMITS,
  },
  // Direct Z.AI GLM (api.z.ai) — the same v4 API family as Zhipu glm, but a
  // separate provider with its own credential and host; never mixed.
  // Value constraints per the official Z.AI v4 reference (GLM-5.3):
  // temperature [0,1], top_p [0.01,1], max_tokens ≤ 131072, tool_choice only
  // "auto", response_format only text|json_object, stop effectively one word,
  // parallel_tool_calls undocumented (hard). Violations fail loudly BEFORE
  // any network call — no forwarding of likely-400s, no silent drops.
  zai: {
    hard: ["parallelToolCalls", "metadata"],
    value: GLM_LIMITS,
    constraints: (envelope) => {
      const issues = [];
      if (envelope.temperature != null && (envelope.temperature < 0 || envelope.temperature > 1)) {
        issues.push({ field: "temperature", reason: "Z.AI GLM-5.3 accepts temperature in [0, 1]" });
      }
      if (envelope.topP != null && (envelope.topP < 0.01 || envelope.topP > 1)) {
        issues.push({ field: "topP", reason: "Z.AI GLM-5.3 accepts top_p in [0.01, 1]" });
      }
      if (envelope.maxOutputTokens != null && envelope.maxOutputTokens > 131_072) {
        issues.push({ field: "maxOutputTokens", reason: "Z.AI GLM-5.3 accepts max_tokens ≤ 131072" });
      }
      if (envelope.toolChoice != null && envelope.toolChoice !== "auto") {
        issues.push({ field: "toolChoice", reason: 'Z.AI GLM-5.3 supports only tool_choice "auto"' });
      }
      if (envelope.responseFormat != null && envelope.responseFormat.type === "json_schema") {
        issues.push({ field: "responseFormat", reason: "Z.AI GLM-5.3 supports only response_format text|json_object" });
      }
      if (envelope.stop != null && envelope.stop.length > 1) {
        issues.push({ field: "stop", reason: "Z.AI GLM-5.3 effectively supports a single stop word" });
      }
      return issues;
    },
  },
  zcode: {
    hard: ["topP", "maxOutputTokens", "reasoning", "responseFormat", "stop", "seed", "toolChoice", "parallelToolCalls", "tools", "providerOptions", "multimodal", "metadata"],
    value: {
      temperature: { reason: "ZCode CLI agent controls sampling; temperature is not forwardable" },
    },
  },
  grok: {
    hard: ["metadata"],
    value: {},
    constraints: (envelope) => {
      // grok-4.6: stop sequences are incompatible with the reasoning contract.
      const issues = [];
      if (envelope.stop != null) {
        issues.push({ field: "stop", reason: "grok-4.6 does not accept stop sequences" });
      }
      return issues;
    },
  },
};

function envelopeFields(envelope) {
  const present = new Set();
  if (envelope.temperature != null) present.add("temperature");
  if (envelope.topP != null) present.add("topP");
  if (envelope.maxOutputTokens != null) present.add("maxOutputTokens");
  if (envelope.reasoning != null) present.add("reasoning");
  if (envelope.responseFormat != null) present.add("responseFormat");
  if (envelope.stop != null) present.add("stop");
  if (envelope.seed != null) present.add("seed");
  if (envelope.toolChoice != null) present.add("toolChoice");
  if (envelope.parallelToolCalls != null) present.add("parallelToolCalls");
  if (envelope.tools != null) present.add("tools");
  if (envelope.providerOptions && Object.keys(envelope.providerOptions).length) present.add("providerOptions");
  if (envelope.metadata && Object.keys(envelope.metadata).length) present.add("metadata");
  // Non-text content parts (images) are a transport capability: text-only
  // transports (codex, zcode) must reject them loudly instead of flattening
  // them into "[image attached]" placeholders.
  if (envelope.messages?.some((message) => Array.isArray(message.content)
    && message.content.some((part) => part.type !== "text"))) {
    present.add("multimodal");
  }
  return present;
}

/** Hard capability check: throws UnsupportedCapabilityError when a field
 *  cannot be represented by the provider at all. Called before any network
 *  activity so a misconfigured node fails fast with the full field list. */
export function assertEnvelopeSupported(envelope, provider) {
  const caps = PROVIDER_CAPABILITIES[provider];
  if (!caps) throw new Error(`No capability matrix for provider "${provider}"`);
  const present = envelopeFields(envelope);
  const unsupported = [...present].filter((field) => caps.hard.includes(field))
    .map((field) => ({ field, reason: `provider "${provider}" cannot transport ${field}` }));
  // Provider value constraints (e.g. Z.AI ranges) are equally loud pre-network
  // failures, reported through the same issues channel.
  const constrained = typeof caps.constraints === "function" ? caps.constraints(envelope) : [];
  const all = [...unsupported, ...constrained];
  if (all.length) throw new UnsupportedCapabilityError(provider, all);
}

/** Value-level adaptation: removes/keeps fields the provider rejects and
 *  returns every removal explicitly. Callers MUST surface `dropped` in their
 *  result — the contract that makes dropping non-silent. */
export function adaptEnvelopeForProvider(envelope, provider) {
  const caps = PROVIDER_CAPABILITIES[provider] || { hard: [], value: {} };
  const adapted = { ...envelope };
  const dropped = [];

  for (const field of caps.hard) {
    if (envelopeFields(adapted).has(field)) {
      // Hard-unsupported fields are the caller's bug: surface as an error,
      // do not quietly strip them here.
      throw new UnsupportedCapabilityError(provider, [{ field, reason: `provider "${provider}" cannot transport ${field}` }]);
    }
  }

  const drop = (field, reason) => {
    if (adapted[field] == null) return;
    dropped.push({ field, reason });
    adapted[field] = null;
  };

  if (caps.value.temperature && envelope.temperature != null && envelope.temperature !== 1) {
    drop("temperature", caps.value.temperature.reason);
  }
  for (const field of ["topP", "reasoning", "responseFormat", "stop", "seed", "parallelToolCalls"]) {
    if (caps.value[field]) drop(field, caps.value[field].reason);
  }
  if (caps.value.reasoningBudget && envelope.reasoning?.budgetTokens != null) {
    adapted.reasoning = { effort: envelope.reasoning.effort, budgetTokens: null };
    dropped.push({ field: "reasoning.budgetTokens", reason: caps.value.reasoningBudget.reason });
  }
  // Provider-specific extras only survive for the addressed provider.
  if (envelope.providerOptions && Object.keys(envelope.providerOptions).length) {
    const own = envelope.providerOptions[provider];
    const foreign = Object.keys(envelope.providerOptions).filter((key) => key !== provider);
    adapted.providerOptions = own ? { [provider]: own } : {};
    for (const key of foreign) {
      dropped.push({ field: `providerOptions.${key}`, reason: `provider-specific extras for "${key}" are not sent to "${provider}"` });
    }
  }
  return { envelope: adapted, dropped };
}

/* ---------- payload building (OpenAI-compatible family) ----------
 *
 * One wire format for openai/kimi/glm/grok with per-provider parameter names,
 * so round-tripping is testable from a single place. */

const JSON_RESPONSE_FORMAT = { type: "json_object" };

/** Build the wire payload for an already-adapted envelope. Returns
 *  {payload, dropped} — `dropped` carries any residual provider-specific
 *  notes (kept explicit for the result transport block). */
export function buildOpenAiCompatiblePayload(adapted, provider, { defaultModel, jsonMode = false } = {}) {
  const payload = {
    model: adapted.model || defaultModel,
    messages: wireMessages(adapted),
  };
  const dropped = [];

  if (adapted.temperature != null) payload.temperature = adapted.temperature;
  if (adapted.topP != null) payload.top_p = adapted.topP;
  if (adapted.maxOutputTokens != null) {
    payload[provider === "openai" ? "max_completion_tokens" : "max_tokens"] = adapted.maxOutputTokens;
  }
  if (adapted.reasoning != null) {
    if (provider === "glm" || provider === "zai") {
      // GLM-5.3 (Z.AI/Zhipu v4): reasoning is always on — thinking.type
      // "disabled" was removed and fails server-side. reasoning_effort accepts
      // low|high|max (max recommended for coding). Legacy canonical values are
      // normalized explicitly with a transport note — never silently.
      payload.thinking = { type: "enabled" };
      const effort = adapted.reasoning.effort;
      if (effort === "low" || effort === "high" || effort === "max") {
        payload.reasoning_effort = effort;
      } else {
        const mapped = effort === "minimal" ? "low" : "high";
        payload.reasoning_effort = mapped;
        dropped.push({ field: "reasoning.effort", reason: `GLM-5.3 reasoning_effort accepts low|high|max; "${effort}" normalized to "${mapped}"` });
      }
    } else if (provider === "grok") {
      // grok-4.6 (xAI): reasoning_effort accepts low|medium|high|xhigh and
      // reasoning cannot be disabled — minimal/max are normalized explicitly
      // with a transport note, never silently.
      const effort = adapted.reasoning.effort;
      if (effort === "low" || effort === "medium" || effort === "high" || effort === "xhigh") {
        payload.reasoning_effort = effort;
      } else {
        const mapped = effort === "minimal" ? "low" : "xhigh";
        payload.reasoning_effort = mapped;
        dropped.push({ field: "reasoning.effort", reason: `grok-4.6 reasoning_effort accepts low|medium|high|xhigh (reasoning cannot be disabled); "${effort}" normalized to "${mapped}"` });
      }
    } else {
      payload.reasoning_effort = adapted.reasoning.effort;
    }
  }
  if (adapted.responseFormat != null) {
    payload.response_format = adapted.responseFormat.type === "json_schema"
      ? { type: "json_schema", json_schema: adapted.responseFormat.jsonSchema }
      : { type: adapted.responseFormat.type };
  } else if (jsonMode) {
    payload.response_format = JSON_RESPONSE_FORMAT;
  }
  if (adapted.stop != null) payload.stop = adapted.stop;
  if (adapted.seed != null && provider !== "glm" && provider !== "zai") payload.seed = adapted.seed;
  if (adapted.tools != null) payload.tools = adapted.tools;
  if (adapted.toolChoice != null) {
    payload.tool_choice = typeof adapted.toolChoice === "string"
      ? adapted.toolChoice
      : { type: "function", function: { name: adapted.toolChoice.name } };
  }
  if (adapted.parallelToolCalls != null) payload.parallel_tool_calls = adapted.parallelToolCalls;
  if (adapted.providerOptions?.[provider]) Object.assign(payload, adapted.providerOptions[provider]);
  // Metadata transport is explicit per provider: OpenAI documents a metadata
  // map; everyone else hard-fails in assertEnvelopeSupported before this point.
  if (provider === "openai" && adapted.metadata && Object.keys(adapted.metadata).length) {
    payload.metadata = adapted.metadata;
  }

  if (payload.response_format && payload.tools) {
    delete payload.response_format;
    dropped.push({ field: "responseFormat", reason: "tool-calling requests cannot force a response format on OpenAI-compatible endpoints" });
  }
  return { payload, dropped };
}

function wireMessages(adapted) {
  const messages = [];
  if (adapted.system) messages.push({ role: "system", content: adapted.system });
  for (const message of adapted.messages) {
    if (message.role === "tool") {
      messages.push({
        role: "tool",
        tool_call_id: message.toolCallId,
        name: message.toolName || undefined,
        content: textContent(message.content),
      });
      continue;
    }
    const wire = { role: message.role };
    if (message.name) wire.name = message.name;
    const textOnly = message.content?.length === 1 && message.content[0].type === "text";
    if (message.content?.length) wire.content = textOnly ? message.content[0].text : message.content;
    if (message.toolCalls?.length) wire.tool_calls = message.toolCalls;
    messages.push(wire);
  }
  return messages;
}

function textContent(content) {
  if (!content) return "";
  if (typeof content === "string") return content;
  return content.map((part) => (part.type === "text" ? part.text : `[${part.type}]`)).join("");
}

/** Log-safe serialization: strips values whose keys look like credentials and
 *  truncates long content. Used for every diagnostic/echo path. */
export function redactForLog(value, depth = 0) {
  if (depth > 4) return "…";
  if (Array.isArray(value)) return value.slice(0, 16).map((item) => redactForLog(item, depth + 1));
  if (isPlainObject(value)) {
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      if (/api[-_]?key|token|secret|authorization|credential|password/i.test(key)) {
        out[key] = "[redacted]";
      } else {
        out[key] = redactForLog(item, depth + 1);
      }
    }
    return out;
  }
  if (typeof value === "string") return value.length > 240 ? `${value.slice(0, 240)}…` : value;
  return value;
}
