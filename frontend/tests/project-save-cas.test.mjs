import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/flow/serialize.ts", import.meta.url);
const storeUrl = new URL("../src/flow/store.ts", import.meta.url);
const canvasUrl = new URL("../src/FlowCanvas.svelte", import.meta.url);

test("project autosave fails closed on a stale revision", async () => {
  const source = (await readFile(sourceUrl, "utf8")).replace(/\r\n/g, "\n");
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
  const source = (await readFile(sourceUrl, "utf8")).replace(/\r\n/g, "\n");
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
  const hydration = store.slice(store.indexOf("loadPersistedProject: async"), store.indexOf("replaceProjectFromDb: async"));
  assert.match(hydration, /setTimeout\(\(\) => \{\s*set\(\{ projectHydrated: true \}\)/);
  assert.match(canvas, /if \(!\$flowHydrated\) return;[\s\S]*?st\.syncFromCanvas/);
});
