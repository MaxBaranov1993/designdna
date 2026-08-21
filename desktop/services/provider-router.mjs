import { chatWithGlm, chatWithKimi, chatWithOpenAI, chatWithZcode, zcodeEnsureConfig } from "./provider-chat.mjs";

async function autoProvider({ codex, credentials, exclude = new Set(), zcodeAvailable = zcodeEnsureConfig }) {
  if (!exclude.has("codex")) {
    try {
      const status = await codex.account();
      if (status?.account) return "codex";
    } catch {
      // Codex is optional; fall through to explicitly connected API accounts.
    }
  }
  if (!exclude.has("kimi") && credentials.has("kimi")) return "kimi";
  if (!exclude.has("glm") && credentials.has("glm")) return "glm";
  if (!exclude.has("openai") && credentials.has("openai")) return "openai";
  // Локальный ZCode CLI не требует ключей: login Z.AI уже работает как аккаунт.
  if (!exclude.has("zcode") && zcodeAvailable()) return "zcode";
  throw new Error("Нет подключённого AI-аккаунта. Откройте Agents → Connections или войдите в ZCode.");
}

async function resolveProvider({ provider, codex, credentials, zcodeAvailable = zcodeEnsureConfig }) {
  if (provider === "auto") return autoProvider({ codex, credentials, zcodeAvailable });
  if (provider === "zcode") {
    if (!zcodeAvailable()) throw new Error("ZCode CLI не найден или не авторизован: войдите в приложение ZCode");
    return provider;
  }
  if ((provider === "kimi" || provider === "openai" || provider === "glm") && !credentials.has(provider)) {
    // Saved graphs may point at an account that is no longer connected. Keep
    // generation working through another authenticated account instead of
    // surfacing an IPC/API-key error inside the node.
    return autoProvider({ codex, credentials, exclude: new Set([provider]), zcodeAvailable });
  }
  return provider;
}

export async function chatWithProvider({
  provider,
  messages,
  temperature,
  profile,
  codex,
  credentials,
  tools = null,
  kimiChat = chatWithKimi,
  openaiChat = chatWithOpenAI,
  glmChat = chatWithGlm,
  zcodeChat = chatWithZcode,
  zcodeAvailable = zcodeEnsureConfig,
}) {
  const selected = await resolveProvider({ provider, codex, credentials, zcodeAvailable });
  if (selected === "codex") {
    return {
      provider: selected,
      content: await codex.chat(messages, { timeoutMs: 180_000, profile: profile || "generator" }),
    };
  }
  if (selected === "zcode") {
    // Локальный ZCode CLI: temperature/response_format не управляются —
    // отдаём финальный текст агента как content.
    return { provider: selected, content: await zcodeChat({ messages }) };
  }
  if (selected === "kimi") {
    return { provider: selected, content: await kimiChat({ credentials, messages, temperature }) };
  }
  if (selected === "openai") {
    return { provider: selected, content: await openaiChat({ credentials, messages, temperature }) };
  }
  if (selected === "glm") {
    // tool-calling режим прокидываем только явному glm-вызову (Agent Workspace);
    // нодам нужен чистый текст/JSON — там tools не передаётся
    const result = await glmChat({ credentials, messages, temperature, tools, returnToolCalls: !!tools });
    return result.toolCalls
      ? { provider: selected, content: result.content, toolCalls: result.toolCalls }
      : { provider: selected, content: typeof result === "string" ? result : result.content };
  }
  throw new Error(`Unsupported generator provider: ${selected}`);
}
