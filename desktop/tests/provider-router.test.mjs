import assert from "node:assert/strict";
import test from "node:test";

import { chatWithProvider, resolveProvider, SELECTABLE_PROVIDERS } from "../services/provider-router.mjs";

const credentials = (connected = true) => ({
  has: (provider) => connected && provider === "openai",
  get: (provider) => connected && provider === "openai" ? "test-key" : null,
});

for (const effort of ["medium", "high", "max"]) {
  test(`router keeps Sol ${effort}`, async () => {
    let received;
    const result = await chatWithProvider({
      provider: "openai",
      envelope: {
        provider: "openai",
        model: "gpt-5.6-sol",
        messages: [{ role: "user", content: "hi" }],
        reasoning: { effort },
      },
      credentials: credentials(),
      openaiChat: async ({ envelope }) => {
        received = envelope;
        return { content: "ok", transport: { provider: "openai", model: "gpt-5.6-sol", dropped: [] } };
      },
    });
    assert.equal(received.model, "gpt-5.6-sol");
    assert.equal(received.reasoning.effort, effort);
    assert.equal(result.provider, "openai");
    assert.equal(result.transport.fallback, null);
  });
}

test("router migrates a retired persisted selection to Sol medium", async () => {
  let received;
  const result = await chatWithProvider({
    provider: "kimi",
    messages: [{ role: "user", content: "hi" }],
    credentials: credentials(),
    openaiChat: async ({ envelope }) => {
      received = envelope;
      return { content: "ok", transport: { provider: "openai", model: "gpt-5.6-sol", dropped: [] } };
    },
  });
  assert.equal(received.provider, "openai");
  assert.equal(received.reasoning.effort, "medium");
  assert.equal(result.transport.fallback, "openai");
});

test("router fails clearly when OpenAI is disconnected", async () => {
  await assert.rejects(
    chatWithProvider({ provider: "openai", messages: [{ role: "user", content: "hi" }], credentials: credentials(false) }),
    /OpenAI.*Connections/,
  );
});

test("selectable providers are exactly Sol, Codex and Claude", () => {
  assert.deepEqual([...SELECTABLE_PROVIDERS], ["openai", "codex", "claude"]);
});

test("resolveProvider keeps supported values and migrates the rest", () => {
  for (const provider of ["openai", "codex", "claude"]) {
    assert.equal(resolveProvider(provider), provider);
  }
  for (const retired of ["kimi", "glm", "zai", "grok", "zcode", "auto", "", null, undefined]) {
    assert.equal(resolveProvider(retired), "openai");
  }
});

test("codex selection reaches the Codex app-server, not OpenAI", async () => {
  let codexProfile;
  let openaiCalled = false;
  const result = await chatWithProvider({
    provider: "codex",
    envelope: { provider: "codex", messages: [{ role: "user", content: "hi" }] },
    profile: "quality_judge",
    credentials: credentials(),
    codex: {
      chat: async (messages, options) => {
        codexProfile = options.profile;
        assert.deepEqual(messages, [{ role: "user", content: "hi" }]);
        return "codex-output";
      },
    },
    openaiChat: async () => { openaiCalled = true; return { content: "", transport: {} }; },
  });
  assert.equal(openaiCalled, false);
  assert.equal(codexProfile, "quality_judge");
  assert.equal(result.content, "codex-output");
  assert.equal(result.provider, "codex");
  assert.equal(result.transport.provider, "codex");
  assert.equal(result.transport.fallback, null);
});

test("claude selection reaches the Claude CLI with the node effort", async () => {
  let seen;
  let openaiCalled = false;
  const result = await chatWithProvider({
    provider: "claude",
    envelope: {
      provider: "claude",
      messages: [{ role: "user", content: "hi" }],
      reasoning: { effort: "max" },
    },
    credentials: credentials(),
    claude: {
      chat: async (messages, options) => {
        seen = { messages, options };
        return "claude-output";
      },
    },
    openaiChat: async () => { openaiCalled = true; return { content: "", transport: {} }; },
  });
  assert.equal(openaiCalled, false);
  assert.equal(seen.options.effort, "max");
  assert.equal(result.content, "claude-output");
  assert.equal(result.provider, "claude");
  assert.equal(result.transport.model, "opus");
});

test("selecting a runtime that is not wired fails with a Connections hint", async () => {
  await assert.rejects(
    chatWithProvider({ provider: "claude", messages: [], credentials: credentials() }),
    /Claude.*Connections/,
  );
  await assert.rejects(
    chatWithProvider({ provider: "codex", messages: [], credentials: credentials() }),
    /Codex.*Connections/,
  );
});

test("Codex and Claude do not require the OpenAI credential", async () => {
  const result = await chatWithProvider({
    provider: "claude",
    envelope: { provider: "claude", messages: [{ role: "user", content: "hi" }] },
    credentials: credentials(false),
    claude: { chat: async () => "ok" },
  });
  assert.equal(result.content, "ok");
});
