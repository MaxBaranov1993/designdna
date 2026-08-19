import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";

function findWindowsCodexBinary(environment) {
  const target = process.arch === "arm64" ? "aarch64-pc-windows-msvc" : "x86_64-pc-windows-msvc";
  const packageName = process.arch === "arm64" ? "codex-win32-arm64" : "codex-win32-x64";
  for (const directory of String(environment.PATH || environment.Path || "").split(path.delimiter)) {
    if (!directory) continue;
    const packageRoots = [
      path.join(directory, "node_modules", "@openai", "codex"),
      path.resolve(directory, "..", "@openai", "codex"),
    ];
    for (const packageRoot of packageRoots) {
      for (const candidate of [
        path.join(packageRoot, "node_modules", "@openai", packageName, "vendor", target, "bin", "codex.exe"),
        path.join(packageRoot, "vendor", target, "bin", "codex.exe"),
      ]) {
        if (existsSync(candidate)) return candidate;
      }
    }
  }
  return null;
}

export function codexProcessSpec({
  platform = process.platform,
  environment = process.env,
} = {}) {
  const args = ["app-server", "--listen", "stdio://"];
  if (environment.DESIGNDNA_CODEX) return { command: environment.DESIGNDNA_CODEX, args };
  if (platform === "win32") {
    const nativeBinary = findWindowsCodexBinary(environment);
    if (nativeBinary) return { command: nativeBinary, args };
    return {
      command: environment.ComSpec || environment.COMSPEC || "cmd.exe",
      args: ["/d", "/s", "/c", "chcp 65001>nul && codex app-server --listen stdio://"],
    };
  }
  return { command: "codex", args };
}

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
    return this.request("account/login/start", {
      type: "chatgpt",
      useHostedLoginSuccessPage: true,
      appBrand: "chatgpt",
    });
  }
  async listThreads(params = {}) { await this.start(); return this.request("thread/list", { limit: 50, ...params }); }
  async startThread(params = {}) { await this.start(); return this.request("thread/start", params); }
  async resumeThread(threadId) { await this.start(); return this.request("thread/resume", { threadId }); }
  async startTurn(params) { await this.start(); return this.request("turn/start", params); }
  async steerTurn(params) { await this.start(); return this.request("turn/steer", params); }
  async interruptTurn(threadId, turnId) { await this.start(); return this.request("turn/interrupt", { threadId, turnId }); }
  async chat(messages, { timeoutMs = 180_000, profile = "generator" } = {}) {
    await this.start();
    const profileInstructions = {
      generator: "Generate the requested Design IR. The SYSTEM section below is the complete, authoritative design specification — follow it exactly, including the design craft rules and any locked Style DNA tokens: token colors (primary for CTAs and key accents, alternating background/surface sections) are mandatory, a plain white-and-grey wireframe is a failure.",
      quality_judge: "Evaluate the supplied Design IR exactly as requested.",
      quality_repair: "Repair the supplied Design IR exactly as requested.",
    };
    if (!Object.hasOwn(profileInstructions, profile)) throw new Error(`Unsupported Codex chat profile: ${profile}`);
    const prompt = [
      `${profileInstructions[profile]} Do not inspect files, run commands, or call tools. Return only the JSON object.`,
      ...messages.map((message) => `${String(message.role || "user").toUpperCase()}:\n${String(message.content || "")}`),
    ].join("\n\n");
    const started = await this.startThread({
      cwd: this.cwd,
      approvalPolicy: "never",
      sandbox: "read-only",
      serviceName: "designdna-generator",
    });
    const threadId = String(started.thread?.id || "");
    if (!threadId) throw new Error("Codex did not return a generator thread id");
    return new Promise((resolve, reject) => {
      let streamed = "";
      let completed = "";
      const timer = setTimeout(() => finish(new Error("Codex generator timed out")), timeoutMs);
      const finish = (error, value) => {
        clearTimeout(timer);
        this.removeListener("notification", onNotification);
        if (error) reject(error); else resolve(value);
      };
      const onNotification = ({ method, params = {} }) => {
        if (params.threadId && String(params.threadId) !== threadId) return;
        if (method === "item/agentMessage/delta") streamed += String(params.delta || "");
        if (method === "item/completed" && params.item?.type === "agentMessage") {
          completed = String(params.item.text || "");
        }
        if (method === "turn/completed") {
          const status = String(params.turn?.status || "completed");
          if (status !== "completed") {
            finish(new Error(params.turn?.error?.message || `Codex generator ${status}`));
            return;
          }
          const output = completed || streamed;
          finish(output.trim() ? null : new Error("Codex generator returned an empty response"), output);
        }
      };
      this.on("notification", onNotification);
      this.startTurn({ threadId, input: [{ type: "text", text: prompt }] }).catch((error) => finish(error));
    });
  }
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
    const spec = codexProcessSpec();
    const child = spawn(spec.command, spec.args, {
      cwd: this.cwd,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
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
