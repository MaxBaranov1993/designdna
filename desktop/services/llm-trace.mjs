import { appendFileSync, mkdirSync, renameSync, statSync } from "node:fs";
import path from "node:path";

/* Трасса вызовов моделей из Electron: одна JSON-строка на запрос в
 * <data>/traces/llm-calls.electron.jsonl. Только метаданные (провайдер, модель,
 * усилие, версия контракта, длительности, объёмы, ошибка), без текста промптов
 * и ответов. Python-путь пишет соседний файл llm-calls.python.jsonl; сервер и
 * MCP читают оба, чтобы агент мог ответить «какой промпт, модель и усилие дали
 * этот результат» после закрытия приложения. */

export const TRACE_FILE_NAME = "llm-calls.electron.jsonl";
export const MAX_TRACE_BYTES = 8 * 1024 * 1024;
const RETAINED_FIELDS = [
  "ts", "source", "requestId", "profile", "provider", "requestedProvider", "model", "effort",
  "contractVersion", "structuredOutput", "dropped", "durationMs", "queuedMs", "ok", "error",
  "cancelled", "promptChars", "outputChars", "threadId", "turnId", "instructionSources",
];

export function messageChars(messages, system = "") {
  let total = String(system || "").length;
  for (const message of messages || []) {
    const content = message?.content;
    if (typeof content === "string") total += content.length;
    else if (Array.isArray(content)) {
      for (const part of content) if (part?.type === "text") total += String(part.text || "").length;
    }
  }
  return total;
}

/** Компактная запись из конверта и результата провайдера. */
export function traceRecord({ envelope, profile, result, error, durationMs, queuedMs, cancelled = false }) {
  const transport = result?.transport || {};
  const record = {
    ts: new Date().toISOString(),
    source: "electron",
    requestId: envelope?.id || null,
    profile: profile || null,
    provider: result?.provider || transport.provider || envelope?.provider || null,
    requestedProvider: transport.requestedProvider || envelope?.provider || null,
    model: transport.model || envelope?.model || null,
    effort: envelope?.reasoning?.effort || null,
    contractVersion: transport.contractVersion || null,
    structuredOutput: transport.structuredOutput ?? null,
    dropped: Array.isArray(transport.dropped) ? transport.dropped.map((item) => item?.field).filter(Boolean) : [],
    durationMs: Math.max(0, Math.round(durationMs || 0)),
    queuedMs: Math.max(0, Math.round(queuedMs || 0)),
    ok: !error,
    error: error ? String(error.message || error).slice(0, 300) : null,
    cancelled: Boolean(cancelled),
    promptChars: messageChars(envelope?.messages, envelope?.system),
    outputChars: typeof result?.content === "string" ? result.content.length : 0,
    threadId: transport.threadId || null,
    turnId: transport.turnId || null,
    instructionSources: Array.isArray(transport.instructionSources) ? transport.instructionSources.length : null,
  };
  return Object.fromEntries(RETAINED_FIELDS.map((key) => [key, record[key]]));
}

export class LlmTrace {
  constructor({ directory, appendFile = appendFileSync, maxBytes = MAX_TRACE_BYTES, onError = null } = {}) {
    this.directory = directory;
    this.file = path.join(directory, TRACE_FILE_NAME);
    this.appendFile = appendFile;
    this.maxBytes = maxBytes;
    this.onError = onError;
    this.ready = false;
  }

  /** Запись никогда не ломает сам вызов модели: ошибки трассы только логируются. */
  write(record) {
    try {
      if (!this.ready) { mkdirSync(this.directory, { recursive: true }); this.ready = true; }
      this.#rotate();
      this.appendFile(this.file, `${JSON.stringify(record)}\n`, "utf8");
      return true;
    } catch (error) {
      this.onError?.(error);
      return false;
    }
  }

  #rotate() {
    let size = 0;
    try { size = statSync(this.file).size; } catch { return; }
    if (size < this.maxBytes) return;
    try { renameSync(this.file, `${this.file}.1`); } catch { /* keep appending to the current file */ }
  }
}
