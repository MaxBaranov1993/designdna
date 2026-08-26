import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/flow/serialize.ts", import.meta.url);

test("project autosave fails closed on a stale revision", async () => {
  const source = await readFile(sourceUrl, "utf8");
  const flushStart = source.indexOf("async function flushDbProject");
  const flushEnd = source.indexOf("\n}\n", flushStart);
  const flushSource = source.slice(flushStart, flushEnd + 2);

  assert.match(flushSource, /resp\.status === 409/);
  assert.match(flushSource, /designdna:project-conflict/);
  assert.match(flushSource, /lastDbProjectText = text/);
  assert.doesNotMatch(flushSource, /send\(typeof conflict\.revision/);
  assert.doesNotMatch(flushSource, /send\(null\)/);
});

test("empty loads and unload beacons preserve the CAS revision", async () => {
  const source = await readFile(sourceUrl, "utf8");
  assert.match(source, /data\.revision[\s\S]{0,180}if \(!data\.project\) return null/);
  assert.match(source, /expectedRevision[\s\S]{0,240}navigator\.sendBeacon/);
  assert.doesNotMatch(source, /new Blob\(\[`\{"project":\$\{lastDbProjectText\}\}`\]/);
});
