import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

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
  }

  start() {
    if (this.child) return;
    const child = spawn(this.command, this.args, {
      cwd: this.cwd,
      env: { ...process.env, ...this.env },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    createInterface({ input: child.stdout }).on("line", (line) => this.#handleLine(line));
    createInterface({ input: child.stderr }).on("line", (line) => {
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
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${this.name} request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ id, method, params })}\n`, (error) => {
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

  #handleLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.stderr.push(`invalid JSONL: ${line.slice(0, 300)}`);
      return;
    }
    const pending = this.pending.get(String(message.id));
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(String(message.id));
    if (message.error) {
      const error = new Error(message.error.message || `${this.name} request failed`);
      error.code = message.error.code;
      error.data = message.error.data;
      pending.reject(error);
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
