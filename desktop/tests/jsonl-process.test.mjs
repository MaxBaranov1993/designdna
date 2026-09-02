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

test("JsonlProcess emits spawned/exited for an unexpected death and expected stop", async () => {
  const dying = new JsonlProcess({
    command: process.execPath,
    args: ["-e", "setTimeout(() => process.exit(3), 30)"],
    name: "dying fixture",
  });
  const events = [];
  dying.on("spawned", (info) => events.push(["spawned", info.spawnCount]));
  const exited = new Promise((resolve) => dying.once("exited", resolve));
  dying.start();
  const exit = await exited;
  assert.deepEqual(events, [["spawned", 1]]);
  assert.equal(exit.code, 3);
  assert.equal(exit.expected, false);
  assert.match(exit.error.message, /exited \(3\)/);
  assert.equal(dying.alive, false);

  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(directory, "fixtures", "echo-worker.mjs")],
    name: "echo fixture",
  });
  const stopped = new Promise((resolve) => worker.once("exited", resolve));
  await worker.request("ping", {});
  await worker.stop();
  assert.equal((await stopped).expected, true);
});

test("JsonlProcess honours caller-provided frame ids, control frames and pending events", async () => {
  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(directory, "fixtures", "echo-worker.mjs")],
    name: "echo fixture",
  });
  const pendingCounts = [];
  worker.on("pending", ({ count }) => pendingCounts.push(count));
  const response = await worker.request("ping", { value: 7 }, 5_000, { id: "api-42" });
  assert.deepEqual(response, { method: "ping", params: { value: 7 } });
  assert.deepEqual(pendingCounts, [1, 0]);
  // служебный фрейм без ответа: echo просто вернёт его как обычный фрейм с id=undefined — нас
  // интересует только, что канал принял запись
  assert.equal(worker.sendControl({ type: "cancel", requestId: "api-42" }), true);
  const aborted = new Promise((resolve) => worker.once("aborted", resolve));
  worker.abort("test abort");
  assert.deepEqual(await aborted, { reason: "test abort", hadProcess: true });
  assert.equal(worker.sendControl({ type: "cancel" }), false);
});

test("JsonlProcess marks cancelled worker errors", async () => {
  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(directory, "fixtures", "cancelling-worker.mjs")],
    name: "cancelling fixture",
  });
  await assert.rejects(worker.request("http.request", {}), (error) => error.code === "cancelled" && error.cancelled === true);
  await worker.stop();
});
