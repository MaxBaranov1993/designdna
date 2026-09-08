import { claudeModel } from "./claude-agent-server.mjs";
import { chatWithOpenAI } from "./provider-chat.mjs";
import { createEnvelope } from "./provider-envelope.mjs";
import { openaiModel } from "./openai-models.mjs";


const SOL_EFFORTS = new Set(["medium", "high", "max"]);
/* Провайдеры, выбираемые пользователем в нодах. openai (Sol) остаётся
 * дефолтом: сохранённые проекты и ретро-выборы мигрируют на него. */
export const SELECTABLE_PROVIDERS = Object.freeze(["openai", "astra", "codex", "claude"]);
const SUPPORTED_PROVIDERS = new Set(SELECTABLE_PROVIDERS);
const DEFAULT_PROVIDER = "openai";

/* GPT (Sol / Astra) работает только по подписке: запросы уходят в Codex CLI
 * app-server с выбранной моделью, а не в OpenAI API по ключу. API-транспорт
 * остаётся доступным лишь явно — параметром gptTransport: "openai" (тесты,
 * DESIGNDNA_GPT_TRANSPORT=openai для отладки). */
export const GPT_TRANSPORTS = Object.freeze(["codex", "openai"]);
export const DEFAULT_GPT_TRANSPORT = GPT_TRANSPORTS.includes(process.env.DESIGNDNA_GPT_TRANSPORT)
  ? process.env.DESIGNDNA_GPT_TRANSPORT
  : "codex";
const GPT_PROVIDERS = new Set(["openai", "astra"]);

function solEffort(value) {
  const effort = typeof value === "string" ? value : value?.effort;
  return SOL_EFFORTS.has(effort) ? effort : "medium";
}

/** Ретро-выбор (kimi/glm/zai/grok/zcode/auto) мигрирует на дефолт. */
export function resolveProvider(requested) {
  const value = String(requested || "");
  return SUPPORTED_PROVIDERS.has(value) ? value : DEFAULT_PROVIDER;
}

/** Shared by IPC and tests: keep the user's model through normalization. */
export function prepareProviderRequest(request, id) {
  const provider = resolveProvider(request?.provider);
  const envelope = createEnvelope({
    ...request,
    provider,
    model: provider === "codex" || provider === "claude"
      ? request?.model : openaiModel(provider, request?.model),
    reasoning: { effort: solEffort(request?.reasoning) },
    id: request?.id || id,
  });
  return { provider, envelope };
}

async function chatViaCodex({ codex, source, messages, model, profile, signal, effort, requestedProvider, fallback }) {
  if (source.responseFormat != null && (source.responseFormat.type !== "json_schema"
    || !source.responseFormat.jsonSchema?.schema)) {
    throw new Error("Codex structured output requires responseFormat.jsonSchema.schema with type json_schema");
  }
  const codexMessages = source.system
    ? [{ role: "system", content: source.system }, ...(source.messages || messages || [])]
    : source.messages || messages || [];
  let responseMetadata = null;
  const content = await codex.chat(codexMessages, {
    profile, signal, model, effort,
    ...(source.responseFormat ? { outputSchema: source.responseFormat.jsonSchema.schema } : {}),
    onResponseMetadata: (metadata) => { responseMetadata = metadata; },
    ...(source.timeoutMs != null ? { timeoutMs: source.timeoutMs } : {}),
  });
  return {
    content,
    toolCalls: [],
    provider: "codex",
    transport: { provider: "codex", model: responseMetadata?.model || null,
      modelProvider: responseMetadata?.modelProvider || null,
      authType: responseMetadata?.authType || null,
      threadId: responseMetadata?.threadId || null,
      turnId: responseMetadata?.turnId || null,
      modelSource: responseMetadata?.modelSource || null,
      completion: responseMetadata?.completion || null,
      // Файлы инструкций, которые app-server подхватил с диска пользователя
      // (глобальный ~/.codex/AGENTS.md отключить нельзя): для трассировки.
      instructionSources: responseMetadata?.instructionSources || null,
      contractVersion: responseMetadata?.contractVersion || codex.contract?.version || null,
      requestedProvider,
      requestId: source.id || null, dropped: [], fallback },
  };
}

export async function chatWithProvider({
  provider,
  messages,
  temperature,
  envelope: envelopeInput = null,
  signal = null,
  credentials,
  tools = null,
  profile = "generator",
  codex = null,
  claude = null,
  openaiChat = chatWithOpenAI,
  gptTransport = DEFAULT_GPT_TRANSPORT,
}) {
  const source = envelopeInput || { messages, temperature, tools, provider };
  const requestedProvider = String(source.provider || provider || DEFAULT_PROVIDER);
  const resolved = resolveProvider(requestedProvider);
  const fallback = resolved === requestedProvider ? null : resolved;
  const effort = solEffort(source.reasoning);
  const model = openaiModel(resolved, source.model);

  if (resolved === "codex") {
    if (!codex) throw new Error("Codex не подключён. Откройте Agents → Connections.");
    return chatViaCodex({ codex, source, messages, model: source.model, profile, signal, effort, requestedProvider: "codex", fallback });
  }

  if (resolved === "claude") {
    if (!claude) throw new Error("Claude не подключён. Откройте Agents → Connections.");
    const claudeResolvedModel = claudeModel(source.model);
    const claudeMessages = source.system
      ? [{ role: "system", content: source.system }, ...(source.messages || messages || [])]
      : source.messages || messages || [];
    let claudeMetadata = null;
    const content = await claude.chat(claudeMessages,
      { profile, effort, signal, model: claudeResolvedModel,
        // json_schema уходит в --json-schema, если установленный CLI его знает;
        // иначе адаптер сообщает dropped, а промпт по-прежнему просит JSON.
        ...(source.responseFormat ? { responseFormat: source.responseFormat } : {}),
        onResponseMetadata: (metadata) => { claudeMetadata = metadata; },
        ...(source.timeoutMs != null ? { timeoutMs: source.timeoutMs } : {}) });
    return {
      content,
      toolCalls: [],
      provider: "claude",
      transport: { provider: "claude", model: claudeResolvedModel, requestId: source.id || null,
        dropped: [...(claudeMetadata?.dropped || [])], fallback,
        contractVersion: claudeMetadata?.contractVersion || claude.contract?.version || null,
        structuredOutput: claudeMetadata?.structuredOutput ?? false },
    };
  }

  // GPT (Sol / Astra) по подписке: Codex CLI с явной моделью
  if (GPT_PROVIDERS.has(resolved) && gptTransport !== "openai") {
    if (!codex) {
      throw new Error("GPT работает по подписке через Codex CLI, а Codex не подключён. Откройте Agents → Connections и войдите в ChatGPT.");
    }
    return chatViaCodex({ codex, source, messages, model, profile, signal, effort, requestedProvider: resolved, fallback });
  }

  if (!credentials.has("openai")) {
    throw new Error("OpenAI не подключён. Добавьте API key в Agents → Connections.");
  }
  const envelope = createEnvelope({
    ...source,
    provider: "openai",
    model,
    reasoning: { effort },
  });
  const result = await openaiChat({ credentials, envelope, signal });
  return {
    ...result,
    provider: "openai",
    transport: {
      ...result.transport,
      provider: "openai",
      model,
      requestId: envelope.id,
      fallback,
    },
  };
}
