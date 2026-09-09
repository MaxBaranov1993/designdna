import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import test from "node:test";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(new URL("../src/flow/serialize.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const A = "a".repeat(64), B = "b".repeat(64), C = "c".repeat(64), E = "e".repeat(64);
const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const reply = (status, body) => new Response(JSON.stringify(body), { status });

async function harness({ offload = async () => {} } = {}) {
  const timers = new Map(), storage = new Map(), handlers = new Map();
  const writes = [], requests = [], conflicts = [], beacons = [];
  let sequence = 0, active = 0, maxActive = 0;
  const exports = {};
  runInNewContext(compiled, {
    exports,
    require: (id) => {
      if (id.endsWith("blobStore")) return { isDesktopBlobUrl: () => false, offloadBlobsInPlace: offload };
      if (id.endsWith("toast")) return { toast() {} };
      if (id === "./ports" || id === "./dataflow") return {};
      throw new Error(`Unexpected dependency ${id}`);
    },
    setTimeout: (fn, delay = 0) => { const id = ++sequence; timers.set(id, { fn, delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    localStorage: {
      setItem: (key, value) => { storage.set(key, value); writes.push(JSON.parse(value)); },
      getItem: (key) => storage.get(key) ?? null,
      removeItem: (key) => storage.delete(key),
    },
    window: {
      addEventListener: (name, fn) => handlers.set(name, fn),
      dispatchEvent: (event) => conflicts.push(event.detail),
    },
    CustomEvent: class { constructor(type, { detail }) { this.type = type; this.detail = detail; } },
    navigator: { sendBeacon: (...args) => { beacons.push(args); return true; } },
    Blob,
    fetch: async (url, options) => {
      if (url.endsWith("load")) return reply(200, { revision: A, project: null });
      const deferred = Promise.withResolvers();
      active += 1;
      maxActive = Math.max(maxActive, active);
      requests.push({ body: JSON.parse(options.body), ...deferred });
      try { return await deferred.promise; } finally { active -= 1; }
    },
  });
  await exports.loadPagesProjectFromDb();
  const tick = async (delay) => {
    for (const [id, timer] of [...timers]) {
      if (timer.delay === delay && timers.delete(id)) timer.fn();
    }
    await settle();
  };
  const stage = async (marker) => {
    exports.scheduleProjectSave(() => ({ version: "designai-pages-v1", pages: [], marker }));
    await tick(300);
    await tick(0);
  };
  return { api: exports, tick, stage, timers, storage, writes, requests, conflicts, beacons, handlers,
    maxActive: () => maxActive };
}

test("slow earlier offload cannot overwrite newest snapshot; pending preparation is coalesced", async () => {
  const slow = Promise.withResolvers();
  const offloads = [];
  const h = await harness({ offload: async (snapshot) => {
    offloads.push(snapshot.marker);
    if (snapshot.marker === "old") await slow.promise;
  } });
  await h.stage("old");
  await h.stage("middle");
  await h.stage("newest");
  assert.deepEqual(offloads, ["old"], "only one offload may run at a time");
  slow.resolve();
  await settle();
  assert.deepEqual(offloads, ["old", "newest"]);
  assert.deepEqual(h.writes.map((x) => x.marker), ["newest"]);
  await h.tick(250);
  assert.equal(h.requests[0].body.project.marker, "newest");
  h.requests[0].resolve(reply(200, { revision: B }));
  await settle();
});

test("failed blob storage and unload retain Source screenshots in SQLite while local cache stays compact", async () => {
  const h = await harness({ offload: async () => { throw new Error('blob disk unavailable'); } });
  const preview = 'data:image/png;base64,c291cmNl';
  const project = { pages: [{ graph: { nodes: [{ type: 'sourceimport', data: {
    blocks: [{ name: 'header', preview, previews: { desktop: preview, mobile: preview } }],
  } }] } }] };
  h.api.scheduleProjectSave(() => project);
  await h.tick(300); await h.tick(0); await h.tick(250);
  const saved = h.requests[0].body.project.pages[0].graph.nodes[0].data.blocks[0];
  assert.equal(saved.preview, preview);
  assert.equal(saved.previews.mobile, preview);
  assert.equal(h.writes.at(-1).pages[0].graph.nodes[0].data.blocks[0].preview, undefined);
  h.requests[0].resolve(reply(200, {revision: B})); await settle();
  h.api.scheduleProjectSave(() => project);
  h.handlers.get('beforeunload')();
  const beacon = JSON.parse(await h.beacons.at(-1)[1].text());
  assert.equal(beacon.project.pages[0].graph.nodes[0].data.blocks[0].previews.desktop, preview);
});

test("a new edit invalidates an older offload even before the new debounce fires", async () => {
  const slow = Promise.withResolvers();
  const h = await harness({ offload: () => slow.promise });
  await h.stage("old");
  h.api.scheduleProjectSave(() => ({ pages: [], marker: "new" }));
  slow.resolve();
  await settle();
  assert.equal(h.writes.length, 0);
  await h.tick(300);
  await h.tick(0);
  assert.deepEqual(h.writes.map((x) => x.marker), ["new"]);
});

test("rapid own saves use one flight and the preceding acknowledgement CAS revision", async () => {
  const h = await harness();
  await h.stage("first");
  await h.tick(250);
  await h.stage("middle");
  await h.tick(250);
  await h.stage("latest");
  await h.tick(250);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].body.expectedRevision, A);
  h.requests[0].resolve(reply(200, { revision: B }));
  await settle();
  await h.tick(250);
  assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1].body.project.marker, "latest");
  assert.equal(h.requests[1].body.expectedRevision, B);
  h.requests[1].resolve(reply(200, { revision: C }));
  await settle();
  assert.equal(h.maxActive(), 1);
  assert.equal(h.conflicts.length, 0);
  assert.equal(h.timers.size, 0);
});

test("external conflict preserves newest data and blocks automatic retries including unload", async () => {
  const h = await harness();
  await h.stage("first");
  await h.tick(250);
  await h.stage("newer");
  h.requests[0].resolve(reply(409, { revision: E }));
  await settle();
  assert.equal(h.conflicts.length, 1);
  assert.equal(h.conflicts[0].expectedRevision, A);
  await h.stage("latest");
  await h.tick(250);
  h.handlers.get("beforeunload")();
  assert.equal(h.beacons.length, 0);
  assert.equal(h.requests.length, 1);
  assert.equal(h.writes.at(-1).marker, "latest");
  assert.equal(await h.api.resolveConflictKeepMine(null), false);
  const explicit = h.api.resolveConflictKeepMine(E);
  await settle();
  assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1].body.expectedRevision, E);
  assert.equal(h.requests[1].body.project.marker, "latest");
  h.requests[1].resolve(reply(409, { revision: C }));
  assert.equal(await explicit, false);
  await h.tick(250);
  assert.equal(h.requests.length, 2, "another conflict must not loop");
});

for (const failure of ["network", "http", "missing revision"]) {
  test(`${failure} failure keeps pending data without an automatic retry loop`, async () => {
    const h = await harness();
    await h.stage("first");
    await h.tick(250);
    await h.stage("latest");
    if (failure === "network") h.requests[0].reject(new Error("offline"));
    else h.requests[0].resolve(reply(failure === "http" ? 500 : 200, {}));
    await settle();
    for (let i = 0; i < 3; i++) await h.tick(250);
    assert.equal(h.requests.length, 1);
    assert.equal(h.writes.at(-1).marker, "latest");
    assert.equal(h.timers.size, 0);
  });
}

test("unload cannot race an in-flight save or be overwritten by a late offload", async () => {
  const slow = Promise.withResolvers();
  const h = await harness({ offload: (snapshot) => snapshot.marker === "latest" ? slow.promise : undefined });
  await h.stage("first");
  await h.tick(250);
  await h.stage("latest");
  h.handlers.get("beforeunload")();
  assert.equal(h.beacons.length, 0);
  assert.equal(h.writes.at(-1).marker, "latest");
  slow.resolve();
  await settle();
  assert.deepEqual(h.writes.map((x) => x.marker), ["first", "latest"]);
  h.requests[0].resolve(reply(200, { revision: B }));
  await settle();
});

test("take-theirs discards delayed preparation and ignores old save acknowledgements", async () => {
  const slow = Promise.withResolvers();
  const h = await harness({ offload: (snapshot) => snapshot.marker === "discard" ? slow.promise : undefined });
  await h.stage("first");
  await h.tick(250);
  await h.stage("discard");
  h.api.discardPendingDbSave();
  await h.api.loadPagesProjectFromDb();
  // The new edit's timer can fire while an old-epoch worker is still pending.
  await h.stage("after reload");
  await h.tick(250);
  h.requests[0].resolve(reply(200, { revision: B }));
  slow.resolve();
  await settle();
  assert.deepEqual(h.writes.map((x) => x.marker), ["first", "after reload"]);
  await h.tick(250);
  assert.equal(h.requests[1].body.expectedRevision, A, "late old acknowledgement cannot replace loaded revision");
  h.requests[1].resolve(reply(200, { revision: C }));
  await settle();
});

test("explicit keep-mine captures newer edits still awaiting blob preparation", async () => {
  const slow = Promise.withResolvers();
  const h = await harness({ offload: (snapshot) => snapshot.marker === "latest" ? slow.promise : undefined });
  await h.stage("old");
  await h.tick(250);
  h.requests[0].resolve(reply(409, { revision: E }));
  await settle();
  await h.stage("latest");
  const saved = h.api.resolveConflictKeepMine(E);
  await settle();
  assert.equal(h.requests[1].body.project.marker, "latest");
  assert.equal(h.requests[1].body.expectedRevision, E);
  h.requests[1].resolve(reply(200, { revision: B }));
  assert.equal(await saved, true);
  slow.resolve();
  await settle();
  await h.tick(250);
  assert.equal(h.requests.length, 2, "superseded offload must not resave after the explicit decision");
});
