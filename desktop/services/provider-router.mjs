import { chatWithKimi, chatWithOpenAI } from "./provider-chat.mjs";

async function autoProvider({ codex, credentials, exclude = new Set() }) {
  if (!exclude.has("codex")) {
    try {
      const status = await codex.account();
      if (status?.account) return "codex";
    } catch {
      // Codex is optional; fall through to explicitly connected API accounts.
    }
  }
  if (!exclude.has("kimi") && credentials.has("kimi")) return "kimi";
  if (!exclude.has("openai") && credentials.has("openai")) return "openai";
  throw new Error("Нет подключённого AI-аккаунта. Откройте Agents → Connections.");
}

async function resolveProvider({ provider, codex, credentials }) {
  if (provider === "auto") return autoProvider({ codex, credentials });
  if ((provider === "kimi" || provider === "openai") && !credentials.has(provider)) {
    // Saved graphs may point at an account that is no longer connected. Keep
    // generation working through another authenticated account instead of
    // surfacing an IPC/API-key error inside the node.
    return autoProvider({ codex, credentials, exclude: new Set([provider]) });
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
  kimiChat = chatWithKimi,
  openaiChat = chatWithOpenAI,
}) {
  const selected = await resolveProvider({ provider, codex, credentials });
  if (selected === "codex") {
    return {
      provider: selected,
      content: await codex.chat(messages, { timeoutMs: 180_000, profile: profile || "generator" }),
    };
  }
  if (selected === "kimi") {
    return { provider: selected, content: await kimiChat({ credentials, messages, temperature }) };
  }
  if (selected === "openai") {
    return { provider: selected, content: await openaiChat({ credentials, messages, temperature }) };
  }
  throw new Error(`Unsupported generator provider: ${selected}`);
}
