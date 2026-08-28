import assert from "node:assert/strict";
import test from "node:test";
import { LiveProjectApiSync } from "../services/live-project-api-sync.mjs";

const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);
const request = (path, body) => ({ path, body: new TextEncoder().encode(JSON.stringify(body)) });
const response = (status, body) => ({ status, encoding: "utf8", body: JSON.stringify(body) });

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
