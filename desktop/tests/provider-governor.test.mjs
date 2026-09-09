import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_PROVIDER_LIMITS, ProviderGovernor, parseProviderLimits } from "../services/provider-governor.mjs";

test("limits come from the env spec with safe defaults", () => {
  assert.deepEqual(parseProviderLimits(""), DEFAULT_PROVIDER_LIMITS);
  const parsed = parseProviderLimits("claude=1, codex=3, bogus, openai=99, glm=abc");
  assert.equal(parsed.claude, 1);
  assert.equal(parsed.codex, 3);
  assert.equal(parsed.openai, DEFAULT_PROVIDER_LIMITS.openai, "out-of-range values keep the default");
  assert.equal(parsed.glm, undefined);
});

test("slots are granted up to the limit, then requests wait in FIFO order", async () => {
  const governor = new ProviderGovernor({ limits: { claude: 2 } });
  const first = await governor.acquire("claude");
  const second = await governor.acquire("claude");
  assert.deepEqual(governor.snapshot().claude, { limit: 2, active: 2, queued: 0 });
  const order = [];
  const third = governor.acquire("claude").then((slot) => { order.push("third"); return slot; });
  const fourth = governor.acquire("claude").then((slot) => { order.push("fourth"); return slot; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(order, []);
  assert.equal(governor.snapshot().claude.queued, 2);
  first.release();
  first.release();
  const slotThree = await third;
  assert.deepEqual(order, ["third"], "a double release must not grant two slots");
  assert.equal(governor.snapshot().claude.active, 2);
  second.release();
  await fourth;
  assert.deepEqual(order, ["third", "fourth"]);
  slotThree.release();
  (await fourth).release();
  assert.deepEqual(governor.snapshot().claude, { limit: 2, active: 0, queued: 0 });
});

test("a queued request can be cancelled without consuming a slot", async () => {
  const governor = new ProviderGovernor({ limits: { codex: 1 } });
  const held = await governor.acquire("codex");
  const abort = new AbortController();
  const waiting = governor.acquire("codex", { signal: abort.signal });
  abort.abort();
  await assert.rejects(waiting, /cancelled while queued/);
  assert.equal(governor.snapshot().codex.queued, 0);
  held.release();
  assert.equal(governor.snapshot().codex.active, 0);
  const already = new AbortController();
  already.abort();
  await governor.acquire("codex").then((slot) => slot.release());
  const other = await governor.acquire("codex");
  await assert.rejects(governor.acquire("codex", { signal: already.signal }), /cancelled/);
  other.release();
});

test("unknown providers fall back to the codex limit and report queued time", async () => {
  let now = 1_000;
  const governor = new ProviderGovernor({ limits: { codex: 1 }, now: () => now });
  const held = await governor.acquire("astra");
  assert.equal(governor.limit("astra"), 1);
  const waiting = governor.acquire("astra");
  now += 250;
  held.release();
  const slot = await waiting;
  assert.equal(slot.queuedMs, 250);
  slot.release();
});
