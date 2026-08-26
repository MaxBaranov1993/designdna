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

test("MCP manager validates arguments against the tool input schema before approval", async () => {
  let approvals = 0;
  const settings = { listMcpServers: () => [{
    id: "schema", name: "Schema", enabled: true, transport: "stdio",
    command: process.execPath,
    args: [path.join(directory, "fixtures", "mcp-schema-server.mjs")],
    credentialEnv: {},
  }] };
  const manager = new McpManager({
    settings, credentials: { get: () => null }, cwd: directory,
    approve: async () => { approvals += 1; return true; },
  });
  try {
    await manager.refresh();
    // невалидные аргументы: отсутствует required + неверный тип + вне enum
    await assert.rejects(
      manager.callTool("mcp_schema__save_note", { title: 42, severity: "weird" }, { correlationId: "corr-1" }),
      (error) => {
        assert.equal(error.code, "MCP_INVALID_ARGUMENTS");
        assert.match(error.message, /title/);
        assert.match(error.message, /body/);
        assert.match(error.message, /severity/);
        assert.equal(error.requestId, "corr-1");
        return true;
      },
    );
    // невалидный запрос НЕ долетает до approval-диалога
    assert.equal(approvals, 0);
    const result = await manager.callTool("mcp_schema__save_note",
      { title: "ok", body: "text", severity: "high" }, { correlationId: "corr-2" });
    assert.equal(approvals, 1);
    assert.equal(result.content[0].text, '{"title":"ok","body":"text","severity":"high"}');
  } finally { manager.stop(); }
});

test("MCP approval payload carries the call correlation id", async () => {
  let approvalPayload = null;
  const settings = { listMcpServers: () => [{
    id: "fixture", name: "Fixture", enabled: true, transport: "stdio",
    command: process.execPath,
    args: [path.join(directory, "fixtures", "mcp-server.mjs")],
    credentialEnv: {},
  }] };
  const manager = new McpManager({
    settings, credentials: { get: () => null }, cwd: directory,
    approve: async (payload) => { approvalPayload = payload; return true; },
  });
  try {
    await manager.refresh();
    await manager.callTool("mcp_fixture__echo", { v: 1 }, { correlationId: "corr-appr" });
    assert.equal(approvalPayload.correlationId, "corr-appr");
  } finally { manager.stop(); }
});

test("MCP manager cancels a pending call by correlation id", async () => {
  const settings = { listMcpServers: () => [{
    id: "slow", name: "Slow", enabled: true, transport: "stdio",
    command: process.execPath,
    args: [path.join(directory, "fixtures", "mcp-slow-server.mjs")],
    credentialEnv: {},
  }] };
  const manager = new McpManager({
    settings, credentials: { get: () => null }, cwd: directory,
    approve: async () => true,
  });
  try {
    await manager.refresh();
    const pending = manager.callTool("mcp_slow__slow_echo", { v: 1 }, { correlationId: "corr-cancel", timeoutMs: 60_000 });
    setTimeout(() => {
      const cancelled = manager.cancelByCorrelation("corr-cancel");
      assert.equal(cancelled, 1);
    }, 200);
    await assert.rejects(pending, (error) => error.code === "MCP_CANCELLED" && error.requestId === "corr-cancel");
  } finally { manager.stop(); }
});

test("MCP unknown tool is a structured error, not a crash", async () => {
  const settings = { listMcpServers: () => [] };
  const manager = new McpManager({
    settings, credentials: { get: () => null }, cwd: directory,
    approve: async () => true,
  });
  try {
    await manager.refresh();
    await assert.rejects(
      manager.callTool("mcp_missing__nope", {}),
      (error) => error.code === "MCP_UNKNOWN_TOOL",
    );
  } finally { manager.stop(); }
});

test("provider-safe qualified names: long/colliding ids get deterministic hash suffixes and route exactly", async () => {
  const { qualifiedToolName } = await import("../services/mcp-manager.mjs");
  // sanitation-colliding raw names → distinct deterministic names
  const a = qualifiedToolName("srv", "my-tool!");
  const b = qualifiedToolName("srv", "my-tool?");
  assert.notEqual(a, b);
  assert.equal(qualifiedToolName("srv", "my-tool!"), a); // deterministic
  // pristine ids keep the historical name byte-for-byte
  assert.equal(qualifiedToolName("fixture", "echo"), "mcp_fixture__echo");
  // все имена provider-safe и ≤ 128 байт
  const long = qualifiedToolName("srv", `tool_${"x".repeat(70)}`);
  for (const name of [a, b, long]) {
    assert.ok(/^[A-Za-z0-9_-]{1,128}$/.test(name), name);
    assert.ok(new TextEncoder().encode(name).length <= 128, name);
  }

  // discovery → provider tool definition → returned tool_call → exact MCP call
  const settings = { listMcpServers: () => [{
    id: `server-${"s".repeat(70)}`, name: "Names", enabled: true, transport: "stdio",
    command: process.execPath,
    args: [path.join(directory, "fixtures", "mcp-names-server.mjs")],
    credentialEnv: {},
  }] };
  const manager = new McpManager({
    settings, credentials: { get: () => null }, cwd: directory, approve: async () => true,
  });
  try {
    await manager.refresh();
    const tools = await manager.listTools();
    assert.equal(tools.length, 3);
    const names = tools.map((tool) => tool.qualifiedName);
    assert.equal(new Set(names).size, 3, "no silent collisions");
    // провайдер принимает все имена как tool definitions (envelope pattern)
    const { createEnvelope } = await import("../services/provider-envelope.mjs");
    const envelope = createEnvelope({
      provider: "openai",
      messages: [{ role: "user", content: "hi" }],
      tools: tools.map((tool) => ({ type: "function", function: { name: tool.qualifiedName, description: tool.description || "d", parameters: { type: "object" } } })),
    });
    assert.equal(envelope.tools.length, 3);
    // модель возвращает qualifiedName дословно → вызывается ТОЧНЫЙ исходный tool
    for (const tool of tools) {
      const result = await manager.callTool(tool.qualifiedName, { v: 1 });
      const called = JSON.parse(result.content[0].text);
      assert.equal(called.called, tool.name, `${tool.qualifiedName} must route to ${tool.name}`);
    }
    // коллидирующая пара указывает на РАЗНЫЕ исходные инструменты
    const calledNames = tools.map((tool) => tool.name);
    assert.ok(calledNames.includes("my-tool!") && calledNames.includes("my-tool?"));
  } finally { manager.stop(); }
});

test("a residual duplicate qualified name fails loudly instead of overwriting", async () => {
  const settings = { listMcpServers: () => [
    { id: "dup", name: "One", enabled: true, transport: "stdio", command: process.execPath, args: [path.join(directory, "fixtures", "mcp-server.mjs")], credentialEnv: {} },
    { id: "dup", name: "Two", enabled: true, transport: "stdio", command: process.execPath, args: [path.join(directory, "fixtures", "mcp-server.mjs")], credentialEnv: {} },
  ] };
  const manager = new McpManager({
    settings, credentials: { get: () => null }, cwd: directory, approve: async () => true,
  });
  try {
    const statuses = await manager.refresh();
    assert.equal(statuses[1].connected, false);
    assert.match(statuses[1].error, /collision/i);
  } finally { manager.stop(); }
});
