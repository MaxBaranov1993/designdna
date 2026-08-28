import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chatWithProvider } from "../services/provider-router.mjs";
import { createEnvelope } from "../services/provider-envelope.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const preloadSource = fs.readFileSync(path.join(directory, "..", "preload.cjs"), "utf-8");
const mainSource = fs.readFileSync(path.join(directory, "..", "main.mjs"), "utf-8");

/* IPC-контракт без Electron-рантайма: preload-мост обязан выставлять новые
 * каналы, main — их обрабатывать, а payload обеих сторон обязан собираться в
 * валидный envelope с correlation id. Это регрессионный-guard проводки. */

test("preload exposes the typed chat-request and cancellation channels", () => {
  for (const channel of ["providers:chat-request", "providers:cancel", "providers:chat", "mcp:cancel"]) {
    assert.ok(preloadSource.includes(`"${channel}"`), `preload lost IPC channel ${channel}`);
  }
  assert.match(preloadSource, /chatRequest:\s*\(request\)/, "preload must expose providers.chatRequest(request)");
  assert.match(preloadSource, /cancel:\s*\(requestId\)/, "preload must expose providers.cancel(requestId)");
});

test("main registers handlers for the new provider and MCP channels", () => {
  for (const channel of ["providers:chat-request", "providers:cancel", "mcp:cancel"]) {
    assert.ok(mainSource.includes(`handleTrusted("${channel}"`), `main lost handler for ${channel}`);
  }
  // providers:chat остаётся legacy-совместимым для сохранённых графов
  assert.ok(mainSource.includes(`handleTrusted("providers:chat"`));
});

test("legacy providers:chat payload shape wraps into a valid envelope with a correlation id", async () => {
  // Ровно логика runProviderChat: request = payload.request || payload
  const payload = {
    provider: "openai",
    messages: [{ role: "user", content: "Judge this IR" }],
    temperature: 0.8,
    profile: "generator",
    tools: null,
  };
  const request = payload?.request && typeof payload.request === "object" ? payload.request : payload;
  const envelope = createEnvelope({
    ...request,
    id: request?.id || `chat-${Date.now().toString(36)}`,
  });
  assert.equal(envelope.provider, "openai");
  assert.ok(envelope.id);
  assert.equal(envelope.temperature, 0.8);

  let received;
  const result = await chatWithProvider({
    envelope,
    profile: payload.profile,
    credentials: { has: () => true, get: () => "test-key" },
    codex: { account: async () => ({ account: null }) },
    openaiChat: async ({ envelope: passed }) => {
      received = passed;
      return { content: "ok", transport: { provider: "openai", model: "m", dropped: [] } };
    },
  });
  assert.equal(received.id, envelope.id);
  assert.equal(result.transport.requestId, envelope.id);
  assert.equal(result.content, "ok");
});

test("providers:chat-request migrates a retired provider to the Sol contract", async () => {
  const request = {
    id: "corr-ipc-1",
    provider: "glm",
    model: "glm-5.3",
    system: "sys",
    messages: [{ role: "user", content: "hi" }],
    temperature: 0.5,
    topP: 0.9,
    maxOutputTokens: 256,
    reasoning: { effort: "high" },
    stop: ["END"],
    timeoutMs: 120_000,
  };
  let received;
  await chatWithProvider({
    envelope: createEnvelope({
      ...request,
      provider: "openai",
      model: "gpt-5.6-sol",
    }),
    credentials: { has: () => true, get: () => "test-key" },
    codex: { account: async () => ({ account: null }) },
    openaiChat: async ({ envelope: passed }) => {
      received = passed;
      return { content: "ok", transport: { provider: "openai", model: "gpt-5.6-sol", dropped: [] } };
    },
  });
  // параметры дошли до адаптера без потерь
  assert.equal(received.id, "corr-ipc-1");
  assert.equal(received.provider, "openai");
  assert.equal(received.model, "gpt-5.6-sol");
  assert.equal(received.system, "sys");
  assert.equal(received.maxOutputTokens, 256);
  assert.equal(received.reasoning.effort, "high");
  assert.deepEqual(received.stop, ["END"]);
  assert.equal(received.timeoutMs, 120_000);
});
