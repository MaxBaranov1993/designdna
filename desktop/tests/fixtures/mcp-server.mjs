import { createInterface } from "node:readline";

for await (const line of createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.id == null) continue;
  let result;
  if (message.method === "initialize") result = { protocolVersion: message.params.protocolVersion, serverInfo: { name: "fixture", version: "1.0.0" }, capabilities: { tools: {} } };
  else if (message.method === "tools/list") result = { tools: [{ name: "echo", description: "Echo input", inputSchema: { type: "object" }, annotations: { readOnlyHint: false } }] };
  else if (message.method === "tools/call") result = { content: [{ type: "text", text: JSON.stringify(message.params.arguments) }], isError: false };
  else { process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Method not found" } })}\n`); continue; }
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`);
}
