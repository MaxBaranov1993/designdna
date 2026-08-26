import assert from "node:assert/strict";
import test from "node:test";
import {
  LIVE_COMMAND_LIMITS,
  LiveCommandContractError,
  assertBaseRevision,
  classifyActionAccess,
  commandError,
  createLiveCommandRequest,
  idempotencyFingerprint,
  requiresApproval,
  validateApplyResult,
  validatePreviewResult,
} from "../services/live-command-contract.mjs";

const request = (overrides = {}) => ({
  commandId: "cmd-1",
  idempotencyKey: "idem-1",
  projectId: "project-1",
  pageId: "page-1",
  baseRevision: "rev-1",
  intent: "Change the selected CTA color",
  scope: { nodeIds: ["12"], sourceKeys: ["hero/cta"], viewports: ["desktop", "mobile"] },
  action: "editor.style.patch",
  arguments: { color: "#7018e6", nested: { enabled: true } },
  mode: "preview",
  correlationId: "trace-1",
  timeoutMs: 10_000,
  ...overrides,
});

const hasIssue = (field, code) => (error) => error instanceof LiveCommandContractError
  && error.issues.some((item) => item.field === field && (!code || item.code === code));

test("normalizes a typed mutation request without losing scope", () => {
  const normalized = createLiveCommandRequest(request());
  assert.deepEqual(normalized.scope, {
    nodeIds: ["12"],
    sourceKeys: ["hero/cta"],
    viewports: ["desktop", "mobile"],
  });
  assert.equal(normalized.action, "editor.style.patch");
  assert.equal(normalized.baseRevision, "rev-1");
});

test("read and pure-preview actions use preview mode without a base revision", () => {
  const readInput = request({ action: "project.get", mode: "preview", arguments: {} });
  delete readInput.baseRevision;
  const read = createLiveCommandRequest(readInput);
  assert.equal(read.baseRevision, null);
  const qualityInput = request({ action: "quality.check", mode: "preview" });
  delete qualityInput.baseRevision;
  const quality = createLiveCommandRequest(qualityInput);
  assert.equal(quality.baseRevision, null);
  assert.throws(() => createLiveCommandRequest(request({ action: "project.get", mode: "apply" })), hasIssue("mode", "INVALID_MODE"));
});

test("mutation and apply requests fail closed without baseRevision", () => {
  assert.throws(
    () => createLiveCommandRequest(request({ baseRevision: undefined })),
    hasIssue("baseRevision", "INVALID_ID"),
  );
  assert.throws(
    () => createLiveCommandRequest(request({ action: "quality.check", mode: "apply", baseRevision: undefined })),
    hasIssue("baseRevision", "INVALID_ID"),
  );
});

test("CAS guard reports stale revision as a retryable standardized error", () => {
  assert.equal(assertBaseRevision(request(), "rev-1").baseRevision, "rev-1");
  assert.throws(() => assertBaseRevision(request(), "rev-2"), (error) => {
    assert.equal(error.code, "STALE_REVISION");
    assert.equal(error.retryable, true);
    assert.equal(error.toJSON().error.retryable, true);
    return true;
  });
  assert.deepEqual(commandError("NOPE", "Nope").ok, false);
});

test("CAS guard rejects an invalid current revision before stale comparison", () => {
  for (const currentRevision of [undefined, null, "", "bad revision", "x".repeat(LIVE_COMMAND_LIMITS.maxIdBytes + 1)]) {
    assert.throws(() => assertBaseRevision(request(), currentRevision), (error) => {
      assert.equal(error.code, "REVISION_INVALID");
      assert.equal(error.retryable, false);
      assert.ok(error.issues.some((item) => item.field === "currentRevision"));
      return true;
    });
  }
});

test("idempotency fingerprint is canonical and excludes transport IDs", () => {
  const first = request({ arguments: { z: 1, nested: { b: 2, a: 1 } } });
  const second = request({
    commandId: "cmd-2",
    idempotencyKey: "idem-2",
    correlationId: "trace-2",
    timeoutMs: 20_000,
    arguments: { nested: { a: 1, b: 2 }, z: 1 },
  });
  assert.equal(idempotencyFingerprint(first), idempotencyFingerprint(second));
  assert.notEqual(idempotencyFingerprint(first), idempotencyFingerprint(request({ arguments: { z: 2, nested: { a: 1, b: 2 } } })));
});

test("unknown fields, unsupported actions/viewports and duplicate scope are rejected", () => {
  assert.throws(() => createLiveCommandRequest({ ...request(), ignored: true }), hasIssue("ignored", "UNKNOWN_FIELD"));
  assert.throws(() => createLiveCommandRequest(request({ action: "shell.exec" })), hasIssue("action", "UNSUPPORTED_ACTION"));
  assert.throws(() => createLiveCommandRequest(request({ scope: { nodeIds: [], sourceKeys: [], viewports: ["watch"] } })), hasIssue("scope.viewports[0]", "UNSUPPORTED_VIEWPORT"));
  assert.throws(() => createLiveCommandRequest(request({ scope: { nodeIds: ["12", "12"] } })), hasIssue("scope.nodeIds", "DUPLICATE"));
  assert.throws(() => createLiveCommandRequest(request({ commandId: "bad id" })), hasIssue("commandId", "INVALID_ID"));
});

test("prototype-pollution keys and non-plain/cyclic arguments are rejected", () => {
  assert.throws(
    () => createLiveCommandRequest(request({ arguments: JSON.parse('{"__proto__":{"polluted":true}}') })),
    hasIssue("$.arguments.__proto__", "PROTOTYPE_POLLUTION"),
  );
  assert.throws(
    () => createLiveCommandRequest(request({ arguments: { constructor: { prototype: { polluted: true } } } })),
    hasIssue("$.arguments.constructor", "PROTOTYPE_POLLUTION"),
  );
  assert.throws(() => createLiveCommandRequest(request({ arguments: { when: new Date() } })), hasIssue("$.arguments.when", "NON_PLAIN_OBJECT"));
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => createLiveCommandRequest(request({ arguments: cyclic })), hasIssue("$.arguments.self", "CYCLIC_VALUE"));
  assert.equal({}.polluted, undefined);
});

test("UTF-8 byte and collection limits are loud and never clip accepted data", () => {
  const accepted = "я".repeat((LIVE_COMMAND_LIMITS.maxArgumentsBytes / 2) - 128);
  const normalized = createLiveCommandRequest(request({ arguments: { text: accepted } }));
  assert.equal(normalized.arguments.text, accepted);
  assert.throws(
    () => createLiveCommandRequest(request({ arguments: { text: "я".repeat(LIVE_COMMAND_LIMITS.maxArgumentsBytes) } })),
    hasIssue("arguments", "SIZE_LIMIT"),
  );
  assert.throws(
    () => createLiveCommandRequest(request({ scope: { nodeIds: Array.from({ length: LIVE_COMMAND_LIMITS.maxScopeEntries + 1 }, (_, i) => `n-${i}`) } })),
    hasIssue("scope.nodeIds", "COUNT_LIMIT"),
  );
});

test("access and approval classification is explicit", () => {
  assert.equal(classifyActionAccess("project.get"), "read");
  assert.equal(classifyActionAccess("quality.check"), "preview");
  assert.equal(classifyActionAccess("editor.style.patch"), "mutation");
  assert.equal(requiresApproval(request({ action: "project.get" })), false);
  assert.equal(requiresApproval(request({ mode: "preview" })), false);
  assert.equal(requiresApproval(request({ mode: "apply" })), true);
  assert.equal(requiresApproval(request({ action: "graph.node.delete", mode: "preview" })), true);
  assert.equal(requiresApproval(request({ action: "generate.run", mode: "preview" }), { paidModel: true }), true);
  assert.equal(requiresApproval(request({ action: "export.start", mode: "preview" }), { externalPath: true }), true);
});

test("preview result is complete and cannot masquerade as a canonical apply", () => {
  const preview = {
    previewId: "preview-1",
    baseRevision: "rev-1",
    patch: [{ op: "replace", path: "/tree/0/color", value: "#7018e6" }],
    inversePatch: [{ op: "replace", path: "/tree/0/color", value: "#000000" }],
    affectedObjects: ["hero/cta"],
    preservedRules: ["layout"],
    violations: [],
    qualityReport: { status: "certified", score: 91 },
    expiresAt: "2026-08-25T12:00:00.000Z",
  };
  assert.equal(validatePreviewResult(preview), preview);
  assert.throws(() => validatePreviewResult({ ...preview, newRevision: "rev-2" }), hasIssue("newRevision", "UNKNOWN_FIELD"));
  assert.throws(() => validatePreviewResult({ ...preview, expiresAt: "2026" }), hasIssue("expiresAt", "INVALID_TIMESTAMP"));
  assert.throws(() => validatePreviewResult({ ...preview, expiresAt: "2026-08-25T12:00:00Z" }), hasIssue("expiresAt", "INVALID_TIMESTAMP"));
  const { inversePatch, ...missingInverse } = preview;
  assert.throws(() => validatePreviewResult(missingInverse), hasIssue("inversePatch", "INVALID_TYPE"));
});

test("apply result requires a revision, inverse command and undo entry", () => {
  const apply = {
    newRevision: "rev-2",
    inverseCommand: { action: "editor.style.patch", arguments: { color: "#000000" } },
    undoEntry: { id: "undo-1", commandId: "cmd-1" },
    affectedObjects: ["hero/cta"],
    qualityReport: { status: "certified" },
  };
  assert.equal(validateApplyResult(apply), apply);
  assert.throws(() => validateApplyResult({ ...apply, newRevision: undefined }), hasIssue("newRevision", "INVALID_ID"));
  assert.throws(() => validateApplyResult({ ...apply, inverseCommand: null }), hasIssue("inverseCommand", "INVALID_TYPE"));
  assert.throws(() => validateApplyResult({ ...apply, previewId: "preview-1" }), hasIssue("previewId", "UNKNOWN_FIELD"));
});
