import assert from "node:assert/strict";
import test from "node:test";
import { SerialRequestQueue } from "../lib/serial-request-queue.mjs";

test("SerialRequestQueue waits for the active operation", async () => {
  const queue = new SerialRequestQueue();
  const events = [];
  let releaseFirst;
  const firstGate = new Promise((resolve) => { releaseFirst = resolve; });

  const first = queue.run(async () => {
    events.push("first:start");
    await firstGate;
    events.push("first:end");
    return 1;
  });
  const second = queue.run(async () => {
    events.push("second:start");
    return 2;
  });

  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(events, ["first:start"]);
  releaseFirst();
  assert.deepEqual(await Promise.all([first, second]), [1, 2]);
  assert.deepEqual(events, ["first:start", "first:end", "second:start"]);
});

test("SerialRequestQueue continues after a rejected operation", async () => {
  const queue = new SerialRequestQueue();
  await assert.rejects(queue.run(async () => { throw new Error("expected"); }), /expected/);
  assert.equal(await queue.run(async () => "recovered"), "recovered");
});
