import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { createInterface } from "node:readline";

export class CodexAppServer extends EventEmitter {
  constructor({ cwd, timeoutMs = 30_000 } = {}) {
    super();
    this.cwd = cwd;
    this.timeoutMs = timeoutMs;
    this.child = null;
    this.pending = new Map();
    this.sequence = 0;
    this.initialized = null;
  }
  async start() {
    if (this.initialized) return this.initialized;
    this.initialized = this.#startAndInitialize();
    try { return await this.initialized; } catch (error) { this.initialized = null; throw error; }
  }
  async account() { await this.start(); return this.request("account/read", {}); }
  async login({ type, apiKey } = {}) {
    await this.start();
    if (type === "apiKey") {
      if (!apiKey) throw new Error("OpenAI API key is not configured");
      return this.request("account/login/start", { type: "apiKey", apiKey });
    }
    return this.request("account/login/start", { type: "chatgpt" });
  }
  async listThreads(params = {}) { await this.start(); return this.request("thread/list", { limit: 50, ...params }); }
  async startThread(params = {}) { await this.start(); return this.request("thread/start", params); }
  async resumeThread(threadId) { await this.start(); return this.request("thread/resume", { threadId }); }
  async startTurn(params) { await this.start(); return this.request("turn/start", params); }
  async steerTurn(params) { await this.start(); return this.request("turn/steer", params); }
  async interruptTurn(threadId, turnId) { await this.start(); return this.request("turn/interrupt", { threadId, turnId }); }
  request(method, params = {}) {
    if (!this.child) return Promise.reject(new Error("Codex app-server is not running"));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`Codex app-server timed out: ${method}`)); }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    });
  }
  respond(id, result, error) {
    if (!this.child || !new Set(["number", "string"]).has(typeof id)) throw new Error("Invalid Codex server request id");
    this.child.stdin.write(`${JSON.stringify(error ? { id, error } : { id, result })}\n`);
  }
  notify(method, params = {}) { this.child?.stdin.write(`${JSON.stringify({ method, params })}\n`); }
  stop() { this.child?.kill(); this.child = null; this.initialized = null; }
  async #startAndInitialize() {
    const child = spawn("codex", ["app-server", "--listen", "stdio://"], { cwd: this.cwd, env: process.env, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    this.child = child;
    createInterface({ input: child.stdout }).on("line", (line) => this.#onLine(line));
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-4_000); });
    child.once("error", (error) => this.#fail(error));
    child.once("exit", (code) => this.#fail(new Error(`Codex app-server exited (${code}): ${stderr.trim()}`)));
    const result = await this.request("initialize", {
      clientInfo: { name: "designdna", title: "DesignDNA", version: "0.3.0" },
      capabilities: { experimentalApi: true, mcpServerOpenaiFormElicitation: true },
    });
    this.notify("initialized", {});
    return result;
  }
  #onLine(line) {
    let message;
    try { message = JSON.parse(line); } catch { return; }
    if (message.id != null && message.method) { this.emit("request", { id: message.id, method: message.method, params: message.params || {} }); return; }
    if (message.id == null && message.method) { this.emit("notification", { method: message.method, params: message.params || {} }); return; }
    const item = this.pending.get(message.id);
    if (!item) return;
    clearTimeout(item.timer);
    this.pending.delete(message.id);
    if (message.error) item.reject(Object.assign(new Error(message.error.message || "Codex app-server error"), { code: message.error.code, data: message.error.data }));
    else item.resolve(message.result);
  }
  #fail(error) {
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(error); }
    this.pending.clear(); this.child = null; this.initialized = null; this.emit("serverError", error);
  }
}
