import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { LlmTrace, MAX_TRACE_BYTES, TRACE_FILE_NAME, messageChars, traceRecord } from "../services/llm-trace.mjs";

function scratch(t) {
  const dir = mkdtempSync(path.join(tmpdir(), "ddna-trace-"));
  t.after(() => { try { rmSync(dir, { recursive: true, force: true }); } catch { /* best effort */ } });
  return dir;
}

test("a trace record keeps metadata only and never the prompt or the answer", () => {
  const envelope = {
    id: "req-1", provider: "claude", model: "opus", system: "SECRET SYSTEM PROMPT",
    reasoning: { effort: "high" },
    messages: [{ role: "user", content: "SECRET USER TEXT" }, { role: "user", content: [{ type: "text", text: "12345" }, { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } }] }],
  };
  const result = { content: '{"approved":true}', provider: "claude",
    transport: { provider: "claude", model: "opus", contractVersion: "agent-contract/1.0", structuredOutput: true,
      dropped: [{ field: "temperature", reason: "x" }], instructionSources: ["a", "b"], threadId: "t1", turnId: "u1" } };
  const record = traceRecord({ envelope, profile: "quality_judge", result, durationMs: 1234.6, queuedMs: 12 });
  assert.equal(record.source, "electron");
  assert.equal(record.requestId, "req-1");
  assert.equal(record.profile, "quality_judge");
  assert.equal(record.provider, "claude");
  assert.equal(record.model, "opus");
  assert.equal(record.effort, "high");
  assert.equal(record.contractVersion, "agent-contract/1.0");
  assert.equal(record.structuredOutput, true);
  assert.deepEqual(record.dropped, ["temperature"]);
  assert.equal(record.durationMs, 1235);
  assert.equal(record.queuedMs, 12);
  assert.equal(record.ok, true);
  assert.equal(record.error, null);
  assert.equal(record.promptChars, "SECRET SYSTEM PROMPT".length + "SECRET USER TEXT".length + 5);
  assert.equal(record.outputChars, 17);
  assert.equal(record.instructionSources, 2);
  assert.equal(record.threadId, "t1");
  const serialized = JSON.stringify(record);
  assert.doesNotMatch(serialized, /SECRET/);
  assert.doesNotMatch(serialized, /approved/);
  assert.doesNotMatch(serialized, /base64/);
  assert.equal(messageChars([{ role: "user", content: null }]), 0);
});

test("errors and cancellations are recorded with the failure, not the payload", () => {
  const record = traceRecord({ envelope: { id: "req-2", provider: "codex", messages: [] }, profile: "generator",
    error: new Error("Codex request cancelled"), durationMs: 5, cancelled: true });
  assert.equal(record.ok, false);
  assert.equal(record.cancelled, true);
  assert.equal(record.error, "Codex request cancelled");
  assert.equal(record.provider, "codex");
  assert.equal(record.outputChars, 0);
});

test("writes JSON lines into <data>/traces and rotates the file at the size cap", (t) => {
  const dir = path.join(scratch(t), "data", "traces");
  const trace = new LlmTrace({ directory: dir, maxBytes: 200 });
  assert.equal(trace.write({ ts: "2026-09-09T00:00:00Z", ok: true }), true);
  const file = path.join(dir, TRACE_FILE_NAME);
  assert.ok(existsSync(file));
  assert.equal(readFileSync(file, "utf8").trim().split("\n").length, 1);
  writeFileSync(file, "x".repeat(250));
  assert.equal(trace.write({ ts: "2026-09-09T00:00:01Z", ok: false }), true);
  assert.ok(existsSync(`${file}.1`), "the oversized file is rotated aside");
  assert.equal(readFileSync(file, "utf8").trim().split("\n").length, 1);
  assert.ok(MAX_TRACE_BYTES > 1024 * 1024);
});

test("a failing writer never throws into the provider call", (t) => {
  const errors = [];
  const trace = new LlmTrace({ directory: path.join(scratch(t), "traces"),
    appendFile: () => { throw new Error("disk full"); }, onError: (error) => errors.push(error.message) });
  assert.equal(trace.write({ ok: true }), false);
  assert.deepEqual(errors, ["disk full"]);
});
