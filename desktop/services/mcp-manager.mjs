import { McpStdioClient } from "./mcp-client.mjs";
import { canonicalMcpSpec } from "./mcp-activation-approval.mjs";
const safeId = (value) => String(value).toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);

export class McpManager {
  constructor({ settings, credentials, cwd, approve, approveActivation }) {
    Object.assign(this, { settings, credentials, cwd, approve, approveActivation });
    this.clients = new Map(); this.tools = new Map();
    this.refreshQueue = Promise.resolve();
  }
  async refresh() {
    const pending = this.refreshQueue.then(() => this.refreshNow(), () => this.refreshNow());
    this.refreshQueue = pending.catch(() => undefined);
    return pending;
  }
  async refreshNow() {
    this.stop(); const statuses = [];
    const servers = this.settings.listMcpServers();
    // Единая точка активации исполняемого MCP-конфига (mcp:save, mcp:refresh,
    // ленивый refresh из listTools/callTool, codex:start-thread): прежде чем
    // запустить хоть один процесс, канонический спек конфига должен быть
    // подтверждён нативным диалогом в main-процессе.
    if (this.approveActivation) {
      const accepted = await this.approveActivation(canonicalMcpSpec(servers));
      if (!accepted) {
        return servers.filter((item) => item.enabled).map((server) => ({
          id: server.id, name: server.name, connected: false, error: "MCP activation declined by user",
        }));
      }
    }
    for (const server of servers.filter((item) => item.enabled)) {
      if (server.transport !== "stdio") { statuses.push({ id: server.id, name: server.name, connected: false, error: "Only stdio MCP is enabled in desktop v0.3" }); continue; }
      try {
        const env = {};
        for (const [variable, provider] of Object.entries(server.credentialEnv || {})) { const value = this.credentials.get(provider); if (value) env[variable] = value; }
        const client = new McpStdioClient({ id: server.id, command: server.command, args: server.args, cwd: this.cwd, env });
        const info = await client.connect(); const listed = await client.listTools();
        this.clients.set(server.id, client);
        for (const tool of listed.tools || []) { const qualifiedName = `mcp_${safeId(server.id)}__${safeId(tool.name)}`; this.tools.set(qualifiedName, { server, client, tool, qualifiedName }); }
        statuses.push({ id: server.id, name: server.name, connected: true, serverInfo: info.serverInfo, tools: (listed.tools || []).length });
      } catch (error) { statuses.push({ id: server.id, name: server.name, connected: false, error: error.message }); }
    }
    return statuses;
  }
  async listTools() {
    if (!this.tools.size) await this.refresh();
    return [...this.tools.values()].map(({ server, tool, qualifiedName }) => ({ serverId: server.id, serverName: server.name, name: tool.name, qualifiedName, description: tool.description || "", inputSchema: tool.inputSchema || { type: "object" }, annotations: tool.annotations || {} }));
  }
  async callTool(qualifiedName, arguments_, { source = "user" } = {}) {
    if (!this.tools.size) await this.refresh();
    const entry = this.tools.get(qualifiedName); if (!entry) throw new Error(`Unknown MCP tool: ${qualifiedName}`);
    if (entry.tool.annotations?.readOnlyHint !== true) {
      const accepted = await this.approve({ source, server: entry.server.name, tool: entry.tool.name, arguments: arguments_ || {} });
      if (!accepted) throw Object.assign(new Error("MCP tool call declined"), { code: "MCP_DECLINED" });
    }
    return entry.client.callTool(entry.tool.name, arguments_ || {});
  }
  dynamicTools() { return [...this.tools.values()].map(({ tool, qualifiedName }) => ({ name: qualifiedName, description: tool.description || `MCP tool ${tool.name}`, inputSchema: tool.inputSchema || { type: "object" } })); }
  stop() { for (const client of this.clients.values()) client.stop(); this.clients.clear(); this.tools.clear(); }
}
