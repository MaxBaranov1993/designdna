import Ajv from "ajv/dist/2020.js";
import { createHash } from "node:crypto";
import { McpError, McpStdioClient } from "./mcp-client.mjs";
import { canonicalMcpSpec } from "./mcp-activation-approval.mjs";
const safeId = (value) => String(value).toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);

/* Provider-safe qualified tool names: `mcp_<server>__<tool>`, ≤ 128 bytes,
 * matching [A-Za-z0-9_-]. Raw ids that are already clean keep the historical
 * name byte-for-byte (backward compatible). Anything sanitized or overlong
 * gets a deterministic `~`-free `-<sha256(raw)[:10]>` suffix of the RAW ids,
 * so long or similarly-sanitized names never collide silently; the map keeps
 * the exact original (server, tool) target, and any residual duplicate fails
 * loudly at refresh instead of overwriting. safeId output is ASCII, so string
 * length equals UTF-8 bytes here. */
export const MCP_QUALIFIED_NAME_MAX_BYTES = 128;
const nameHash = (value) => createHash("sha256").update(value).digest("hex").slice(0, 10);

export function qualifiedToolName(serverId, toolName) {
  const rawServer = String(serverId);
  const rawTool = String(toolName);
  const cleanServer = safeId(rawServer);
  const cleanTool = safeId(rawTool);
  const base = `mcp_${cleanServer}__${cleanTool}`;
  const pristine = rawServer === cleanServer && rawTool === cleanTool
    && rawServer.length <= 48 && rawTool.length <= 48
    && base.length <= MCP_QUALIFIED_NAME_MAX_BYTES;
  if (pristine) return base;
  const suffix = `-${nameHash(`${rawServer} ${rawTool}`)}`;
  const budget = MCP_QUALIFIED_NAME_MAX_BYTES - suffix.length;
  const trimmed = base.length > budget ? base.slice(0, budget) : base;
  return `${trimmed}${suffix}`;
}

/* Full JSON Schema 2020-12 validation for MCP tool arguments.
 * Ajv is a standards-compliant validator; compilation failures are treated as
 * validation errors so a malformed server schema cannot crash the client. */
const ajv = new Ajv({ strict: false, allErrors: true });

export function validateToolArguments(schema, arguments_) {
  if (!Array.isArray(arguments_) && arguments_ !== undefined && arguments_ !== null && typeof arguments_ !== "object") {
    return [{ path: "$", message: "arguments must be an object" }];
  }
  let validate;
  try {
    validate = ajv.compile(schema || { type: "object" });
  } catch (error) {
    return [{ path: "$", message: `invalid tool inputSchema: ${error.message}` }];
  }
  const valid = validate(arguments_ || {});
  if (valid) return [];
  return (validate.errors || []).map((err) => ({
    path: err.instancePath ? `$${err.instancePath}` : "$",
    message: err.message || "validation failed",
  }));
}

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
      if (this.clients.has(server.id)) {
        // Дублирующийся id сервера — громкая ошибка конфига; процесс даже не
        // запускаем, чтобы не плодить осиротевшие child-процессы.
        statuses.push({ id: server.id, name: server.name, connected: false, error: `MCP name collision: duplicate server id "${server.id}"` });
        continue;
      }
      const env = {};
      for (const [variable, provider] of Object.entries(server.credentialEnv || {})) { const value = this.credentials.get(provider); if (value) env[variable] = value; }
      const client = new McpStdioClient({ id: server.id, command: server.command, args: server.args, cwd: this.cwd, env });
      try {
        const info = await client.connect(); const listed = await client.listTools();
        // Сначала собираем и проверяем ВСЕ имена — только потом регистрируем:
        // коллизия не оставляет ни частично записанных tools, ни живого child.
        const pending = [];
        for (const tool of listed.tools || []) {
          const qualifiedName = qualifiedToolName(server.id, tool.name);
          const rawKey = `${server.id} ${tool.name}`;
          const existing = this.tools.get(qualifiedName);
          if (existing) {
            // Ни одной молчаливой перезаписи: дубль — это громкая ошибка конфига.
            throw new McpError("MCP_NAME_COLLISION",
              `MCP tool name collision: "${qualifiedName}" for "${rawKey}" (already "${existing.rawKey}")`,
              { serverId: server.id });
          }
          pending.push({ server, client, tool, qualifiedName, rawKey });
        }
        this.clients.set(server.id, client);
        for (const entry of pending) this.tools.set(entry.qualifiedName, entry);
        statuses.push({ id: server.id, name: server.name, connected: true, serverInfo: info.serverInfo, tools: (listed.tools || []).length });
      } catch (error) { client.stop(); statuses.push({ id: server.id, name: server.name, connected: false, error: error.message }); }
    }
    return statuses;
  }
  async listTools() {
    if (!this.tools.size) await this.refresh();
    return [...this.tools.values()].map(({ server, tool, qualifiedName }) => ({ serverId: server.id, serverName: server.name, name: tool.name, qualifiedName, description: tool.description || "", inputSchema: tool.inputSchema || { type: "object" }, annotations: tool.annotations || {} }));
  }

  /** Вызов инструмента. Контракт:
   *  - аргументы валидируются по inputSchema ДО approval и до spawn-запроса;
   *  - approval-диалог несёт correlationId вызова (аудит согласований);
   *  - timeoutMs ограничен (≤120с), отмена через correlationId гасит вызов;
   *  - все отказы — структурные McpError {code, requestId, serverId}. */
  async callTool(qualifiedName, arguments_, { source = "user", timeoutMs = null, correlationId = null } = {}) {
    if (!this.tools.size) await this.refresh();
    const entry = this.tools.get(qualifiedName);
    if (!entry) throw new McpError("MCP_UNKNOWN_TOOL", `Unknown MCP tool: ${qualifiedName}`, { requestId: correlationId });
    const issues = validateToolArguments(entry.tool.inputSchema, arguments_ || {});
    if (issues.length) {
      throw new McpError("MCP_INVALID_ARGUMENTS", `Invalid arguments for ${entry.tool.name}: ${issues.map((i) => `${i.path}: ${i.message}`).join("; ")}`, { requestId: correlationId, serverId: entry.server.id });
    }
    if (entry.tool.annotations?.readOnlyHint !== true) {
      const accepted = await this.approve({ source, server: entry.server.name, tool: entry.tool.name, arguments: arguments_ || {}, correlationId });
      if (!accepted) throw new McpError("MCP_DECLINED", "MCP tool call declined", { requestId: correlationId, serverId: entry.server.id });
    }
    try {
      return await entry.client.callTool(entry.tool.name, arguments_ || {}, { timeoutMs, correlationId });
    } catch (error) {
      if (error instanceof McpError) throw error;
      throw new McpError("MCP_CALL_FAILED", error.message, { requestId: correlationId, serverId: entry.server.id });
    }
  }

  /** Отмена активных вызовов по correlationId во всех клиентах. */
  cancelByCorrelation(correlationId) {
    let cancelled = 0;
    for (const client of this.clients.values()) cancelled += client.cancelByCorrelation(correlationId);
    return cancelled;
  }

  dynamicTools() { return [...this.tools.values()].map(({ tool, qualifiedName }) => ({ name: qualifiedName, description: tool.description || `MCP tool ${tool.name}`, inputSchema: tool.inputSchema || { type: "object" } })); }
  stop() { for (const client of this.clients.values()) client.stop(); this.clients.clear(); this.tools.clear(); }
}
