import { createInterface } from "node:readline";

// Fixture that negotiates an unsupported protocol version: the client must
// reject the handshake with MCP_PROTOCOL_MISMATCH and stop the process.
for await (const line of createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.id == null) continue;
  if (message.method === "initialize") {
    const result = { protocolVersion: "1999-01-01", serverInfo: { name: "legacy", version: "0.0.1" }, capabilities: {} };
    process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`);
    continue;
  }
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Method not found" } })}\n`);
}
