import {
  adaptEnvelopeForProvider,
  assertEnvelopeSupported,
  canonicalToolArguments,
  createEnvelope,
} from "./provider-envelope.mjs";

const OPENAI_URL = "https://api.openai.com/v1/responses";
const SOL_MODEL = "gpt-5.6-sol";
const SOL_EFFORTS = new Set(["medium", "high", "max"]);
const DEFAULT_TIMEOUT_MS = 180_000;

function envelopeFromCall(input) {
  if (input?.envelope) return input.envelope;
  return createEnvelope({
    ...(input || {}),
    provider: "openai",
    model: SOL_MODEL,
    messages: input?.messages,
    temperature: input?.temperature,
    tools: input?.tools ?? null,
  });
}

function abortSignalFor({ signal, timeoutMs }) {
  const signals = [AbortSignal.timeout(timeoutMs || DEFAULT_TIMEOUT_MS)];
  if (signal) signals.push(signal);
  if (typeof AbortSignal.any === "function") return AbortSignal.any(signals);
  return signals[0];
}

function providerError(code, cause) {
  const error = new Error(`OpenAI: ${cause?.message || cause}`);
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}

function isAbort(signal, error) {
  return signal?.aborted || error?.name === "AbortError" || error?.name === "TimeoutError";
}

async function postJson(url, body, { headers, signal, fetchImpl = fetch }) {
  const response = await fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}: ${data.error?.message || data.message || "request failed"}`);
    error.status = response.status;
    error.body = data;
    throw error;
  }
  return data;
}

function responsesInput(envelope) {
  const input = [];
  for (const message of envelope.messages || []) {
    const text = (message.content || [])
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n");
    if (message.role === "tool") {
      input.push({ type: "function_call_output", call_id: message.toolCallId, output: text });
      continue;
    }
    if (text) input.push({ role: message.role, content: text });
    for (const call of message.toolCalls || []) {
      input.push({
        type: "function_call",
        call_id: call.id,
        name: call.function.name,
        arguments: call.function.arguments,
      });
    }
  }
  return input;
}

function responsesTools(tools) {
  return (tools || []).map((tool) => ({
    type: "function",
    name: tool.function.name,
    description: tool.function.description || "",
    parameters: tool.function.parameters || { type: "object", properties: {} },
    strict: false,
  }));
}

function prepareSolResponsesPayload(envelope) {
  assertEnvelopeSupported(envelope, "openai");
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "openai");
  const effort = SOL_EFFORTS.has(adapted.reasoning?.effort) ? adapted.reasoning.effort : "medium";
  const payload = {
    model: SOL_MODEL,
    input: responsesInput(adapted),
    reasoning: { effort },
    store: false,
  };
  if (adapted.system) payload.instructions = adapted.system;
  if (adapted.maxOutputTokens != null) payload.max_output_tokens = adapted.maxOutputTokens;
  if (adapted.tools?.length) payload.tools = responsesTools(adapted.tools);
  if (adapted.toolChoice != null) {
    payload.tool_choice = typeof adapted.toolChoice === "object"
      ? { type: "function", name: adapted.toolChoice.name }
      : adapted.toolChoice;
  }
  if (adapted.parallelToolCalls != null) payload.parallel_tool_calls = adapted.parallelToolCalls;
  if (adapted.metadata) payload.metadata = adapted.metadata;

  const explicitDrops = [...dropped];
  if (adapted.model && adapted.model !== SOL_MODEL) {
    explicitDrops.push({ field: "model", reason: `DesignDNA agents are fixed to ${SOL_MODEL}` });
  }
  if (adapted.temperature != null) {
    explicitDrops.push({ field: "temperature", reason: "Sol reasoning is controlled by effort" });
  }
  return { adapted, payload, dropped: explicitDrops };
}

function extractResponsesContent(data) {
  const content = [];
  const toolCalls = [];
  for (const item of data.output || []) {
    if (item?.type === "message") {
      for (const part of item.content || []) {
        if (part?.type === "output_text" && part.text) content.push(String(part.text));
      }
    } else if (item?.type === "function_call") {
      toolCalls.push({
        id: String(item.call_id || item.id || ""),
        name: String(item.name || ""),
        arguments: canonicalToolArguments(
          item.arguments,
          `OpenAI function_call ${item.call_id || item.id || "unknown"}.arguments`,
        ),
      });
    }
  }
  const text = content.join("\n") || String(data.output_text || "");
  if (!text.trim() && !toolCalls.length) throw new Error("OpenAI returned an empty response");
  return { content: text, toolCalls: toolCalls.length ? toolCalls : null };
}

export async function chatWithOpenAI({
  credentials,
  envelope = null,
  messages,
  temperature = 0.8,
  tools = null,
  fetchImpl = fetch,
  environment = process.env,
  signal,
}) {
  const key = credentials.get("openai");
  if (!key) throw new Error("OpenAI is not connected. Add an API key in Agents -> Connections.");
  const request = envelope || envelopeFromCall({ messages, temperature, tools });
  const { adapted, payload, dropped } = prepareSolResponsesPayload(request);
  let response;
  try {
    response = await postJson(environment.DESIGNDNA_OPENAI_URL || OPENAI_URL, payload, {
      headers: { Authorization: `Bearer ${key}` },
      signal: abortSignalFor({ signal, timeoutMs: adapted.timeoutMs }),
      fetchImpl,
    });
  } catch (error) {
    if (isAbort(signal, error)) {
      throw providerError(signal?.aborted ? "PROVIDER_CANCELLED" : "PROVIDER_TIMEOUT", error);
    }
    throw providerError("PROVIDER_HTTP", error);
  }
  const { content, toolCalls } = extractResponsesContent(response);
  return {
    content,
    toolCalls,
    transport: { provider: "openai", model: SOL_MODEL, dropped },
  };
}
