import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, rename, unlink, writeFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";

const MAX_LINE_BYTES = 512 * 1024;

function safeEqual(left, right) {
  const a = Buffer.from(String(left || ""), "utf8");
  const b = Buffer.from(String(right || ""), "utf8");
  return a.length === b.length && timingSafeEqual(a, b);
}

export function liveCommandEndpoint(dataDirectory, platform = process.platform) {
  const digest = createHash("sha256").update(path.resolve(dataDirectory), "utf8").digest("hex").slice(0, 20);
  return platform === "win32" ? `\\\\.\\pipe\\designdna-live-${digest}` : path.join(dataDirectory, "designdna-live.sock");
}

export class LiveCommandPipeServer {
  constructor({ dataDirectory, execute, endpoint = null } = {}) {
    if (typeof dataDirectory !== "string" || !dataDirectory) throw new TypeError("dataDirectory is required");
    if (typeof execute !== "function") throw new TypeError("execute must be a function");
    this.dataDirectory = path.resolve(dataDirectory);
    this.endpoint = endpoint || liveCommandEndpoint(this.dataDirectory);
    this.capabilityPath = path.join(this.dataDirectory, "live-command.json");
    this.execute = execute;
    this.token = randomBytes(32).toString("base64url");
    this.server = null;
  }

  async start() {
    if (this.server) return this.info();
    await mkdir(this.dataDirectory, { recursive: true });
    if (process.platform !== "win32") await unlink(this.endpoint).catch((error) => { if (error?.code !== "ENOENT") throw error; });
    const server = net.createServer((socket) => this.#connection(socket));
    await new Promise((resolve, reject) => {
      const onError = (error) => { server.off("listening", onListening); reject(error); };
      const onListening = () => { server.off("error", onError); resolve(); };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen(this.endpoint);
    });
    this.server = server;
    const document = JSON.stringify({ version: 1, endpoint: this.endpoint, token: this.token, pid: process.pid });
    const temporary = `${this.capabilityPath}.${process.pid}.tmp`;
    try {
      await writeFile(temporary, document, { encoding: "utf8", mode: 0o600, flag: "wx" });
      // A crash may leave an obsolete capability behind. The endpoint is
      // already exclusively bound, so replacing that stale document is safe.
      await unlink(this.capabilityPath).catch((error) => { if (error?.code !== "ENOENT") throw error; });
      await rename(temporary, this.capabilityPath);
      return this.info();
    } catch (error) {
      this.server = null;
      await new Promise((resolve) => server.close(() => resolve()));
      await unlink(temporary).catch((cleanupError) => { if (cleanupError?.code !== "ENOENT") throw cleanupError; });
      if (process.platform !== "win32") {
        await unlink(this.endpoint).catch((cleanupError) => { if (cleanupError?.code !== "ENOENT") throw cleanupError; });
      }
      throw error;
    }
  }

  info() {
    return { endpoint: this.endpoint, capabilityPath: this.capabilityPath, listening: Boolean(this.server) };
  }

  #connection(socket) {
    socket.setEncoding("utf8");
    let text = "";
    let finished = false;
    const respond = (payload) => {
      if (finished) return;
      finished = true;
      socket.end(`${JSON.stringify(payload)}\n`);
    };
    socket.on("data", (chunk) => {
      if (finished) return;
      text += chunk;
      if (Buffer.byteLength(text, "utf8") > MAX_LINE_BYTES) return respond({ ok: false, error: { code: "MESSAGE_TOO_LARGE", message: "Live command message is too large" } });
      const newline = text.indexOf("\n");
      if (newline < 0) return;
      const line = text.slice(0, newline);
      void (async () => {
        let message;
        try { message = JSON.parse(line); } catch { return respond({ ok: false, error: { code: "PARSE_ERROR", message: "Invalid JSON" } }); }
        if (!safeEqual(message?.token, this.token)) return respond({ ok: false, error: { code: "UNAUTHORIZED", message: "Invalid live command capability" } });
        try {
          const result = await this.execute(message.command);
          respond({ ok: true, requestId: message.requestId || null, result });
        } catch (error) {
          respond({ ok: false, requestId: message?.requestId || null, error: { code: String(error?.code || "LIVE_COMMAND_FAILED"), message: String(error?.message || error) } });
        }
      })();
    });
    socket.on("error", () => { finished = true; });
  }

  async stop() {
    const server = this.server;
    this.server = null;
    if (server) await new Promise((resolve) => server.close(() => resolve()));
    await unlink(this.capabilityPath).catch((error) => { if (error?.code !== "ENOENT") throw error; });
    if (process.platform !== "win32") await unlink(this.endpoint).catch((error) => { if (error?.code !== "ENOENT") throw error; });
  }
}
