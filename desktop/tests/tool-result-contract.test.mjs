import assert from "node:assert/strict";
import test from "node:test";
import { serializeToolResult, MAX_TOOL_RESULT_BYTES } from "../../frontend/src/desktop/tool-result.ts";
import { createEnvelope } from "../services/provider-envelope.mjs";

test("tool results serialize verbatim under the byte limit", () => {
  const result = { content: [{ type: "text", text: "ok" }], isError: false };
  const out = serializeToolResult(result);
  assert.equal(out.oversize, false);
  assert.equal(out.text, JSON.stringify(result));
});

test("oversize tool results become an explicit structured marker — never sliced JSON", () => {
  const big = { data: "€".repeat(6_000) }; // ~18 КБ в UTF-8
  const out = serializeToolResult(big);
  assert.equal(out.oversize, true);
  assert.equal(out.code, "TOOL_RESULT_OVERSIZE");
  const marker = JSON.parse(out.text); // маркер — валидный JSON, не обрезанные байты
  assert.equal(marker.error.code, "TOOL_RESULT_OVERSIZE");
  assert.ok(marker.error.bytes > MAX_TOOL_RESULT_BYTES);
  assert.equal(marker.error.limit, MAX_TOOL_RESULT_BYTES);
  assert.ok(out.text.length < 1_000);
});

test("unserializable tool results become a structured marker instead of throwing", () => {
  const cyclic = { a: 1 };
  cyclic.self = cyclic;
  const out = serializeToolResult(cyclic);
  assert.equal(out.code, "TOOL_RESULT_UNSERIALIZABLE");
  assert.equal(JSON.parse(out.text).error.code, "TOOL_RESULT_UNSERIALIZABLE");
  const bigint = serializeToolResult({ n: 1n });
  assert.equal(bigint.code, "TOOL_RESULT_UNSERIALIZABLE");
});

test("round two: the oversize marker survives history resubmission byte-exact", () => {
  const big = { data: "x".repeat(20_000) };
  const marker = serializeToolResult(big).text;
  const envelope = createEnvelope({
    provider: "openai",
    messages: [
      { role: "user", content: "run" },
      { role: "assistant", content: "", toolCalls: [{ id: "c1", name: "f", arguments: "{}" }] },
      { role: "tool", content: marker, toolCallId: "c1", toolName: "f" },
    ],
  });
  const tool = envelope.messages.find((m) => m.role === "tool");
  assert.equal(tool.content.length, 1);
  assert.equal(tool.content[0].type, "text");
  assert.equal(tool.content[0].text, marker); // ничего не усечено на любом хопе
});

test("AgentWorkspace sends qualifiedName and description verbatim (no replace/slice)", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../../frontend/src/desktop/AgentWorkspace.svelte", import.meta.url), "utf-8");
  assert.ok(!source.includes(".slice(0, 500)"), "description slice must be gone");
  assert.ok(!source.includes(".slice(0, 64)"), "qualifiedName slice must be gone");
  assert.ok(!source.includes("replace(/[^A-Za-z0-9_-]/g"), "qualifiedName rewrite must be gone");
  assert.ok(source.includes("String(tool.qualifiedName || tool.name || \"\")"), "qualifiedName must pass verbatim");
});

test("AgentWorkspace cancel cannot clear a newer request or switch model or effort mid-round", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../../frontend/src/desktop/AgentWorkspace.svelte", import.meta.url), "utf-8");
  assert.ok(source.includes('const selectedModel = agentModel;'), "each request must pin the selected model");
  assert.ok(source.includes("const selectedEffort = agentEffort;"), "each tool loop must pin its reasoning effort");
  assert.ok(source.includes("reasoning: { effort: selectedEffort }"), "every round must reuse the pinned effort");
  assert.ok(source.includes("if (activeCorrelationId === correlationId) activeCorrelationId = null;"), "an old finally block must not clear a newer request");
  assert.ok(source.includes("disabled={busy || agentRunning}"), "provider/session controls must lock during an active loop");
});

test("AgentWorkspace keeps every provider and connection control inside the desktop sidebar", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../../frontend/src/desktop/agent-workspace.css", import.meta.url), "utf-8");
  assert.match(css, /\.agent-sidebar\s*\{[^}]*overflow-x:\s*hidden/s, "the sidebar must never hide controls behind horizontal scrolling");
  assert.match(css, /\.agent-backend\s*\{[^}]*grid-template-columns:\s*repeat\([23],\s*minmax\(0,\s*1fr\)\)/s, "provider controls must wrap into a bounded grid");
  assert.match(css, /\.agent-connections\s*\{[^}]*display:\s*grid/s, "connection fields must use a one-dimensional form layout");
  assert.match(css, /\.agent-connections input,[\s\S]*?width:\s*100%/s, "credential inputs must stay within the sidebar width");
  assert.match(css, /@media \(max-width:\s*900px\)[\s\S]*?\.agent-sidebar\s*\{[^}]*display:\s*flex/s, "small desktop windows must keep the agent settings reachable");
});
