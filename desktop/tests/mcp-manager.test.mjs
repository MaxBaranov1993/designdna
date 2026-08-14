import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { McpManager } from "../services/mcp-manager.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));

test("MCP manager discovers tools and gates mutating calls", async () => {
  let approvals = 0;
  const settings = { listMcpServers: () => [{ id: "fixture", name: "Fixture", enabled: true, transport: "stdio", command: process.execPath, args: [path.join(directory, "fixtures", "mcp-server.mjs")], credentialEnv: {} }] };
  const manager = new McpManager({ settings, credentials: { get: () => null }, cwd: directory, approve: async () => { approvals += 1; return true; } });
  try {
    const statuses = await manager.refresh();
    assert.equal(statuses[0].connected, true);
    const tools = await manager.listTools();
    assert.equal(tools[0].qualifiedName, "mcp_fixture__echo");
    const result = await manager.callTool(tools[0].qualifiedName, { value: 42 });
    assert.equal(approvals, 1);
    assert.equal(result.content[0].text, '{"value":42}');
  } finally { manager.stop(); }
});
