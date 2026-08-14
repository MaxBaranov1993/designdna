import fs from "node:fs";
import path from "node:path";

const ALLOWED_MCP_TRANSPORTS = new Set(["stdio", "http"]);

export class SettingsStore {
  constructor(userDataPath) {
    this.file = path.join(userDataPath, "settings.json");
  }

  read() {
    try {
      return JSON.parse(fs.readFileSync(this.file, "utf8"));
    } catch (error) {
      if (error.code === "ENOENT") return { mcpServers: [] };
      throw error;
    }
  }

  listMcpServers() {
    return this.read().mcpServers || [];
  }

  saveMcpServers(input) {
    if (!Array.isArray(input)) throw new Error("mcpServers must be an array");
    const mcpServers = input.map((server, index) => {
      const name = String(server?.name || "").trim();
      const transport = String(server?.transport || "");
      if (!name) throw new Error(`MCP server ${index + 1} needs a name`);
      if (!ALLOWED_MCP_TRANSPORTS.has(transport)) throw new Error(`Unsupported MCP transport: ${transport}`);
      if (transport === "stdio" && !String(server.command || "").trim()) throw new Error(`${name}: command is required`);
      if (transport === "http") {
        const url = new URL(String(server.url || ""));
        if (!new Set(["http:", "https:"]).has(url.protocol)) throw new Error(`${name}: invalid URL`);
      }
      return {
        name,
        transport,
        enabled: server.enabled !== false,
        ...(transport === "stdio"
          ? { command: String(server.command), args: Array.isArray(server.args) ? server.args.map(String) : [] }
          : { url: String(server.url) }),
      };
    });
    this.#write({ ...this.read(), mcpServers });
    return mcpServers;
  }

  #write(value) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temp = `${this.file}.${process.pid}.tmp`;
    fs.writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
    fs.renameSync(temp, this.file);
  }
}
