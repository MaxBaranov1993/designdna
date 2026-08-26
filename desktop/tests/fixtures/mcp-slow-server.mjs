import { createInterface } from "node:readline";

// Медленный MCP-сервер для тестов таймаутов/отмены: tools/call отвечает
// только через 10 секунд, всё остальное — мгновенно.
for await (const line of createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.id == null) continue;
  let result;
  if (message.method === "initialize") result = { protocolVersion: message.params.protocolVersion, serverInfo: { name: "slow-fixture", version: "1.0.0" }, capabilities: { tools: {} } };
  else if (message.method === "tools/list") result = { tools: [{ name: "slow_echo", description: "Echo after delay", inputSchema: { type: "object" }, annotations: { readOnlyHint: true } }] };
  else if (message.method === "tools/call") {
    setTimeout(() => {
      process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result: { content: [{ type: "text", text: JSON.stringify(message.params.arguments) }] } })}\n`);
    }, 10_000);
    continue;
  }
  else { process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Method not found" } })}\n`); continue; }
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`);
}
