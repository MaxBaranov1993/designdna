import { spawn } from "node:child_process";

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
 */
export class JsonlProcess {
  constructor({ command, args = [], cwd, env = {}, name = command, timeoutMs = 30_000 }) {
    this.command = command;
    this.args = args;
    this.cwd = cwd;
    this.env = env;
    this.name = name;
    this.timeoutMs = timeoutMs;
    this.child = null;
    this.pending = new Map();
    this.sequence = 0;
    this.stderr = [];
    this.spawnCount = 0;
    this.#resetReader();
  }

  #resetReader() {
    this.rxBuffer = Buffer.alloc(0);
    this.rxExpectBytes = 0;
    this.rxHeader = null;
  }

  start() {
    if (this.child) return;
    this.spawnCount += 1;
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
    child.once("error", (error) => this.#failAll(error));
    child.once("exit", (code, signal) => {
      const detail = this.stderr.slice(-5).join("\n");
      this.#failAll(new Error(`${this.name} exited (${code ?? signal ?? "unknown"})${detail ? `: ${detail}` : ""}`));
      this.child = null;
    });
  }

  request(method, params = {}, timeoutMs = this.timeoutMs) {
    this.start();
    const id = `${process.pid}-${++this.sequence}`;
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
        this.pending.delete(id);
        reject(new Error(`${this.name} request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(frame, (error) => {
        if (!error) return;
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  async stop() {
    const child = this.child;
    if (!child) return;
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
    this.pending.delete(String(message.id));
    if (message.error) {
      const error = new Error(message.error.message || `${this.name} request failed`);
      error.code = message.error.code;
      error.data = message.error.data;
      pending.reject(error);
    } else if (body) {
      pending.resolve({ ...message.result, bodyBytes: body });
    } else {
      pending.resolve(message.result);
    }
  }

  #failAll(error) {
    for (const { reject, timer } of this.pending.values()) {
      clearTimeout(timer);
      reject(error);
    }
    this.pending.clear();
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
