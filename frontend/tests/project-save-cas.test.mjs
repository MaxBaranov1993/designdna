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
  assert.match(store, /projectHydrated:\s*false,/);
  const hydration = store.slice(store.indexOf("loadPersistedProject: async"), store.indexOf("replaceProjectFromDb: async"));
  assert.match(hydration, /setTimeout\(\(\) => \{\s*set\(\{ projectHydrated: true \}\)/);
  assert.match(canvas, /if \(!\$flowHydrated\) return;[\s\S]*?st\.syncFromCanvas/);
});

test("edits made while a saved project loads pause autosave instead of overwriting it", async () => {
  const [store, source, dialog] = await Promise.all([
    readFile(storeUrl, "utf8"),
    readFile(sourceUrl, "utf8"),
    readFile(new URL("../src/flow/ConflictDialog.svelte", import.meta.url), "utf8"),
  ]);
  const hydration = store.slice(store.indexOf("loadPersistedProject: async"), store.indexOf("replaceProjectFromDb: async"));
  assert.match(hydration, /if \(localDirtySinceInit\) \{[\s\S]{0,260}blockDbSaveForHydrationConflict\(\)/,
    "a dirty startup cache must not keep a CAS-valid base for the full saved project");
  const block = source.slice(source.indexOf("export function blockDbSaveForHydrationConflict"));
  assert.match(block, /dbConflictBlocked = true/);
  assert.match(block, /edited-while-loading/);
  assert.match(dialog, /whileLoading[\s\S]*Load saved project/);
});


test("the project lives only in SQLite: no localStorage writes, one-time migration, flush on quit", async () => {
  const [store, source, main] = await Promise.all([
    readFile(storeUrl, "utf8"),
    readFile(sourceUrl, "utf8"),
    readFile(new URL("../../desktop/main.mjs", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(source, /localStorage\.setItem/, "autosave never writes the project to localStorage");
  assert.doesNotMatch(store, /const projectSaved = loadPagesProjectFromStorage\(\)/, "startup does not read the old cache");
  const hydration = store.slice(store.indexOf("loadPersistedProject: async"), store.indexOf("replaceProjectFromDb: async"));
  assert.match(hydration, /if \(project\) \{\s*clearLocalProjectCache\(\);/);
  assert.match(hydration, /loadPagesProjectFromStorage\(\)[\s\S]*migrated = !!project/);
  assert.match(hydration, /if \(migrated\) void flushProjectToDb\(\)\.then\(\(ok\) => \{ if \(ok\) clearLocalProjectCache\(\); \}\)/,
    "the old cache is dropped only after SQLite accepted the moved project");
  assert.match(source, /__designdnaFlushProject = flushProjectToDb/);
  assert.match(main, /void flushAllProjects\(\)\.then\(\(\) => shutdown\(\)\)/, "quit flushes before stopping the Python worker");
  assert.match(main, /window\.on\("close", \(event\) => \{[\s\S]*flushWindowProject\(window\)/);
});
