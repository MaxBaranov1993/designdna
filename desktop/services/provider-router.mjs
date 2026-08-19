import { chatWithKimi, chatWithOpenAI } from "./provider-chat.mjs";

async function autoProvider({ codex, credentials }) {
  try {
    const status = await codex.account();
    if (status?.account) return "codex";
  } catch {
    // Codex is optional; fall through to explicitly connected API accounts.
  }
  if (credentials.has("kimi")) return "kimi";
  if (credentials.has("openai")) return "openai";
  throw new Error("Нет подключённого AI-аккаунта. Откройте Agents → Connections.");
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
  const selected = provider === "auto" ? await autoProvider({ codex, credentials }) : provider;
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
