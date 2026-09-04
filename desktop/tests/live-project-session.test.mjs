import assert from "node:assert/strict";
import test from "node:test";
import { LiveCommandRegistry } from "../services/live-command-registry.mjs";
import { LiveProjectSession } from "../services/live-project-session.mjs";

const REV_A = "a".repeat(64);
const REV_B = "b".repeat(64);
const REV_C = "c".repeat(64);
const T0 = "2026-08-25T12:00:00.000Z";
const T1 = "2026-08-25T12:01:00.000Z";

const createSession = (options = {}) => new LiveProjectSession({
  userId: "user-1",
  projectId: "project-1",
  now: () => Date.parse(T1),
  ...options,
});

const hydrate = (session, project = { pages: [{ id: "page-1", title: "Original" }] }) =>
  session.hydrateFromLoad(project, REV_A, T0);

const applyInput = (overrides = {}) => ({
  commandId: "cmd-1",
  idempotencyKey: "idem-1",
  baseRevision: REV_A,
  newRevision: REV_B,
  project: { pages: [{ id: "page-1", title: "Changed" }] },
  inverseCommand: { action: "project.restore", revision: REV_A },
  undoEntry: { id: "undo-1", label: "Change title" },
  ...overrides,
});

const rejectsCode = (fn, code) => assert.throws(fn, (error) => {
  assert.equal(error.code, code);
  return true;
});

test("hydrate establishes a clean authoritative snapshot and exact revision", () => {
  const session = createSession();
  const snapshot = hydrate(session);
  assert.equal(session.key, "user-1:project-1");
  assert.equal(session.currentRevision(), REV_A);
  assert.equal(snapshot.revision, REV_A);
  assert.equal(snapshot.persistedRevision, REV_A);
  assert.equal(snapshot.dirty, false);
  rejectsCode(() => session.hydrateFromLoad({}, "not-sha256", T0), "REVISION_INVALID");
});

test("snapshots and apply metadata are clone-isolated from callers", () => {
  const session = createSession();
  const source = { pages: [{ id: "page-1", title: "Original" }] };
  hydrate(session, source);
  source.pages[0].title = "Caller mutation";
  const first = session.getSnapshot();
  first.project.pages[0].title = "Snapshot mutation";
  assert.equal(session.getSnapshot().project.pages[0].title, "Original");

  const input = applyInput();
  session.compareAndSwapApply(input);
  input.project.pages[0].title = "Post-apply mutation";
  input.undoEntry.label = "Tampered";
  assert.equal(session.getSnapshot().project.pages[0].title, "Changed");
  assert.equal(session.undoEntries[0].undoEntry.label, "Change title");
});

test("state byte bounds and unsafe JSON fail before canonical mutation", () => {
  const session = createSession({ maxProjectBytes: 128 });
  rejectsCode(() => session.hydrateFromLoad({ text: "я".repeat(100) }, REV_A, T0), "STATE_TOO_LARGE");
  hydrate(session, { ok: true });
  rejectsCode(() => session.compareAndSwapApply(applyInput({ project: { text: "x".repeat(200) } })), "STATE_TOO_LARGE");
  assert.equal(session.currentRevision(), REV_A);
  const polluted = JSON.parse('{"__proto__":{"polluted":true}}');
  rejectsCode(() => session.compareAndSwapApply(applyInput({ project: polluted })), "STATE_INVALID");
  assert.equal({}.polluted, undefined);
});

test("project bytes can be validated before persistence without mutating the session", () => {
  const session = createSession({ maxProjectBytes: 128 });
  hydrate(session, { ok: true });
  const before = session.getSnapshot();
  assert.ok(session.validateProject({ pages: [] }).bytes > 0);
  rejectsCode(() => session.validateProject({ text: "x".repeat(200) }), "STATE_TOO_LARGE");
  assert.deepEqual(session.getSnapshot(), before);
});

test("CAS apply marks dirty, replays idempotently and persisted acknowledgement marks clean", () => {
  const session = createSession();
  hydrate(session);
  const first = session.compareAndSwapApply(applyInput());
  assert.equal(first.replayed, false);
  assert.equal(session.getSnapshot().dirty, true);
  const replay = session.compareAndSwapApply(applyInput());
  assert.equal(replay.replayed, true);
  assert.equal(session.changesSince(0).events.filter((event) => event.type === "session.applied").length, 1);
  const saved = session.notePersistedSave(applyInput().project, REV_A, REV_B, T1);
  assert.equal(saved.dirty, false);
  assert.equal(saved.persistedRevision, REV_B);
});

test("stale saves and conflicting external loads fail closed", () => {
  const session = createSession();
  hydrate(session);
  rejectsCode(
    () => session.notePersistedSave({ pages: [] }, REV_C, REV_B, T1),
    "STALE_SAVE",
  );
  session.compareAndSwapApply(applyInput());
  rejectsCode(
    () => session.hydrateFromLoad({ pages: [{ id: "external" }] }, REV_C, T1),
    "EXTERNAL_WRITE_CONFLICT",
  );
  rejectsCode(
    () => session.notePersistedSave({ pages: [{ id: "different" }] }, REV_A, REV_B, T1),
    "EXTERNAL_WRITE_CONFLICT",
  );
  assert.equal(session.currentRevision(), REV_B);
  assert.equal(session.getSnapshot().dirty, true);
});

test("same revision with server-normalized bytes is a reload, not a conflict", () => {
  const session = createSession();
  hydrate(session);
  // load отдаёт мигрированный payload при той же ревизии (SHA сырых байтов)
  const normalized = session.hydrateFromLoad({ pages: [], migrated: true }, REV_A, "2026-08-25T12:00:00.000Z");
  assert.equal(normalized.revision, REV_A);
  assert.equal(normalized.dirty, false);
  assert.deepEqual(normalized.project, { pages: [], migrated: true });
  // грязная сессия при той же ревизии сохраняет свои байты
  session.compareAndSwapApply(applyInput());
  const kept = session.hydrateFromLoad({ pages: [], migrated: true }, session.currentRevision(), T1);
  assert.equal(kept.dirty, true);
  assert.notDeepEqual(kept.project, { pages: [], migrated: true });
});

test("stale loads are rejected while a newer clean external revision may hydrate", () => {
  const session = createSession();
  hydrate(session);
  rejectsCode(() => session.hydrateFromLoad({ pages: [] }, REV_B, "2026-08-25T11:59:00.000Z"), "STALE_LOAD");
  const updated = session.hydrateFromLoad({ pages: [{ id: "external" }] }, REV_B, T1);
  assert.equal(updated.revision, REV_B);
  assert.equal(updated.dirty, false);
});

test("concurrent CAS contenders cannot both commit from the same base revision", async () => {
  const session = createSession();
  hydrate(session);
  const attempts = await Promise.allSettled([
    Promise.resolve().then(() => session.compareAndSwapApply(applyInput())),
    Promise.resolve().then(() => session.compareAndSwapApply(applyInput({
      commandId: "cmd-2",
      idempotencyKey: "idem-2",
      newRevision: REV_C,
      project: { pages: [{ title: "Competing write" }] },
    }))),
  ]);
  assert.equal(attempts.filter((item) => item.status === "fulfilled").length, 1);
  const rejected = attempts.find((item) => item.status === "rejected");
  assert.equal(rejected.reason.code, "STALE_REVISION");
  assert.equal(session.currentRevision(), REV_B);
});

test("preview execution and resolution always use the session-owned revision", async () => {
  const now = Date.parse(T0);
  const registry = new LiveCommandRegistry({ now: () => now });
  registry.register("editor.style.patch", async (request, context) => {
    assert.equal(context.currentRevision, REV_A);
    return {
      previewId: "preview-1",
      baseRevision: request.baseRevision,
      patch: [],
      inversePatch: [],
      affectedObjects: [],
      preservedRules: [],
      violations: [],
      qualityReport: {},
      expiresAt: "2026-08-25T12:05:00.000Z",
    };
  });
  const session = createSession({ registry, now: () => now });
  hydrate(session);
  const request = {
    commandId: "cmd-1",
    idempotencyKey: "idem-1",
    projectId: "project-1",
    pageId: "page-1",
    baseRevision: REV_A,
    intent: "Preview",
    scope: { nodeIds: [], sourceKeys: [], viewports: ["desktop"] },
    action: "editor.style.patch",
    arguments: {},
    mode: "preview",
    correlationId: "trace-1",
    timeoutMs: 10_000,
  };
  await session.beginPreview(request, { currentRevision: REV_C });
  assert.equal(session.resolvePreview("preview-1").baseRevision, REV_A);
  session.compareAndSwapApply(applyInput());
  rejectsCode(() => session.resolvePreview("preview-1"), "PREVIEW_STALE");
  await assert.rejects(session.beginPreview({ ...request, baseRevision: REV_C }), (error) => error.code === "STALE_REVISION");
});

test("renderer attachments advance generation and stale generations are rejected", () => {
  const session = createSession();
  const first = session.attachRenderer("renderer-1");
  const second = session.attachRenderer("renderer-1");
  assert.equal(first.generation, 1);
  assert.equal(second.generation, 2);
  assert.equal(session.isRendererGenerationCurrent("renderer-1", 1), false);
  assert.equal(session.isRendererGenerationCurrent("renderer-1", 2), true);
});

test("session events are ordered, cloned and listener failures are isolated", () => {
  const session = createSession({ maxEvents: 3 });
  const received = [];
  session.subscribe(() => { throw new Error("observer failed"); });
  const unsubscribe = session.subscribe((event) => {
    event.type = "tampered";
    received.push(event);
  });
  hydrate(session);
  session.attachRenderer("renderer-1");
  session.compareAndSwapApply(applyInput());
  assert.equal(received.length, 3);
  assert.deepEqual(session.changesSince(0).events.map((event) => event.cursor), [1, 2, 3]);
  assert.equal(session.changesSince(0).events[0].type, "session.hydrated");
  unsubscribe();
  session.notePersistedSave(applyInput().project, REV_A, REV_B, T1);
  assert.equal(received.length, 3);
  const bounded = session.changesSince(0);
  assert.deepEqual(bounded.events.map((event) => event.cursor), [2, 3, 4]);
  assert.equal(bounded.truncated, true);
});
