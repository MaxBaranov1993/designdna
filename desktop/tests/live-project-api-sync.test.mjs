import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { LiveProjectApiSync } from "../services/live-project-api-sync.mjs";
import { ApiScheduler } from "../services/api-scheduler.mjs";
import { ApiRequestManager } from "../services/api-request-manager.mjs";

const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);
const request = (path, body) => ({ path, body: new TextEncoder().encode(JSON.stringify(body)) });
const response = (status, body) => ({ status, encoding: "utf8", body: JSON.stringify(body) });

// Execute the actual IPC handler without importing Electron or starting workers.
// This catches preparation accidentally moving outside the serialized callback.
function apiHandler(sync, reply) {
  const main = readFileSync(new URL("../main.mjs", import.meta.url), "utf8");
  const start = main.indexOf('  handleTrusted("api:request",');
  const end = main.indexOf('  handleTrusted("repo-canvas:snapshot",', start);
  assert.ok(start >= 0 && end > start);
  let handler;
  const worker = { request: reply };
  runInNewContext(main.slice(start, end), {
    handleTrusted: (_channel, callback) => { handler = callback; },
    validateApiRequest: (value) => value,
    liveProjects: sync,
    apiScheduler: new ApiScheduler(),
    INTERACTIVE_API_PATHS: new Set(),
    pythonWorker: worker,
    pythonInteractiveWorker: worker,
    sourceAuthIntent: () => null,
    ensureWorkerConfigured: async () => {},
    apiSequence: 0,
    apiRequests: new ApiRequestManager(),
    Uint8Array,
    Buffer,
  });
  return (value) => handler({}, value);
}

const loadResponse = (project, revision = A) => response(200, {
  project, revision, updated_at: "2026-08-25T12:00:00Z",
});
const saveResponse = (revision = B) => response(200, {
  ok: true, revision, updated_at: "2026-08-25T12:01:00Z",
});

for (const nextLarge of [false, true]) {
  test(`IPC queued oversized load then ${nextLarge ? "oversized" : "small"} load preserves both responses`, async () => {
    const sync = new LiveProjectApiSync({ maxProjectBytes: 96 });
    const large = { text: "x".repeat(160) };
    const replies = [loadResponse(large), loadResponse(nextLarge ? large : { pages: [] })];
    const sessions = [];
    const invoke = apiHandler(sync, async () => {
      sessions.push(sync.get());
      return replies[sessions.length - 1];
    });
    const first = invoke(request("/api/project/load", {}));
    const second = invoke(request("/api/project/load", {}));
    const results = await Promise.all([first, second]);
    assert.equal(results[0], replies[0]);
    assert.equal(results[1], replies[1]);
    assert.notEqual(sessions[0], sessions[1]);
    assert.equal(sessions[0].disposed, true);
    assert.equal(sync.getSnapshot()?.revision ?? null, nextLarge ? null : A);
  });
}

test("IPC committed save acknowledgement survives a queued oversized save", async () => {
  const sync = new LiveProjectApiSync({ maxProjectBytes: 96 });
  sync.synchronize(sync.prepare(request("/api/project/load", {})), loadResponse({ value: 1 }));
  const session = sync.get();
  const started = Promise.withResolvers();
  const committed = Promise.withResolvers();
  const persisted = [];
  const firstReply = saveResponse();
  const secondReply = saveResponse(C);
  const invoke = apiHandler(sync, async () => {
    if (persisted.length === 0) {
      persisted.push(B); // Fake worker has committed before returning its reply.
      started.resolve();
      await committed.promise;
      return firstReply;
    }
    assert.equal(session.persistedRevision, B, "first acknowledgement synchronized before reset");
    persisted.push(C);
    return secondReply;
  });
  const first = invoke(request("/api/project/save", { project: { value: 2 }, expectedRevision: A }));
  await started.promise;
  const second = invoke(request("/api/project/save", { project: { text: "x".repeat(160) }, expectedRevision: B }));
  assert.equal(session.disposed, false, "queued preparation must not dispose the in-flight session");
  committed.resolve();
  assert.equal(await first, firstReply);
  assert.equal(await second, secondReply);
  assert.deepEqual(persisted, [B, C]);
  assert.equal(session.disposed, true);
});

test("IPC queued save validates against the preceding acknowledged revision", async () => {
  const sync = new LiveProjectApiSync();
  sync.synchronize(sync.prepare(request("/api/project/load", {})), loadResponse({ value: 1 }));
  let writes = 0;
  const invoke = apiHandler(sync, async () => { writes += 1; return saveResponse(); });
  const first = invoke(request("/api/project/save", { project: { value: 2 }, expectedRevision: A }));
  const stale = invoke(request("/api/project/save", { project: { value: 3 }, expectedRevision: A }));
  assert.equal((await first).status, 200);
  const rejected = await stale;
  assert.equal(rejected.status, 409);
  assert.equal(JSON.parse(rejected.body).revision, B);
  assert.equal(writes, 1);
});

for (const path of ["/api/project/load", "/api/project/save"]) {
  test(`IPC shutdown preserves in-flight ${path} response and rejects queued project work`, async () => {
    const sync = new LiveProjectApiSync();
    sync.synchronize(sync.prepare(request("/api/project/load", {})), loadResponse({ value: 1 }));
    const started = Promise.withResolvers();
    const finished = Promise.withResolvers();
    const reply = path.endsWith("save") ? saveResponse() : loadResponse({ value: 1 });
    let calls = 0;
    const invoke = apiHandler(sync, async () => {
      calls += 1;
      started.resolve();
      await finished.promise;
      return reply;
    });
    const pending = invoke(request(path, { project: { value: 2 }, expectedRevision: A }));
    await started.promise;
    const queued = invoke(request("/api/project/load", {}));
    sync.dispose();
    sync.dispose(); // idempotent; late replies must not create a new session
    finished.resolve();
    assert.equal(await pending, reply);
    const rejected = await queued;
    assert.equal(rejected.status, 503);
    assert.equal(JSON.parse(rejected.body).error, "SESSION_DISPOSED");
    assert.equal(calls, 1);
    assert.equal(sync.getSnapshot(), null);
    assert.equal(sync.sessions.size, 0);
  });
}

test("late capacity-reset contexts cannot overwrite a newer session or hide a save acknowledgement", () => {
  const sync = new LiveProjectApiSync({ maxProjectBytes: 96 });
  sync.synchronize(sync.prepare(request("/api/project/load", {})), loadResponse({ value: 1 }));
  const oldLoad = sync.prepare(request("/api/project/load", {}));
  const oldSave = sync.prepare(request("/api/project/save", { project: { value: 2 }, expectedRevision: A }));
  sync.prepare(request("/api/project/save", { project: { text: "x".repeat(160) }, expectedRevision: B }));
  const current = sync.prepare(request("/api/project/load", {}));
  sync.synchronize(current, loadResponse({ value: 3 }, C));
  assert.equal(sync.synchronize(oldLoad, loadResponse({ value: 1 })), null);
  const acknowledgement = saveResponse();
  const original = JSON.stringify(acknowledgement);
  assert.equal(sync.synchronize(oldSave, acknowledgement), null);
  assert.equal(JSON.stringify(acknowledgement), original);
  assert.equal(sync.get(), current.session);
  assert.equal(sync.getSnapshot().revision, C);
  assert.deepEqual(sync.getSnapshot().project, { value: 3 });
});

test("active-session response contract errors are not suppressed by lifecycle handling", () => {
  const sync = new LiveProjectApiSync();
  const load = sync.prepare(request("/api/project/load", {}));
  assert.throws(() => sync.synchronize(load, loadResponse({}, "invalid")), { code: "REVISION_INVALID" });
  sync.synchronize(load, loadResponse({ value: 1 }));
  const first = sync.prepare(request("/api/project/save", { project: { value: 2 }, expectedRevision: A }));
  const stale = sync.prepare(request("/api/project/save", { project: { value: 3 }, expectedRevision: A }));
  sync.synchronize(first, saveResponse());
  assert.throws(() => sync.synchronize(stale, saveResponse(C)), { code: "STALE_SAVE" });
  assert.equal(sync.getSnapshot().revision, B);
});

test("load hydrates the authoritative session and normalizes Python UTC timestamps", () => {
  const sync = new LiveProjectApiSync();
  const context = sync.prepare(request("/api/project/load", {}));
  const snapshot = sync.synchronize(context, response(200, {
    project: { pages: [] }, revision: A, updated_at: "2026-08-25T12:00:00+00:00",
  }));
  assert.equal(snapshot.revision, A);
  assert.equal(snapshot.updatedAt, "2026-08-25T12:00:00.000Z");
  assert.deepEqual(sync.getSnapshot().project, { pages: [] });
});

test("missing projects still hydrate the empty CAS revision", () => {
  const sync = new LiveProjectApiSync();
  const context = sync.prepare(request("/api/project/load", {}));
  const snapshot = sync.synchronize(context, response(200, { project: null, revision: A, updated_at: null }));
  assert.equal(snapshot.revision, A);
  assert.deepEqual(snapshot.project, {});
});

test("save requires CAS and rejects a renderer revision that is not authoritative", () => {
  const sync = new LiveProjectApiSync();
  sync.synchronize(sync.prepare(request("/api/project/load", {})), response(200, {
    project: { value: 1 }, revision: A, updated_at: "2026-08-25T12:00:00Z",
  }));
  assert.throws(() => sync.prepare(request("/api/project/save", { project: { value: 2 } })), /expectedRevision/);
  assert.throws(
    () => sync.prepare(request("/api/project/save", { project: { value: 2 }, expectedRevision: C })),
    (error) => error.code === "STALE_REVISION" && error.currentRevision === A,
  );
});

test("successful save advances the session while a 409 leaves it unchanged", () => {
  const sync = new LiveProjectApiSync();
  sync.synchronize(sync.prepare(request("/api/project/load", {})), response(200, {
    project: { value: 1 }, revision: A, updated_at: "2026-08-25T12:00:00Z",
  }));
  const stale = sync.prepare(request("/api/project/save", { project: { value: 2 }, expectedRevision: A }));
  assert.equal(sync.synchronize(stale, response(409, { stale: true, revision: C })), null);
  assert.equal(sync.getSnapshot().revision, A);
  const saved = sync.prepare(request("/api/project/save", { project: { value: 2 }, expectedRevision: A }));
  sync.synchronize(saved, response(200, {
    ok: true, revision: B, updated_at: "2026-08-25T12:01:00+00:00",
  }));
  assert.equal(sync.getSnapshot().revision, B);
  assert.deepEqual(sync.getSnapshot().project, { value: 2 });
});

test("unrelated API requests are ignored", () => {
  const sync = new LiveProjectApiSync();
  assert.equal(sync.prepare(request("/api/config", {})), null);
});

test("oversized canonical projects bypass the bounded live bridge without failing load or save", () => {
  const sync = new LiveProjectApiSync({ maxProjectBytes: 96 });
  const largeProject = { pages: [{ graph: { nodes: [{ data: { text: "x".repeat(160) } }] } }] };

  const loadContext = sync.prepare(request("/api/project/load", {}));
  assert.equal(sync.synchronize(loadContext, response(200, {
    project: largeProject,
    revision: A,
    updated_at: "2026-08-25T12:00:00Z",
  })), null);
  assert.equal(sync.getSnapshot(), null);

  const saveContext = sync.prepare(request("/api/project/save", {
    project: largeProject,
    expectedRevision: A,
  }));
  assert.equal(saveContext.bypassReason, "STATE_TOO_LARGE");
  assert.equal(sync.synchronize(saveContext, response(200, {
    ok: true,
    revision: B,
    updated_at: "2026-08-25T12:01:00Z",
  })), null);

  const recovered = sync.prepare(request("/api/project/save", {
    project: { pages: [] },
    expectedRevision: B,
  }));
  sync.synchronize(recovered, response(200, {
    ok: true,
    revision: C,
    updated_at: "2026-08-25T12:02:00Z",
  }));
  assert.equal(sync.getSnapshot().revision, C);
});
