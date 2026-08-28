import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/flow/serialize.ts", import.meta.url);
const storeUrl = new URL("../src/flow/store.ts", import.meta.url);
const canvasUrl = new URL("../src/FlowCanvas.svelte", import.meta.url);

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

test("a clean desktop canvas cannot overwrite SQLite before hydration", async () => {
  const [store, canvas] = await Promise.all([
    readFile(storeUrl, "utf8"),
    readFile(canvasUrl, "utf8"),
  ]);
  assert.match(store, /projectHydrated:\s*Boolean\(projectSaved\)/);
  assert.match(store, /loadPersistedProject:[\s\S]{0,2400}setTimeout\(\(\) => \{[\s\S]{0,160}projectHydrated:\s*true/);
  assert.match(canvas, /if \(!st\.projectHydrated\) return;[\s\S]{0,120}st\.syncFromCanvas/);
});
