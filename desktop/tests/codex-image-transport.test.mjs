import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { CodexAppServer } from "../services/codex-app-server.mjs";
import { chatWithProvider, prepareProviderRequest } from "../services/provider-router.mjs";

const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==";
const image = (url = `data:image/png;base64,${PNG}`) => ({ type: "image_url", image_url: { url, detail: "high" } });
const messages = [{ role: "system", content: "Сохрани Source DS tokens" }, { role: "user", content: [
  { type: "text", text: "Before screenshot" }, image(),
  { type: "text", text: "After screenshot — compare" }, image(),
  { type: "text", text: "Final instruction\nKeep layout" },
] }];
const fixture = fileURLToPath(new URL("./fixtures/codex-image-server.mjs", import.meta.url));

function harness(t, mode = "success") {
  const root = mkdtempSync(path.join(tmpdir(), "ddna-codex-test-"));
  const notifications = [];
  let child;
  const server = new CodexAppServer({ imageTempRoot: root, timeoutMs: 2_000,
    spawnProcess: (_command, _args, options) => {
      child = spawn(process.execPath, [fixture, mode], { ...options, cwd: process.cwd() });
      return child;
    },
  });
  server.on("notification", (event) => notifications.push(event));
  t.after(async () => {
    const exited = child && child.exitCode === null ? once(child, "exit") : null;
    server.stop();
    if (exited) await exited;
    rmSync(root, { recursive: true, force: true });
  });
  return { root, server, notifications };
}

function clean(h) {
  assert.deepEqual(readdirSync(h.root), [], "all request image directories must be removed");
  assert.equal(h.server.listenerCount("serverError"), 0);
  assert.equal(h.server.listenerCount("notification"), 1, "only the fixture observer should remain");
}

test("Source DS visual QA sends actual image bytes through envelope, router and JSONL localImage input", async (t) => {
  const h = harness(t);
  const prepared = prepareProviderRequest({ provider: "codex", model: "gpt-5.6-sol",
    system: "Envelope system contract", messages, reasoning: { effort: "high" } }, "source-ds-qa");
  const result = await chatWithProvider({ ...prepared, codex: h.server, profile: "quality_judge",
    credentials: { has: () => { throw new Error("API credentials must not be read"); } },
    openaiChat: () => { throw new Error("API fallback must not run"); },
  });
  assert.equal(result.content, '{"score":92}');
  assert.equal(result.transport.provider, "codex");
  assert.equal(result.transport.model, "gpt-5.6-sol");
  assert.equal(result.transport.modelProvider, "openai");
  assert.equal(result.transport.authType, "chatgpt");
  assert.equal(result.transport.modelSource, "thread/start");
  assert.equal(result.transport.turnId, `turn-${result.transport.threadId}`);
  assert.equal(result.transport.requestId, "source-ds-qa");
  assert.equal(result.transport.fallback, null);
  const thread = h.notifications.find((e) => e.method === "fixture/thread").params;
  assert.equal(thread.modelProvider, "openai");
  assert.equal(thread.model, "gpt-5.6-sol");
  assert.deepEqual(h.notifications.find((e) => e.method === "fixture/account").params, { refreshToken: false });
  assert.equal(thread.ephemeral, true);
  assert.equal(thread.sandbox, "read-only");
  assert.equal(thread.approvalPolicy, "never");
  const wire = h.notifications.find((e) => e.method === "fixture/input").params;
  assert.equal(wire.model, "gpt-5.6-sol");
  assert.equal(wire.effort, "high");
  assert.deepEqual(wire.input.map((part) => part.type), ["text", "localImage", "text", "localImage", "text"]);
  // Герметичный контракт: инструкции профиля и system-сообщения конверта —
  // developerInstructions треда; в input остаётся только переписка.
  assert.match(thread.developerInstructions, /Evaluate the supplied Design IR/);
  assert.match(thread.developerInstructions, /Envelope system contract\n\nСохрани Source DS tokens/);
  assert.equal(thread.config.project_doc_max_bytes, 0);
  assert.deepEqual(thread.config.mcp_servers, {});
  assert.doesNotMatch(wire.input[0].text, /SYSTEM:|Evaluate the supplied Design IR/);
  assert.match(wire.input[0].text, /^USER:\nBefore screenshot/);
  assert.equal(wire.input[2].text, "\nAfter screenshot — compare\n");
  assert.equal(wire.input[4].text, "\nFinal instruction\nKeep layout");
  for (const part of wire.input.filter((item) => item.type === "localImage")) {
    assert.equal(part.base64, PNG, "fixture must read the exact image content from the transported path");
    assert.equal(part.detail, "high");
    assert.ok(path.isAbsolute(part.path));
    assert.ok(part.path.startsWith(`${h.root}${path.sep}`));
    assert.equal(existsSync(part.path), false);
  }
  clean(h);
});

test("HTTPS evidence uses native image input and no temporary files", async (t) => {
  const h = harness(t);
  await h.server.chat([{ role: "user", content: [image("https://example.test/source.png")] }]);
  const wire = h.notifications.find((e) => e.method === "fixture/input").params;
  assert.deepEqual(wire.input[1], { type: "image", url: "https://example.test/source.png", detail: "high" });
  clean(h);
});

for (const [mode, expectedModel, modelSource] of [
  ["success", "fixture-resolved-model", "thread/start"],
  ["reroute", "fixture-rerouted-model", "model/rerouted"],
]) {
  test(`router reports the server model with no client model override (${mode})`, async (t) => {
    const h = harness(t, mode);
    const result = await chatWithProvider({ provider: "codex", messages, codex: h.server });
    assert.equal(result.transport.model, expectedModel);
    assert.equal(result.transport.modelSource, modelSource);
    assert.equal(result.transport.modelProvider, "openai");
    assert.equal(result.transport.authType, "chatgpt");
    assert.equal(result.transport.fallback, null);
    clean(h);
  });
}

for (const mode of ["logged-out", "api-key", "bedrock"]) {
  test(`subscription route rejects ${mode} without thread creation or fallback`, async (t) => {
    const h = harness(t, mode);
    let fallbackCalls = 0;
    await assert.rejects(chatWithProvider({ provider: "codex", messages, codex: h.server,
      openaiChat: () => { fallbackCalls++; return "wrong"; },
    }), /existing ChatGPT login/);
    assert.equal(fallbackCalls, 0);
    assert.equal(h.notifications.some((event) => event.method === "fixture/thread" || event.method === "fixture/input"), false);
    clean(h);
  });
}

for (const mode of ["provider-mismatch", "thread-provider-mismatch", "missing-model"]) {
  test(`thread response ${mode} fails before visual evidence is sent`, async (t) => {
    const h = harness(t, mode);
    await assert.rejects(h.server.chat(messages), /refusing to send the turn/);
    assert.equal(h.notifications.some((event) => event.method === "fixture/input"), false);
    clean(h);
  });
}

test("metadata is scoped to each concurrent request while chat still returns strings", async (t) => {
  const h = harness(t);
  const metadata = [];
  const outputs = await Promise.all(["fixture-model-a", "fixture-model-b"].map((model, index) =>
    h.server.chat(messages, { model, onResponseMetadata: (value) => { metadata[index] = value; } })));
  assert.deepEqual(outputs, ['{"score":92}', '{"score":92}']);
  assert.deepEqual(metadata.map((item) => item.model), ["fixture-model-a", "fixture-model-b"]);
  assert.notEqual(metadata[0].threadId, metadata[1].threadId);
  assert.ok(metadata.every(Object.isFrozen));
  clean(h);
});

test("explicit JSON Schema reaches Codex turn/start verbatim without changing the selected model", async (t) => {
  const h = harness(t);
  const schema = { type: "object", properties: { score: { type: "number" } }, required: ["score"], additionalProperties: false };
  const prepared = prepareProviderRequest({ provider: "codex", model: "gpt-5.6-luna", messages,
    responseFormat: { type: "json_schema", jsonSchema: { name: "exact_review", schema } },
  }, "schema-review");
  const result = await chatWithProvider({ ...prepared, codex: h.server });
  const wire = h.notifications.find((event) => event.method === "fixture/input").params;
  assert.deepEqual(wire.outputSchema, schema);
  assert.equal(wire.model, "gpt-5.6-luna");
  assert.equal(result.transport.model, "gpt-5.6-luna");
  assert.equal(result.transport.completion.outputSchemaRequested, true);
  clean(h);
});

for (const mode of ["completion-split-valid", "completion-malformed", "completion-disagrees", "completion-early-turn"]) {
  test(`completion evidence preserves the exact response (${mode})`, async (t) => {
    const h = harness(t, mode);
    const result = await chatWithProvider({ provider: "codex", messages, codex: h.server });
    const valid = JSON.stringify({ siteBrief: { summary: "Я".repeat(3800) }, styleGuide: { tone: "precise" } });
    assert.equal(result.content, mode === "completion-split-valid" ? valid : valid.slice(0, -1));
    if (mode !== "completion-split-valid") assert.throws(() => JSON.parse(result.content));
    else assert.doesNotThrow(() => JSON.parse(result.content));
    const evidence = result.transport.completion;
    assert.equal(evidence.outputChars, result.content.length);
    assert.equal(evidence.source, mode === "completion-early-turn" ? "deltas" : "item/completed");
    assert.equal(evidence.itemDeltaMatchesCompleted,
      mode === "completion-early-turn" ? null : mode !== "completion-disagrees");
    assert.equal(evidence.outputSchemaRequested, false);
    clean(h);
  });
}

for (const [mode, pattern] of [
  ["init-error", /initialize failed/], ["thread-error", /thread failed/],
  ["missing-thread", /thread id/], ["turn-error", /turn rejected/],
  ["failed", /vision failed/], ["interrupted", /interrupted/],
  ["empty", /empty response/], ["crash", /exited/],
]) {
  test(`image cleanup after ${mode}`, async (t) => {
    const h = harness(t, mode);
    await assert.rejects(h.server.chat(messages, { timeoutMs: 3_000 }), pattern);
    clean(h);
  });
}

for (const mode of ["hold", "late-ack", "thread-hold"]) {
  test(`cancellation cleans images and stops the request (${mode})`, async (t) => {
    const h = harness(t, mode);
    const controller = new AbortController();
    let interruptSeen;
    const interrupted = new Promise((resolve) => { interruptSeen = resolve; });
    const watch = ({ method, params }) => {
      if (method === (mode === "thread-hold" ? "fixture/thread" : "fixture/input")) controller.abort();
      if (method === "fixture/interrupt") interruptSeen(params);
    };
    h.server.on("notification", watch);
    await assert.rejects(h.server.chat(messages, { signal: controller.signal }), /cancelled/);
    if (mode !== "thread-hold") {
      const params = await interrupted;
      assert.equal(params.turnId, `turn-${params.threadId}`);
    }
    h.server.removeListener("notification", watch);
    clean(h);
  });
}

test("turn timeout removes image files and interrupts the active turn", async (t) => {
  const h = harness(t, "hold");
  await h.server.start();
  const interrupted = new Promise((resolve) => h.server.on("notification", function watch(event) {
    if (event.method === "fixture/interrupt") { h.server.removeListener("notification", watch); resolve(); }
  }));
  await assert.rejects(h.server.chat(messages, { timeoutMs: 150 }), /timed out/);
  await interrupted;
  clean(h);
});

test("pre-cancelled request creates no image files and never starts a process", async (t) => {
  const h = harness(t);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(h.server.chat(messages, { signal: controller.signal }), /cancelled/);
  assert.equal(h.server.sequence, 0);
  clean(h);
});

test("server stop cleans images while a turn is pending", async (t) => {
  const h = harness(t, "hold");
  const stopOnInput = ({ method }) => {
    if (method === "fixture/input") h.server.stop();
  };
  h.server.on("notification", stopOnInput);
  await assert.rejects(h.server.chat(messages), /stopped/);
  h.server.removeListener("notification", stopOnInput);
  clean(h);
});

test("initialization cancellation releases images without starting a thread", async (t) => {
  const h = harness(t);
  const controller = new AbortController();
  let release;
  h.server.start = () => new Promise((resolve) => { release = resolve; });
  const pending = h.server.chat(messages, { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, /cancelled/);
  release();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.server.sequence, 0);
  clean(h);
});

test("thread creation timeout releases images and never starts a turn", async (t) => {
  const h = harness(t, "thread-hold");
  await h.server.start();
  await assert.rejects(h.server.chat(messages, { timeoutMs: 100 }), /timed out/);
  assert.equal(h.notifications.some((event) => event.method === "fixture/input"), false);
  clean(h);
});

test("image count and total byte limits reject with cleanup before transport", async (t) => {
  const h = harness(t);
  const largePng = Buffer.concat([Buffer.from(PNG, "base64"), Buffer.alloc(5 * 1024 * 1024)]).toString("base64");
  for (const [parts, pattern] of [
    [Array.from({ length: 33 }, () => image()), /at most 32/],
    [Array.from({ length: 4 }, () => image(`data:image/png;base64,${largePng}`)), /20 MiB/],
    [[image(), image(`data:image/png;base64,${"A".repeat(8_000_000)}`)], /8000000/],
  ]) {
    await assert.rejects(h.server.chat([{ role: "user", content: parts }]), pattern);
    assert.equal(h.server.sequence, 0);
    clean(h);
  }
});

for (const invalid of ["data:image/png;base64,%%%%", "data:image/png;base64,AAAA",
  "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,", "file:///private.png",
  "https://user:password@example.test/private.png", `data:image/png;base64,${PNG}junk`]) {
  test(`invalid image is rejected and previously materialized images are removed: ${invalid.slice(0, 55)}`, async (t) => {
    const h = harness(t);
    await assert.rejects(h.server.chat([{ role: "user", content: [image(), image(invalid)] }]), /Codex/);
    assert.equal(h.server.sequence, 0, "invalid input must not start a process");
    clean(h);
  });
}

test("unsupported content after an image cannot silently drop text or leak images", async (t) => {
  const h = harness(t);
  await assert.rejects(h.server.chat([{ role: "user", content: [image(), { type: "unknown", text: "lost" }] }]), /Unsupported/);
  clean(h);
});

test("concurrent visual requests keep their image directories and completions separate", async (t) => {
  const h = harness(t);
  const outputs = await Promise.all([h.server.chat(messages), h.server.chat(messages)]);
  assert.deepEqual(outputs, ['{"score":92}', '{"score":92}']);
  const wires = h.notifications.filter((e) => e.method === "fixture/input");
  assert.notEqual(path.dirname(wires[0].params.input[1].path), path.dirname(wires[1].params.input[1].path));
  clean(h);
});
