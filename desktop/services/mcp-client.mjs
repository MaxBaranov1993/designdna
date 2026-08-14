import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

export class McpStdioClient {
  constructor({ id, command, args = [], cwd, env = {}, timeoutMs = 30_000 }) {
    Object.assign(this, { id, command, args, cwd, env, timeoutMs });
    this.child = null; this.pending = new Map(); this.sequence = 0; this.serverInfo = null;
  }
  async connect() {
    if (this.serverInfo) return this.serverInfo;
    const child = spawn(this.command, this.args, { cwd: this.cwd, env: { ...process.env, ...this.env }, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    this.child = child;
    createInterface({ input: child.stdout }).on("line", (line) => this.#onLine(line));
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-4_000); });
    child.once("error", (error) => this.#fail(error));
    child.once("exit", (code) => this.#fail(new Error(`MCP ${this.id} exited (${code}): ${stderr.trim()}`)));
    const initialized = await this.request("initialize", { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "designdna", version: "0.3.0" } });
    this.notify("notifications/initialized", {});
    this.serverInfo = initialized;
    return initialized;
  }
  async listTools() { await this.connect(); return this.request("tools/list", {}); }
  async callTool(name, arguments_) { await this.connect(); return this.request("tools/call", { name, arguments: arguments_ || {} }); }
  request(method, params) {
    if (!this.child) return Promise.reject(new Error(`MCP ${this.id} is not running`));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`MCP ${this.id} timed out: ${method}`)); }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }
  notify(method, params) { this.child?.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`); }
  stop() { this.child?.kill(); this.child = null; this.serverInfo = null; }
  #onLine(line) {
    let message; try { message = JSON.parse(line); } catch { return; }
    const item = this.pending.get(message.id); if (!item) return;
    clearTimeout(item.timer); this.pending.delete(message.id);
    if (message.error) item.reject(Object.assign(new Error(message.error.message || `MCP ${this.id} error`), { code: message.error.code })); else item.resolve(message.result);
  }
  #fail(error) {
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(error); }
    this.pending.clear(); this.child = null; this.serverInfo = null;
  }
}
