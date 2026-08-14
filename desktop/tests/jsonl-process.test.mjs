import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { JsonlProcess } from "../lib/jsonl-process.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));

test("JsonlProcess correlates requests and shuts down", async () => {
  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(directory, "fixtures", "echo-worker.mjs")],
    name: "echo fixture",
  });
  const response = await worker.request("ping", { value: 42 });
  assert.deepEqual(response, { method: "ping", params: { value: 42 } });
  await worker.stop();
});
