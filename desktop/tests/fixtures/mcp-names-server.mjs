import { createInterface } from "node:readline";

// Fixture with hostile tool names: sanitation-colliding pair and an over-64-char
// name. tools/call echoes the RAW called tool name so tests can prove exact
// mapping through the qualified provider-safe alias.
const TOOLS = [
  { name: "my-tool!", description: "collides after sanitation", inputSchema: { type: "object" }, annotations: { readOnlyHint: true } },
  { name: "my-tool?", description: "collides after sanitation too", inputSchema: { type: "object" }, annotations: { readOnlyHint: true } },
  { name: `tool_${"x".repeat(70)}`, description: "over 64 chars", inputSchema: { type: "object" }, annotations: { readOnlyHint: true } },
];

for await (const line of createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.id == null) continue;
  if (message.method === "initialize") {
    const result = { protocolVersion: message.params.protocolVersion, serverInfo: { name: "names", version: "1.0.0" }, capabilities: { tools: {} } };
    process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`);
    continue;
  }
  if (message.method === "tools/list") {
    process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result: { tools: TOOLS } })}\n`);
    continue;
  }
  if (message.method === "tools/call") {
    const result = { content: [{ type: "text", text: JSON.stringify({ called: message.params.name, arguments: message.params.arguments }) }], isError: false };
    process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`);
    continue;
  }
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Method not found" } })}\n`);
}
