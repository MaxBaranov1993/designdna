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

test("JsonlProcess carries binary bodies without base64 (protocol v2)", async () => {
  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(directory, "fixtures", "echo-worker.mjs")],
    name: "echo fixture",
  });
  // тело с \n, нулями и не-UTF8 секцией: в base64-JSON этого бы не выжило без эскейпинга
  const body = new Uint8Array(300_000);
  for (let i = 0; i < body.length; i++) body[i] = i % 251;
  body.set([0x0a, 0x0d, 0x00, 0x22, 0x5c], 100);
  const response = await worker.request("http.request", { path: "/api/x", bodyBytes: body });
  assert.ok(response.bodyBytes instanceof Uint8Array);
  assert.equal(response.bodyBytes.length, body.length);
  assert.deepEqual(Buffer.from(response.bodyBytes.subarray(0, 8)), Buffer.from(body.subarray(0, 8)));
  assert.deepEqual(Buffer.from(response.bodyBytes.subarray(299_992)), Buffer.from(body.subarray(299_992)));
  await worker.stop();
});

test("JsonlProcess abort rejects pending and respawns on next request", async () => {
  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(directory, "fixtures", "echo-worker.mjs")],
    name: "echo fixture",
  });
  const spawnsBefore = worker.spawnCount;
  const pending = worker.request("ping", { slow: true });
  worker.abort("cancelled by user");
  await assert.rejects(pending, /cancelled by user/);
  const response = await worker.request("ping", { value: 1 });
  assert.deepEqual(response, { method: "ping", params: { value: 1 } });
  assert.ok(worker.spawnCount > spawnsBefore);
  await worker.stop();
});
