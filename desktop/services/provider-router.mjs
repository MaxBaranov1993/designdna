import { chatWithGlm, chatWithGrok, chatWithKimi, chatWithOpenAI, chatWithZai, chatWithZcode, zcodeEnsureConfig } from "./provider-chat.mjs";
import { adaptEnvelopeForProvider, assertEnvelopeSupported, createEnvelope } from "./provider-envelope.mjs";

const PROVIDER_ORDER = ["kimi", "zai", "glm", "openai", "grok"];
const CODEX_DEFAULT_TIMEOUT_MS = 180_000;
const CODEX_GENERATOR_TIMEOUT_MS = 300_000;

async function autoProvider({ codex, credentials, exclude = new Set(), zcodeAvailable = zcodeEnsureConfig }) {
  if (!exclude.has("codex")) {
    try {
      const status = await codex.account();
      if (status?.account) return "codex";
    } catch {
      // Codex is optional; fall through to explicitly connected API accounts.
    }
  }
  for (const provider of PROVIDER_ORDER) {
    if (!exclude.has(provider) && credentials.has(provider)) return provider;
  }
  // Локальный ZCode CLI — только явный opt-in через ZCODE_CLI (см.
  // provider-chat.zcodeCliPath); автоматического discovery нет.
  if (!exclude.has("zcode") && zcodeAvailable()) return "zcode";
  throw new Error("Нет подключённого AI-аккаунта. Откройте Agents → Connections или включите ZCode через ZCODE_CLI.");
}

async function resolveProvider({ provider, codex, credentials, zcodeAvailable = zcodeEnsureConfig }) {
  if (provider === "auto") {
    const selected = await autoProvider({ codex, credentials, zcodeAvailable });
    return { provider: selected, fallback: selected };
  }
  if (provider === "codex") {
    let status;
    try { status = await codex.account(); } catch (error) {
      throw new Error(`Codex account unavailable: ${error.message}`);
    }
    if (!status?.account) throw new Error("Codex не подключён. Войдите через Agents → Connections.");
    return { provider, fallback: null };
  }
  if (provider === "zcode") {
    if (!zcodeAvailable()) throw new Error("ZCode CLI не найден или не включён: автоматический поиск установленного приложения удалён — задайте ZCODE_CLI с полным путём к zcode.cjs и выполните login Z.AI");
    return { provider, fallback: null };
  }
  if (PROVIDER_ORDER.includes(provider)) {
    if (!credentials.has(provider)) {
      throw new Error(`Провайдер ${provider} не подключён. Добавьте ключ в Agents → Connections.`);
    }
    return { provider, fallback: null };
  }
  throw new Error(`Unsupported generator provider: ${provider}`);
}

/** Envelope → codex chat messages (текстовые; мультимодальные части — текст). */
function codexMessages(envelope) {
  const messages = [];
  if (envelope.system) messages.push({ role: "system", content: envelope.system });
  for (const message of envelope.messages) {
    const text = (message.content || [])
      .map((part) => (part.type === "text" ? part.text : part.type === "image_url" ? "[image attached]" : ""))
      .filter(Boolean)
      .join("\n");
    if (text.trim()) messages.push({ role: message.role, content: text });
  }
  return messages;
}

export async function chatWithProvider({
  provider,
  messages,
  temperature,
  profile,
  envelope: envelopeInput = null,
  signal = null,
  codex,
  credentials,
  tools = null,
  kimiChat = chatWithKimi,
  openaiChat = chatWithOpenAI,
  glmChat = chatWithGlm,
  zaiChat = chatWithZai,
  grokChat = chatWithGrok,
  zcodeChat = chatWithZcode,
  zcodeAvailable = zcodeEnsureConfig,
}) {
  // Одна точка валидации: и явный envelope, и legacy-поля проходят через
  // типизированный конверт — параметры далее не теряются молча.
  const envelope = envelopeInput || createEnvelope({
    id: `chat-${Date.now().toString(36)}`,
    provider,
    messages,
    temperature,
    tools,
  });
  const { provider: selected, fallback } = await resolveProvider({ provider: envelope.provider, codex, credentials, zcodeAvailable });

  const withTransport = (result) => ({
    ...result,
    provider: selected,
    transport: { ...result.transport, requestId: envelope.id, fallback },
  });

  if (selected === "codex") {
    assertEnvelopeSupported(envelope, "codex");
    const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "codex");
    const content = await codex.chat(codexMessages(adapted), {
      timeoutMs: adapted.timeoutMs || (profile === "generator" ? CODEX_GENERATOR_TIMEOUT_MS : CODEX_DEFAULT_TIMEOUT_MS),
      profile: profile || "generator",
    });
    return withTransport({ content, toolCalls: null, transport: { provider: "codex", model: null, dropped } });
  }
  if (selected === "zcode") {
    return withTransport(await zcodeChat({ envelope, signal }));
  }
  if (selected === "kimi") {
    return withTransport(await kimiChat({ credentials, envelope, signal }));
  }
  if (selected === "openai") {
    return withTransport(await openaiChat({ credentials, envelope, signal }));
  }
  if (selected === "glm") {
    return withTransport(await glmChat({ credentials, envelope, signal }));
  }
  if (selected === "zai") {
    return withTransport(await zaiChat({ credentials, envelope, signal }));
  }
  if (selected === "grok") {
    return withTransport(await grokChat({ credentials, envelope, signal }));
  }
  throw new Error(`Unsupported generator provider: ${selected}`);
}
