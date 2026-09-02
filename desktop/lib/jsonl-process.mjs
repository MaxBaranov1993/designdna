import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";

/**
 * JSONL-процесс с бинарными фреймами (протокол v2).
 *
 * Фрейм = header-строка JSON (UTF-8, `\\n`-терминированная); если в header
 * есть bodyLen > 0 — за ней следуют ровно bodyLen сырых байт. Тела запросов
 * и бинарные ответы идут этими байтами, а не base64-строкой внутри JSON:
 * на мегабайтных payload это убирает +33% инфляции и двойной JSON-эскейпинг.
 *
 * Чистые JSON-фреймы (без bodyLen) полностью совместимы с v1 — их используют
 * repo-canvas worker и health/configure-вызовы.
 *
 * События (для супервизора движка в main.mjs): `spawned` {spawnCount, pid},
 * `exited` {code, signal, expected, error}, `failed` {error} (spawn/pipe),
 * `aborted` {reason}, `pending` {count} — число запросов в полёте.
 * Имя `failed` вместо `error`: EventEmitter без слушателя `error` бросает.
 */
export class JsonlProcess extends EventEmitter {
  constructor({ command, args = [], cwd, env = {}, name = command, timeoutMs = 30_000, restartOnTimeout = false }) {
    super();
    this.command = command;
    this.args = args;
    this.cwd = cwd;
    this.env = env;
    this.name = name;
    this.timeoutMs = timeoutMs;
    // Таймаут на коротком интерактивном канале означает мёртвый транспорт
    // (десинк/битый pipe), а не медленный запрос: канал не оживает сам, и до
    // этого флага лечился только перезапуском всего приложения.
    this.restartOnTimeout = restartOnTimeout;
    this.child = null;
    this.pending = new Map();
    this.sequence = 0;
    this.stderr = [];
    this.spawnCount = 0;
    // stop() помечает штатное завершение: exit после него — не авария
    this.stopping = false;
    this.spawnedAt = 0;
    this.#resetReader();
  }

  get alive() { return Boolean(this.child); }

  get pid() { return this.child?.pid ?? null; }

  get pendingCount() { return this.pending.size; }

  #resetReader() {
    this.rxBuffer = Buffer.alloc(0);
    this.rxExpectBytes = 0;
    this.rxHeader = null;
  }

  start() {
    if (this.child) return;
    this.spawnCount += 1;
    this.stopping = false;
    this.spawnedAt = Date.now();
    this.#resetReader();
    const child = spawn(this.command, this.args, {
      cwd: this.cwd,
      env: { ...process.env, ...this.env },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    child.stdout.on("data", (chunk) => this.#onStdout(chunk));
    createLineReader(child.stderr, (line) => {
      this.stderr.push(line);
      if (this.stderr.length > 40) this.stderr.shift();
    });
    child.once("error", (error) => {
      this.#failAll(error);
      this.emit("failed", { error });
    });
    child.once("exit", (code, signal) => {
      const detail = this.stderr.slice(-5).join("\n");
      const error = new Error(`${this.name} exited (${code ?? signal ?? "unknown"})${detail ? `: ${detail}` : ""}`);
      const expected = this.stopping;
      this.#failAll(error);
      if (this.child === child) this.child = null;
      this.emit("exited", { code, signal, expected, error });
    });
    this.emit("spawned", { spawnCount: this.spawnCount, pid: child.pid ?? null });
  }

  /** Служебный фрейм без ожидания ответа (например, {type:"cancel", requestId}).
   *  false — процесс не запущен или канал уже закрыт. */
  sendControl(frame) {
    const child = this.child;
    if (!child || child.killed || !child.stdin || child.stdin.destroyed) return false;
    try {
      child.stdin.write(`${JSON.stringify(frame)}\n`);
      return true;
    } catch {
      return false;
    }
  }

  /** options.id — id фрейма, заданный вызывающим (чтобы адресовать cancel);
   *  по умолчанию `${pid}-${seq}`. */
  request(method, params = {}, timeoutMs = this.timeoutMs, options = {}) {
    this.start();
    const id = options?.id ? String(options.id) : `${process.pid}-${++this.sequence}`;
    // bodyBytes (Uint8Array) выносим из JSON в сырой кусок фрейма
    const frameParams = { ...params };
    let bodyBytes = null;
    if (frameParams.bodyBytes instanceof Uint8Array) {
      bodyBytes = Buffer.from(frameParams.bodyBytes);
      delete frameParams.bodyBytes;
    }
    const header = JSON.stringify(bodyBytes ? { id, method, params: { ...frameParams, bodyLen: bodyBytes.length } } : { id, method, params: frameParams });
    const frame = Buffer.concat([Buffer.from(header + "\n"), ...(bodyBytes ? [bodyBytes] : [])]);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#untrack(id);
        reject(new Error(`${this.name} request timed out: ${method}`));
        if (this.restartOnTimeout) this.abort(`${this.name}: канал перезапущен после таймаута ${method}`);
      }, timeoutMs);
      this.#track(id, { resolve, reject, timer });
      this.child.stdin.write(frame, (error) => {
        if (!error) return;
        clearTimeout(timer);
        this.#untrack(id);
        reject(error);
      });
    });
  }

  async stop() {
    const child = this.child;
    if (!child) return;
    this.stopping = true;
    try {
      await this.request("shutdown", {}, 1_500);
    } catch {
      child.kill();
    }
  }

  /** Немедленная отмена: процесс убивается, все ожидающие запросы отклоняются
   *  с reason. Следующий request() лениво поднимет свежий процесс. */
  abort(reason) {
    const child = this.child;
    this.#failAll(new Error(reason || "aborted"));
    if (child) {
      child.removeAllListeners("exit");
      child.kill();
      this.child = null;
    }
    this.emit("aborted", { reason: reason || "aborted", hadProcess: Boolean(child) });
  }

  #track(id, entry) {
    this.pending.set(id, entry);
    this.emit("pending", { count: this.pending.size });
  }

  #untrack(id) {
    if (!this.pending.delete(id)) return;
    this.emit("pending", { count: this.pending.size });
  }

  #onStdout(chunk) {
    this.rxBuffer = this.rxBuffer.length ? Buffer.concat([this.rxBuffer, chunk]) : chunk;
    while (true) {
      if (this.rxExpectBytes > 0) {
        if (this.rxBuffer.length < this.rxExpectBytes) return;
        const body = this.rxBuffer.subarray(0, this.rxExpectBytes);
        this.rxBuffer = this.rxBuffer.subarray(this.rxExpectBytes);
        this.rxExpectBytes = 0;
        this.#dispatch(this.rxHeader, body);
        this.rxHeader = null;
        continue;
      }
      const newline = this.rxBuffer.indexOf(0x0a);
      if (newline < 0) return;
      const line = this.rxBuffer.subarray(0, newline).toString("utf-8");
      this.rxBuffer = this.rxBuffer.subarray(newline + 1);
      if (!line.trim()) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        this.stderr.push(`invalid frame: ${line.slice(0, 300)}`);
        continue;
      }
      const result = message.result;
      const bodyLen = result && typeof result === "object" ? Number(result.bodyLen) : 0;
      if (Number.isInteger(bodyLen) && bodyLen > 0) {
        this.rxHeader = message;
        this.rxExpectBytes = bodyLen;
        continue;
      }
      this.#dispatch(message, null);
    }
  }

  #dispatch(message, body) {
    const pending = this.pending.get(String(message.id));
    if (!pending) return;
    clearTimeout(pending.timer);
    this.#untrack(String(message.id));
    if (message.error) {
      const error = new Error(message.error.message || `${this.name} request failed`);
      error.code = message.error.code;
      error.data = message.error.data;
      // кооперативная отмена воркера (cancel_token): не авария транспорта
      if (message.error.cancelled === true || message.cancelled === true) error.cancelled = true;
      pending.reject(error);
    } else if (body) {
      pending.resolve({ ...message.result, bodyBytes: body });
    } else {
      pending.resolve(message.result);
    }
  }

  #failAll(error) {
    const hadPending = this.pending.size > 0;
    for (const { reject, timer } of this.pending.values()) {
      clearTimeout(timer);
      reject(error);
    }
    this.pending.clear();
    if (hadPending) this.emit("pending", { count: 0 });
  }
}

function createLineReader(stream, onLine) {
  let buffer = Buffer.alloc(0);
  stream.on("data", (chunk) => {
    buffer = buffer.length ? Buffer.concat([buffer, chunk]) : chunk;
    while (true) {
      const newline = buffer.indexOf(0x0a);
      if (newline < 0) return;
      const line = buffer.subarray(0, newline).toString("utf-8");
      buffer = buffer.subarray(newline + 1);
      if (line.trim()) onLine(line);
    }
  });
}
