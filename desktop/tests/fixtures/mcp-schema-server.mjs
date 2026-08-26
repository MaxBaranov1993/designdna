import { createInterface } from "node:readline";

// MCP-сервер со строгой inputSchema для тестов валидации аргументов.
for await (const line of createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.id == null) continue;
  let result;
  if (message.method === "initialize") result = { protocolVersion: message.params.protocolVersion, serverInfo: { name: "schema-fixture", version: "1.0.0" }, capabilities: { tools: {} } };
  else if (message.method === "tools/list") result = { tools: [{
    name: "save_note",
    description: "Save a note",
    inputSchema: {
      type: "object",
      required: ["title", "body"],
      properties: {
        title: { type: "string" },
        body: { type: "string" },
        severity: { type: "string", enum: ["low", "high"] },
      },
    },
    annotations: { readOnlyHint: false },
  }] };
  else if (message.method === "tools/call") result = { content: [{ type: "text", text: JSON.stringify(message.params.arguments) }], isError: false };
  else { process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Method not found" } })}\n`); continue; }
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id: message.id, result })}\n`);
}
