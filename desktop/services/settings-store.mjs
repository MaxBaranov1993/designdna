import fs from "node:fs";
import path from "node:path";

const ALLOWED_MCP_TRANSPORTS = new Set(["stdio"]);
// Credential references mirror the CredentialStore provider set: an MCP stdio
// server may reference any storable provider credential (by name only — the
// secret itself never enters settings.json).
const ALLOWED_CREDENTIALS = new Set(["openai", "kimi", "glm", "zai", "grok"]);
const serverId = (value) => String(value).toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);

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

  validateMcpServers(input) {
    if (!Array.isArray(input)) throw new Error("mcpServers must be an array");
    return input.map((server, index) => {
      const name = String(server?.name || "").trim();
      const transport = String(server?.transport || "");
      if (!name) throw new Error(`MCP server ${index + 1} needs a name`);
      if (!ALLOWED_MCP_TRANSPORTS.has(transport)) throw new Error(`Unsupported MCP transport: ${transport}`);
      if (transport === "stdio" && !String(server.command || "").trim()) throw new Error(`${name}: command is required`);
      const id = serverId(server?.id || name);
      if (!id) throw new Error(`${name}: invalid id`);
      const credentialEnv = Object.fromEntries(Object.entries(server?.credentialEnv || {}).map(([variable, provider]) => {
        if (!/^[A-Z_][A-Z0-9_]*$/.test(variable)) throw new Error(`${name}: invalid environment variable ${variable}`);
        if (!ALLOWED_CREDENTIALS.has(String(provider))) throw new Error(`${name}: unsupported credential reference ${provider}`);
        return [variable, String(provider)];
      }));
      return {
        id,
        name,
        transport,
        enabled: server.enabled !== false,
        command: String(server.command),
        args: Array.isArray(server.args) ? server.args.map(String) : [],
        credentialEnv,
      };
    });
  }

  saveMcpServers(input) {
    const mcpServers = this.validateMcpServers(input);
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
