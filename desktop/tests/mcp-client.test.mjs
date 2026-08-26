import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { McpError, McpStdioClient, redactMcpStderr } from "../services/mcp-client.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const serverFixture = path.join(directory, "fixtures", "mcp-server.mjs");

function client(overrides = {}) {
  return new McpStdioClient({
    id: "fixture",
    command: process.execPath,
    args: [serverFixture],
    cwd: directory,
    ...overrides,
  });
}

test("initialize/listTools/callTool round-trip against the fixture server", async () => {
  const mcp = client();
  try {
    const info = await mcp.connect();
    assert.equal(info.serverInfo.name, "fixture");
    const listed = await mcp.listTools();
    assert.equal(listed.tools[0].name, "echo");
    const result = await mcp.callTool("echo", { value: 7 }, { correlationId: "corr-7" });
    assert.equal(result.content[0].text, '{"value":7}');
  } finally { mcp.stop(); }
});

test("server errors reject with structured McpError (code + requestId + serverId)", async () => {
  const mcp = client();
  try {
    await mcp.connect();
    // fixture отвечает мгновенно — таймаут не наступит; проверяем bounded
    // поведение на заведомо маленьком таймауте против медленного скриппа нет,
    // поэтому проверяем структуру через прямой reject-путь: несуществующий
    // метод даёт серверную ошибку с кодом из JSON-RPC.
    await assert.rejects(
      mcp.request("unknown/method", {}, { correlationId: "corr-x" }),
      (error) => {
        assert.ok(error instanceof McpError);
        assert.equal(error.code, -32601);
        assert.equal(error.requestId, "corr-x");
        assert.equal(error.serverId, "fixture");
        assert.deepEqual(error.toJSON(), {
          code: -32601, message: error.message, requestId: "corr-x", serverId: "fixture",
        });
        return true;
      },
    );
  } finally { mcp.stop(); }
});

test("per-call timeout override fires with MCP_TIMEOUT", async () => {
  // Специальный «медленный» сервер: отвечает на tools/call только после 10с.
  const slowFixture = path.join(directory, "fixtures", "mcp-slow-server.mjs");
  const mcp = new McpStdioClient({
    id: "slow", command: process.execPath, args: [slowFixture], cwd: directory,
  });
  try {
    await mcp.connect();
    await assert.rejects(
      mcp.callTool("slow_echo", {}, { timeoutMs: 1_500, correlationId: "corr-slow" }),
      (error) => {
        assert.ok(error instanceof McpError);
        assert.equal(error.code, "MCP_TIMEOUT");
        assert.equal(error.requestId, "corr-slow");
        return true;
      },
    );
  } finally { mcp.stop(); }
});

test("AbortSignal cancels a pending call with MCP_CANCELLED", async () => {
  const slowFixture = path.join(directory, "fixtures", "mcp-slow-server.mjs");
  const mcp = new McpStdioClient({
    id: "slow", command: process.execPath, args: [slowFixture], cwd: directory,
  });
  const controller = new AbortController();
  try {
    await mcp.connect();
    const pending = mcp.callTool("slow_echo", { v: 1 }, { signal: controller.signal, correlationId: "corr-abort" });
    setTimeout(() => controller.abort(), 150);
    await assert.rejects(pending, (error) => {
      assert.ok(error instanceof McpError);
      assert.equal(error.code, "MCP_CANCELLED");
      assert.equal(error.requestId, "corr-abort");
      return true;
    });
    // после отмены клиент жив: следующий вызов работает
    const ok = await mcp.request("tools/list", {}, { timeoutMs: 5_000 });
    assert.ok(Array.isArray(ok.tools));
  } finally { mcp.stop(); }
});

test("requests before connect fail structured (MCP_NOT_RUNNING)", async () => {
  const mcp = client();
  await assert.rejects(
    mcp.request("tools/list", {}),
    (error) => error instanceof McpError && error.code === "MCP_NOT_RUNNING",
  );
});

test("already-aborted signal rejects immediately with MCP_CANCELLED", async () => {
  const mcp = client();
  try {
    await mcp.connect();
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      mcp.request("tools/list", {}, { signal: controller.signal, correlationId: "corr-preabort" }),
      (error) => error instanceof McpError && error.code === "MCP_CANCELLED" && error.requestId === "corr-preabort",
    );
  } finally { mcp.stop(); }
});

test("already-aborted callTool rejects before spawning the server", async () => {
  const mcp = client();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    mcp.callTool("echo", {}, { signal: controller.signal, correlationId: "corr-prespawn" }),
    (error) => error instanceof McpError && error.code === "MCP_CANCELLED" && error.requestId === "corr-prespawn",
  );
  assert.equal(mcp.child, null); // ни spawn, ни handshake не выполнялись
});

test("unsupported negotiated protocol version fails the handshake", async () => {
  const legacyFixture = path.join(directory, "fixtures", "mcp-legacy-server.mjs");
  const mcp = new McpStdioClient({
    id: "legacy", command: process.execPath, args: [legacyFixture], cwd: directory,
  });
  await assert.rejects(
    mcp.connect(),
    (error) => error instanceof McpError && error.code === "MCP_PROTOCOL_MISMATCH" && error.serverId === "legacy",
  );
  assert.equal(mcp.child, null); // stop() убил процесс после mismatch
});

test("redactMcpStderr strips key-like tokens from server diagnostics", () => {
  const noisy = "loaded key sk-abcdef1234567890abcdef bearer Bearer eyJhbGciOi.9887 pads AAAAAAAA...";
  const redacted = redactMcpStderr(noisy);
  assert.doesNotMatch(redacted, /sk-abcdef1234567890/);
  assert.doesNotMatch(redacted, /eyJhbGciOi/);
  assert.match(redacted, /\[redacted\]/);
});
