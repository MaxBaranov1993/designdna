import assert from "node:assert/strict";
import test from "node:test";
import { LiveCommandContractError } from "../services/live-command-contract.mjs";
import { LiveCommandBroker, LiveCommandRegistry } from "../services/live-command-registry.mjs";

const makeRequest = (overrides = {}) => ({
  commandId: "cmd-1",
  idempotencyKey: "idem-1",
  projectId: "project-1",
  pageId: "page-1",
  baseRevision: "rev-1",
  intent: "Change the selected CTA",
  scope: { nodeIds: ["12"], sourceKeys: ["hero/cta"], viewports: ["desktop"] },
  action: "editor.style.patch",
  arguments: { color: "#7018e6" },
  mode: "preview",
  correlationId: "trace-1",
  timeoutMs: 10_000,
  ...overrides,
});

const previewResult = (overrides = {}) => ({
  previewId: "preview-1",
  baseRevision: "rev-1",
  patch: [{ op: "replace", path: "/color", value: "#7018e6" }],
  inversePatch: [{ op: "replace", path: "/color", value: "#000000" }],
  affectedObjects: ["hero/cta"],
  preservedRules: ["layout"],
  violations: [],
  qualityReport: { status: "certified" },
  expiresAt: "2026-08-25T12:01:00.000Z",
  ...overrides,
});

const applyResult = (revision = "rev-2") => ({
  newRevision: revision,
  inverseCommand: { action: "editor.style.patch", arguments: { color: "#000000" } },
  undoEntry: { id: `undo-${revision}`, commandId: "cmd-1" },
  affectedObjects: ["hero/cta"],
  qualityReport: { status: "certified" },
});

const rejectsCode = async (promise, code) => assert.rejects(promise, (error) => {
  assert.ok(error instanceof LiveCommandContractError);
  assert.equal(error.code, code);
  return true;
});

test("registration is explicit and unsupported or missing handlers fail loudly", async () => {
  const registry = new LiveCommandRegistry();
  assert.throws(() => registry.register("shell.exec", () => ({})), (error) => error.code === "UNSUPPORTED_ACTION");
  await rejectsCode(registry.execute(makeRequest(), { currentRevision: "rev-1" }), "HANDLER_NOT_REGISTERED");
  const unregister = registry.register("quality.check", async () => previewResult());
  assert.deepEqual(registry.actionInventory(), [{ action: "quality.check", access: "preview", approval: "never" }]);
  assert.throws(() => registry.register("quality.check", async () => previewResult()), (error) => error.code === "HANDLER_ALREADY_REGISTERED");
  unregister();
  assert.deepEqual(registry.actionInventory(), []);
  assert.equal(LiveCommandBroker, LiveCommandRegistry);
});

test("preview is contract-checked, stored, bounded and never emits an apply event", async () => {
  let now = Date.parse("2026-08-25T12:00:00.000Z");
  const registry = new LiveCommandRegistry({ now: () => now, maxPreviews: 1 });
  let sequence = 0;
  registry.register("editor.style.patch", async () => previewResult({ previewId: `preview-${++sequence}` }));
  const first = await registry.execute(makeRequest(), { currentRevision: "rev-1" });
  assert.equal(first.previewId, "preview-1");
  assert.deepEqual(registry.changesSince(0).events, []);
  assert.equal(registry.getPreview("preview-1").baseRevision, "rev-1");
  await registry.execute(makeRequest({ commandId: "cmd-2", idempotencyKey: "idem-2" }), { currentRevision: "rev-1" });
  assert.equal(registry.getPreview("preview-1"), null);
  assert.equal(registry.getPreview("preview-2").previewId, "preview-2");
  registry.dispose();

  const unsafe = new LiveCommandRegistry({ now: () => now });
  unsafe.register("editor.style.patch", async () => ({ ...previewResult(), newRevision: "rev-2" }));
  await rejectsCode(unsafe.execute(makeRequest(), { currentRevision: "rev-1" }), "PREVIEW RESULT_INVALID");
});

test("an active previewId is immutable and collisions cannot overwrite it", async () => {
  const now = () => Date.parse("2026-08-25T12:00:00.000Z");
  let score = 91;
  const registry = new LiveCommandRegistry({ now });
  registry.register("editor.style.patch", async () => previewResult({ qualityReport: { status: "certified", score } }));

  const originalRequest = makeRequest();
  const original = await registry.execute(originalRequest, { currentRevision: "rev-1" });
  score = 50;
  const replay = await registry.execute(originalRequest, { currentRevision: "rev-1" });
  assert.equal(replay.qualityReport.score, 91);
  assert.equal(registry.getPreview("preview-1").qualityReport.score, 91);

  const collision = makeRequest({ commandId: "cmd-2", idempotencyKey: "idem-2" });
  await rejectsCode(registry.execute(collision, { currentRevision: "rev-1" }), "PREVIEW_ID_CONFLICT");
  assert.equal(registry.getPreview("preview-1").qualityReport.score, 91);

  const semanticCollision = makeRequest({ arguments: { color: "#ff691d" } });
  await rejectsCode(registry.execute(semanticCollision, { currentRevision: "rev-1" }), "PREVIEW_ID_CONFLICT");
  assert.equal(registry.getPreview("preview-1").qualityReport.score, 91);
});

test("an expired previewId may be replaced by a different command", async () => {
  let now = Date.parse("2026-08-25T12:00:00.000Z");
  let expiresAt = "2026-08-25T12:01:00.000Z";
  let score = 91;
  const registry = new LiveCommandRegistry({ now: () => now });
  registry.register("editor.style.patch", async () => previewResult({ expiresAt, qualityReport: { score } }));
  await registry.execute(makeRequest(), { currentRevision: "rev-1" });

  now = Date.parse("2026-08-25T12:02:00.000Z");
  expiresAt = "2026-08-25T12:03:00.000Z";
  score = 75;
  const replacement = await registry.execute(
    makeRequest({ commandId: "cmd-2", idempotencyKey: "idem-2", baseRevision: "rev-2" }),
    { currentRevision: "rev-2" },
  );
  assert.equal(replacement.previewId, "preview-1");
  assert.equal(registry.getPreview("preview-1").qualityReport.score, 75);
});

test("apply is approved, runs exactly once, replays idempotently and emits one event", async () => {
  let handlerCalls = 0;
  let approvals = 0;
  const registry = new LiveCommandRegistry({
    now: () => Date.parse("2026-08-25T12:00:00.000Z"),
    approve: async ({ request, access }) => {
      approvals += 1;
      assert.equal(request.mode, "apply");
      assert.equal(access, "mutation");
      return true;
    },
  });
  registry.register("editor.style.patch", async () => {
    handlerCalls += 1;
    return applyResult();
  });
  const command = makeRequest({ mode: "apply" });
  const first = await registry.execute(command, { currentRevision: "rev-1" });
  first.newRevision = "tampered";
  // Replay succeeds despite the now-advanced revision because the first apply
  // was already committed; it does not run approval or mutation twice.
  const replay = await registry.execute(command, { currentRevision: "rev-2" });
  assert.equal(replay.newRevision, "rev-2");
  assert.equal(handlerCalls, 1);
  assert.equal(approvals, 1);
  const changes = registry.changesSince(0);
  assert.equal(changes.events.length, 1);
  assert.equal(changes.events[0].cursor, 1);
  assert.equal(changes.events[0].newRevision, "rev-2");
});

test("concurrent identical applies share one in-flight execution", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let calls = 0;
  const registry = new LiveCommandRegistry({ approve: async () => true });
  registry.register("editor.style.patch", async () => {
    calls += 1;
    await gate;
    return applyResult();
  });
  const command = makeRequest({ mode: "apply" });
  const first = registry.execute(command, { currentRevision: "rev-1" });
  const second = registry.execute(command, { currentRevision: "rev-1" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 1);
  release();
  assert.deepEqual(await first, await second);
  assert.equal(registry.changesSince(0).events.length, 1);
});

test("stale revision and approval decline happen before handler execution", async () => {
  let calls = 0;
  const stale = new LiveCommandRegistry({ approve: async () => true });
  stale.register("editor.style.patch", async () => { calls += 1; return applyResult(); });
  await rejectsCode(stale.execute(makeRequest({ mode: "apply" }), { currentRevision: "rev-other" }), "STALE_REVISION");
  assert.equal(calls, 0);

  const declined = new LiveCommandRegistry({ approve: async () => false });
  declined.register("editor.style.patch", async () => { calls += 1; return applyResult(); });
  await rejectsCode(declined.execute(makeRequest({ mode: "apply" }), { currentRevision: "rev-1" }), "APPROVAL_DECLINED");
  assert.equal(calls, 0);
});

test("paid/network previews invoke approval and a missing approver fails closed", async () => {
  let approvals = 0;
  const now = () => Date.parse("2026-08-25T12:00:00.000Z");
  const registry = new LiveCommandRegistry({ now, approve: async () => { approvals += 1; return true; } });
  registry.register("generate.run", async () => previewResult());
  await registry.execute(makeRequest({ action: "generate.run" }), {
    currentRevision: "rev-1",
    approvalContext: { paidModel: true },
  });
  assert.equal(approvals, 1);

  const closed = new LiveCommandRegistry({ now });
  closed.register("source.capture", async () => previewResult());
  await rejectsCode(closed.execute(makeRequest({ action: "source.capture" }), { currentRevision: "rev-1" }), "APPROVAL_REQUIRED");
});

test("same idempotency key with a different semantic fingerprint is rejected", async () => {
  const registry = new LiveCommandRegistry({ approve: async () => true });
  registry.register("editor.style.patch", async () => applyResult());
  await registry.execute(makeRequest({ mode: "apply" }), { currentRevision: "rev-1" });
  await rejectsCode(registry.execute(makeRequest({ mode: "apply", arguments: { color: "#ff691d" } }), {
    currentRevision: "rev-2",
  }), "IDEMPOTENCY_CONFLICT");
});

test("expired previews are rejected at creation and evicted during cleanup", async () => {
  let now = Date.parse("2026-08-25T12:00:00.000Z");
  const registry = new LiveCommandRegistry({ now: () => now });
  registry.register("quality.check", async () => previewResult());
  const qualityRequest = makeRequest({ action: "quality.check" });
  delete qualityRequest.baseRevision;
  await registry.execute(qualityRequest);
  now = Date.parse("2026-08-25T12:02:00.000Z");
  assert.deepEqual(registry.cleanup(), { removedPreviews: 1 });
  assert.equal(registry.getPreview("preview-1"), null);

  const expired = new LiveCommandRegistry({ now: () => now });
  expired.register("quality.check", async () => previewResult());
  await rejectsCode(expired.execute(qualityRequest), "PREVIEW_EXPIRED");
});

test("event log has monotonic cursors, bounded history and truncation signal", async () => {
  const registry = new LiveCommandRegistry({ approve: async () => true, maxEvents: 2 });
  let revision = 1;
  registry.register("editor.style.patch", async () => applyResult(`rev-${++revision}`));
  for (let index = 1; index <= 3; index += 1) {
    await registry.execute(makeRequest({
      commandId: `cmd-${index}`,
      idempotencyKey: `idem-${index}`,
      baseRevision: `rev-${index}`,
      mode: "apply",
    }), { currentRevision: `rev-${index}` });
  }
  const allAvailable = registry.changesSince(0);
  assert.deepEqual(allAvailable.events.map((event) => event.cursor), [2, 3]);
  assert.equal(allAvailable.latestCursor, 3);
  assert.equal(allAvailable.truncated, true);
  assert.deepEqual(registry.changesSince(2).events.map((event) => event.cursor), [3]);
  assert.throws(() => registry.changesSince(-1), (error) => error.code === "CURSOR_INVALID");
});

test("subscribers receive one isolated apply event, never an idempotent replay", async () => {
  const registry = new LiveCommandRegistry({ approve: async () => true });
  registry.register("editor.style.patch", async () => applyResult());
  const received = [];
  registry.subscribe(() => { throw new Error("observer failure"); });
  registry.subscribe(async () => { throw new Error("async observer failure"); });
  const unsubscribe = registry.subscribe((event) => {
    event.action = "tampered-by-listener";
    received.push(event);
  });
  const command = makeRequest({ mode: "apply" });
  const applied = await registry.execute(command, { currentRevision: "rev-1" });
  assert.equal(applied.newRevision, "rev-2");
  await registry.execute(command, { currentRevision: "rev-2" });
  assert.equal(received.length, 1);
  assert.equal(registry.changesSince(0).events[0].action, "editor.style.patch");

  unsubscribe();
  await registry.execute(makeRequest({
    commandId: "cmd-2",
    idempotencyKey: "idem-2",
    baseRevision: "rev-2",
    mode: "apply",
  }), { currentRevision: "rev-2" });
  assert.equal(received.length, 1);
});

test("job cancellation hook runs once and cleanup/dispose are safe", async () => {
  const registry = new LiveCommandRegistry();
  registry.subscribe(() => {});
  assert.equal(registry.subscribers.size, 1);
  const reasons = [];
  registry.registerJob("job-1", async (reason) => { reasons.push(reason); });
  assert.deepEqual(await registry.cancelJob("job-1", "user-request"), { jobId: "job-1", cancelled: true });
  assert.deepEqual(reasons, ["user-request"]);
  await rejectsCode(registry.cancelJob("job-1"), "JOB_NOT_FOUND");
  registry.dispose();
  assert.equal(registry.subscribers.size, 0);
  registry.dispose();
  assert.throws(() => registry.actionInventory(), (error) => error.code === "REGISTRY_DISPOSED");
});
