/* Общие правила герметичного запуска подписочных CLI (Claude Code и Codex).
 *
 * Продукт ставят другие пользователи, и оба CLI на их машинах читают СВОИ
 * инструкции: ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md, settings.json с хуками,
 * config.toml с моделью и MCP-серверами. Продуктовые вызовы должны быть
 * изолированы от этого: инструкции DesignDNA уходят явными каналами
 * (system prompt / developerInstructions), cwd — пустой каталог приложения,
 * инструменты выключены. Здесь — то, что нужно обоим адаптерам. */

/** Текст сообщения конверта: строка или text-части массива. */
export function messageText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content == null ? "" : String(content);
  return content
    .filter((part) => part?.type === "text")
    .map((part) => String(part?.text ?? ""))
    .join("\n");
}

/** system-сообщения уходят в системный канал провайдера, остальные — в ввод.
 *  Картинки в system недопустимы: их некуда положить в системном промпте. */
export function splitSystemMessages(messages) {
  const systemTexts = [];
  const rest = [];
  for (const message of messages || []) {
    if (String(message?.role || "") !== "system") {
      rest.push(message);
      continue;
    }
    if (Array.isArray(message.content) && message.content.some((part) => part?.type === "image_url")) {
      throw new Error("System messages cannot carry images");
    }
    const text = messageText(message.content);
    if (text.trim()) systemTexts.push(text);
  }
  return { systemTexts, rest };
}

/** Переопределения конфига Codex для внутренних (не пользовательских) тредов:
 *  без AGENTS.md пользователя и без запуска его MCP-серверов. Проверено на
 *  app-server 0.153.2: thread/start принимает оба ключа. */
export const HERMETIC_CODEX_CONFIG = Object.freeze({ project_doc_max_bytes: 0, mcp_servers: {} });
