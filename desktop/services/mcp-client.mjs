import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { randomUUID } from "node:crypto";

/* Structured MCP error: provider-neutral codes + correlation id so renderer and
 * logs can link a failure to a specific call without text matching. */
export class McpError extends Error {
  constructor(code, message, { requestId = null, serverId = null } = {}) {
    super(message);
    this.name = "McpError";
    this.code = code;
    this.requestId = requestId;
    this.serverId = serverId;
  }
  toJSON() {
    return { code: this.code, message: this.message, requestId: this.requestId, serverId: this.serverId };
  }
}

/** Strip secret-like substrings from server stderr before showing/logging. */
export function redactMcpStderr(text) {
  return String(text || "")
    .replace(/\b(sk|rk|xai|glmf|kimi)[-_][A-Za-z0-9_-]{8,}/g, (m) => `${m.slice(0, 6)}…[redacted]`)
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]{12,}/gi, "Bearer [redacted]")
    .replace(/\b[A-Za-z0-9+/]{40,}={0,2}\b/g, "[redacted]")
    .slice(-4_000);
}

const MAX_TIMEOUT_MS = 120_000;
const MAX_STDERR_BYTES = 8_000;
const SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25", "2024-11-05"];

function boundedTimeout(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1_000) return fallback;
  return Math.min(parsed, MAX_TIMEOUT_MS);
}

function isAbort(signal, error) {
  return signal?.aborted || error?.name === "AbortError";
}

export class McpStdioClient {
  constructor({ id, command, args = [], cwd, env = {}, timeoutMs = 30_000 }) {
    Object.assign(this, { id, command, args, cwd, env, timeoutMs });
    this.child = null;
    this.pending = new Map();
    this.sequence = 0;
    this.serverInfo = null;
    this.connectPromise = null;
    this.stderrBuffer = "";
    this.stderrBytes = 0;
  }

  async connect() {
    if (this.serverInfo) return this.serverInfo;
    if (this.connectPromise) return this.connectPromise;
    this.connectPromise = this.#doConnect();
    try {
      return await this.connectPromise;
    } finally {
      this.connectPromise = null;
    }
  }

  async #doConnect() {
    const child = spawn(this.command, this.args, {
      cwd: this.cwd,
      env: { ...process.env, ...this.env },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    this.stderrBuffer = "";
    this.stderrBytes = 0;
    createInterface({ input: child.stdout }).on("line", (line) => this.#onLine(line));
    child.stderr.on("data", (chunk) => this.#onStderr(chunk));
    // Async stdin failures (EPIPE after a server crash) arrive as stream
    // 'error' events — without a listener they crash the process; route them
    // through the same structured failure path as spawn/exit.
    child.stdin.on("error", (error) => this.#fail(new McpError("MCP_WRITE_FAILED", error.message, { serverId: this.id })));
    child.once("error", (error) => this.#fail(new McpError("MCP_SPAWN_FAILED", error.message, { serverId: this.id })));
    child.once("exit", (code) => this.#fail(new McpError("MCP_SERVER_EXITED", `MCP ${this.id} exited (${code}): ${redactMcpStderr(this.stderrBuffer)}`, { serverId: this.id })));
    const initialized = await this.request("initialize", {
      protocolVersion: SUPPORTED_PROTOCOL_VERSIONS[0],
      capabilities: {},
      clientInfo: { name: "designdna", version: "0.3.0" },
    }, { timeoutMs: 30_000 });
    const negotiated = initialized?.protocolVersion;
    if (!SUPPORTED_PROTOCOL_VERSIONS.includes(negotiated)) {
      this.stop();
      throw new McpError("MCP_PROTOCOL_MISMATCH", `MCP ${this.id} negotiated unsupported protocol ${negotiated}`, { serverId: this.id });
    }
    this.notify("notifications/initialized", {});
    this.serverInfo = initialized;
    return initialized;
  }

  #onStderr(chunk) {
    const text = chunk.toString("utf-8");
    this.stderrBytes += Buffer.byteLength(text, "utf8");
    this.stderrBuffer = (this.stderrBuffer + text).slice(-MAX_STDERR_BYTES);
  }

  async listTools(options = {}) {
    if (options.signal?.aborted) {
      throw new McpError("MCP_CANCELLED", `MCP ${this.id} call already aborted: tools/list`, { requestId: options.correlationId || null, serverId: this.id });
    }
    await this.connect();
    return this.request("tools/list", {}, options);
  }

  /** Call a tool. options: {timeoutMs, correlationId, signal} — correlationId
   * links the IPC call, approval dialog and structured error; signal aborts
   * the call and sends notifications/cancelled. */
  async callTool(name, arguments_, options = {}) {
    // Reject before connect(): an already-aborted call must not spawn the
    // server process or run the initialize handshake.
    if (options.signal?.aborted) {
      throw new McpError("MCP_CANCELLED", `MCP ${this.id} call already aborted: tools/call`, { requestId: options.correlationId || null, serverId: this.id });
    }
    await this.connect();
    return this.request("tools/call", { name, arguments: arguments_ || {} }, options);
  }

  request(method, params, { timeoutMs = null, correlationId = null, signal = null } = {}) {
    if (signal?.aborted) {
      return Promise.reject(new McpError("MCP_CANCELLED", `MCP ${this.id} call already aborted: ${method}`, { requestId: correlationId || null, serverId: this.id }));
    }
    if (!this.child) {
      return Promise.reject(new McpError("MCP_NOT_RUNNING", `MCP ${this.id} is not running`, { serverId: this.id }));
    }
    const id = ++this.sequence;
    const requestId = correlationId ? String(correlationId).slice(0, 128) : `${this.id}#${id}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup();
        this.pending.delete(id);
        this.#notifyCancelled(id, "timeout");
        reject(new McpError("MCP_TIMEOUT", `MCP ${this.id} timed out: ${method}`, { requestId, serverId: this.id }));
      }, boundedTimeout(timeoutMs, this.timeoutMs));
      const onAbort = () => {
        if (!this.pending.has(id)) return;
        cleanup();
        this.pending.delete(id);
        this.#notifyCancelled(id, "cancelled by client");
        reject(new McpError("MCP_CANCELLED", `MCP ${this.id} call cancelled: ${method}`, { requestId, serverId: this.id }));
      };
      const cleanup = signal
        ? () => { clearTimeout(timer); signal.removeEventListener("abort", onAbort); }
        : () => { clearTimeout(timer); };
      signal?.addEventListener("abort", onAbort, { once: true });
      this.pending.set(id, {
        resolve: (value) => { cleanup(); resolve(value); },
        reject: (error) => { cleanup(); reject(error); },
        timer,
        requestId,
        cleanup,
      });
      try {
        this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
      } catch (error) {
        cleanup();
        this.pending.delete(id);
        reject(new McpError("MCP_WRITE_FAILED", error.message, { requestId, serverId: this.id }));
      }
    });
  }

  /** Cancel pending calls by correlationId across all clients. Returns count. */
  cancelByCorrelation(correlationId) {
    let cancelled = 0;
    for (const [id, item] of this.pending) {
      if (item.requestId !== String(correlationId)) continue;
      this.pending.delete(id);
      item.cleanup();
      this.#notifyCancelled(id, "cancelled by client");
      item.reject(new McpError("MCP_CANCELLED", `MCP ${this.id} call cancelled`, { requestId: item.requestId, serverId: this.id }));
      cancelled += 1;
    }
    return cancelled;
  }

  #notifyCancelled(id, reason) {
    try {
      this.notify("notifications/cancelled", { requestId: id, reason });
    } catch {
      // dead stdin after server crash — already handled by exit handler
    }
  }

  notify(method, params) {
    if (!this.child) return;
    this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  }

  stop() {
    this.child?.kill();
    this.child = null;
    this.serverInfo = null;
    this.connectPromise = null;
    this.stderrBuffer = "";
    this.stderrBytes = 0;
  }

  #onLine(line) {
    let message;
    try { message = JSON.parse(line); } catch { return; }
    const item = this.pending.get(message.id);
    if (!item) return;
    this.pending.delete(message.id);
    item.cleanup();
    if (message.error) {
      item.reject(new McpError(message.error.code ?? "MCP_SERVER_ERROR", message.error.message || `MCP ${this.id} error`, { requestId: item.requestId, serverId: this.id }));
    } else {
      item.resolve(message.result);
    }
  }

  #fail(error) {
    for (const [, item] of this.pending) { item.cleanup(); item.reject(error); }
    this.pending.clear();
    this.child = null;
    this.serverInfo = null;
    this.connectPromise = null;
  }
}
