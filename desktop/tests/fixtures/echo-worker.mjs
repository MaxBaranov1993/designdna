import { createInterface } from "node:readline";

for await (const line of createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.method === "shutdown") {
    process.stdout.write(`${JSON.stringify({ id: message.id, result: { shutdown: true } })}\n`);
    process.exit(0);
  }
  process.stdout.write(`${JSON.stringify({ id: message.id, result: { method: message.method, params: message.params } })}\n`);
}
