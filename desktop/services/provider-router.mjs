import { chatWithOpenAI } from "./provider-chat.mjs";
import { createEnvelope } from "./provider-envelope.mjs";


const SOL_MODEL = "gpt-5.6-sol";
const SOL_EFFORTS = new Set(["medium", "high", "max"]);
/* Провайдеры, выбираемые пользователем в нодах. openai (Sol по API-ключу)
 * остаётся дефолтом: сохранённые проекты и ретро-выборы мигрируют на него,
 * чтобы включение выбора не сломало уже работающую генерацию. */
export const SELECTABLE_PROVIDERS = Object.freeze(["openai", "codex", "claude"]);
const SUPPORTED_PROVIDERS = new Set(SELECTABLE_PROVIDERS);
const DEFAULT_PROVIDER = "openai";

function solEffort(value) {
  const effort = typeof value === "string" ? value : value?.effort;
  return SOL_EFFORTS.has(effort) ? effort : "medium";
}

/** Ретро-выбор (kimi/glm/zai/grok/zcode/auto) мигрирует на дефолт. */
export function resolveProvider(requested) {
  const value = String(requested || "");
  return SUPPORTED_PROVIDERS.has(value) ? value : DEFAULT_PROVIDER;
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
}) {
  const source = envelopeInput || { messages, temperature, tools, provider };
  const requestedProvider = String(source.provider || provider || DEFAULT_PROVIDER);
  const resolved = resolveProvider(requestedProvider);
  const fallback = resolved === requestedProvider ? null : resolved;
  const effort = solEffort(source.reasoning);

  if (resolved === "codex") {
    if (!codex) throw new Error("Codex не подключён. Откройте Agents → Connections.");
    // Codex — текстовый CLI-транспорт: image-части не доедут, а молча
    // превратить их в "[object Object]" значит сорвать разметку без причины.
    if ((source.messages || messages || []).some((item) => Array.isArray(item?.content)
      && item.content.some((part) => part?.type === "image_url"))) {
      throw new Error("Codex не передаёт изображения — для разметки скриншота выберите на ноде Claude или GPT.");
    }
    const content = await codex.chat(source.messages || messages || [], { profile });
    return {
      content,
      toolCalls: [],
      provider: "codex",
      transport: { provider: "codex", model: "codex", requestId: source.id || null, dropped: [], fallback },
    };
  }

  if (resolved === "claude") {
    if (!claude) throw new Error("Claude не подключён. Откройте Agents → Connections.");
    const content = await claude.chat(source.messages || messages || [], { profile, effort, signal });
    return {
      content,
      toolCalls: [],
      provider: "claude",
      transport: { provider: "claude", model: "opus", requestId: source.id || null, dropped: [], fallback },
    };
  }

  if (!credentials.has("openai")) {
    throw new Error("OpenAI не подключён. Добавьте API key в Agents → Connections.");
  }
  const envelope = createEnvelope({
    ...source,
    provider: "openai",
    model: SOL_MODEL,
    reasoning: { effort },
  });
  const result = await openaiChat({ credentials, envelope, signal });
  return {
    ...result,
    provider: "openai",
    transport: {
      ...result.transport,
      provider: "openai",
      model: SOL_MODEL,
      requestId: envelope.id,
      fallback,
    },
  };
}
