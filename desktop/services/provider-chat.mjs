import {
  adaptEnvelopeForProvider,
  assertEnvelopeSupported,
  canonicalToolArguments,
  createEnvelope,
} from "./provider-envelope.mjs";
import { SOL_MODEL, openaiModel } from "./openai-models.mjs";

const OPENAI_URL = "https://api.openai.com/v1/responses";
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
    const parts = (message.content || []).map((part) => {
      if (part.type === "text") return {
        type: message.role === "assistant" ? "output_text" : "input_text", text: part.text,
      };
      if (part.type === "image_url" && message.role === "user") return {
        type: "input_image", image_url: part.image_url.url,
        ...(part.image_url.detail ? { detail: part.image_url.detail } : {}),
      };
      throw new Error(`OpenAI: unsupported ${part.type} part for ${message.role}`);
    });
    if (parts.length) input.push({ role: message.role,
      content: parts.every((part) => part.type !== "input_image") ? text : parts });
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

function prepareResponsesPayload(envelope) {
  assertEnvelopeSupported(envelope, "openai");
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "openai");
  const effort = SOL_EFFORTS.has(adapted.reasoning?.effort) ? adapted.reasoning.effort : "medium";
  const payload = {
    model: openaiModel("openai", adapted.model),
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
  if (adapted.responseFormat) {
    payload.text = { format: adapted.responseFormat.type === "json_schema"
      ? { type: "json_schema", ...adapted.responseFormat.jsonSchema }
      : { type: adapted.responseFormat.type } };
  }

  const explicitDrops = [...dropped];
  if (adapted.model && adapted.model.replace(/^openai\//, "") !== payload.model) {
    explicitDrops.push({ field: "model", reason: `Unsupported model replaced by ${payload.model}` });
  }
  if (adapted.temperature != null) {
    explicitDrops.push({ field: "temperature", reason: "OpenAI reasoning is controlled by effort" });
  }
  return { adapted, payload, dropped: explicitDrops };
}

function extractResponsesContent(data) {
  if (data.status && data.status !== "completed") {
    throw providerError("PROVIDER_INCOMPLETE", data.error?.message || data.incomplete_details?.reason || data.status);
  }
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
  const { adapted, payload, dropped } = prepareResponsesPayload(request);
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
    transport: { provider: "openai", model: payload.model, dropped },
  };
}
