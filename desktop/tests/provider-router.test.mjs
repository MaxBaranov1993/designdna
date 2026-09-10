import assert from "node:assert/strict";
import test from "node:test";

import { chatWithProvider, PROFILE_TIMEOUTS_MS, profileTimeoutMs, resolveProvider, SELECTABLE_PROVIDERS } from "../services/provider-router.mjs";

const credentials = (connected = true) => ({
  has: (provider) => connected && provider === "openai",
  get: (provider) => connected && provider === "openai" ? "test-key" : null,
});

/* GPT по подписке: Sol и Astra по умолчанию уходят в Codex с явной моделью. */
for (const [provider, model] of [["openai", "gpt-5.6-sol"], ["astra", "gpt-6-astra"]]) {
  test(`${provider} routes through the Codex subscription with ${model}`, async () => {
    let seen;
    let openaiCalled = false;
    const result = await chatWithProvider({
      provider,
      envelope: { provider, messages: [{ role: "user", content: "hi" }], reasoning: { effort: "high" } },
      credentials: credentials(false),
      codex: { chat: async (messages, options) => { seen = { messages, options }; return "codex-output"; } },
      openaiChat: async () => { openaiCalled = true; return { content: "", transport: {} }; },
    });
    assert.equal(openaiCalled, false);
    assert.equal(seen.options.model, model);
    assert.equal(seen.options.effort, "high");
    assert.equal(result.provider, "codex");
    assert.equal(result.transport.requestedProvider, provider);
    assert.equal(result.transport.fallback, null);
    assert.equal(result.content, "codex-output");
  });
}

test("GPT without a wired Codex fails with a subscription hint, not an API-key hint", async () => {
  await assert.rejects(
    chatWithProvider({ provider: "openai", messages: [{ role: "user", content: "hi" }], credentials: credentials() }),
    /Codex.*Connections/,
  );
});

for (const effort of ["medium", "high", "max"]) {
  test(`router keeps Sol ${effort} on the explicit API transport`, async () => {
    let received;
    const result = await chatWithProvider({
      provider: "openai",
      gptTransport: "openai",
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
    gptTransport: "openai",
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

test("router fails clearly when the explicit API transport has no OpenAI key", async () => {
  await assert.rejects(
    chatWithProvider({ provider: "openai", gptTransport: "openai", messages: [{ role: "user", content: "hi" }], credentials: credentials(false) }),
    /OpenAI.*Connections/,
  );
});

test("selectable providers are Sol, Astra, Codex and Claude", () => {
  assert.deepEqual([...SELECTABLE_PROVIDERS], ["openai", "astra", "codex", "claude"]);
});

test("resolveProvider keeps supported values and migrates the rest", () => {
  for (const provider of ["openai", "astra", "codex", "claude"]) {
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
  assert.equal(result.transport.model, null, "an adapter without metadata must not fabricate a model");
});

test("Codex transport uses response metadata instead of the requested model", async () => {
  const result = await chatWithProvider({ envelope: { provider: "codex", model: "requested-alias", messages: [] },
    codex: { chat: async (_messages, { onResponseMetadata }) => {
      onResponseMetadata({ model: "resolved-model", modelProvider: "openai", authType: "chatgpt",
        threadId: "thread-resolved", turnId: "turn-resolved", modelSource: "thread/start" });
      return "ok";
    } },
  });
  assert.equal(result.transport.model, "resolved-model");
  assert.equal(result.transport.modelProvider, "openai");
  assert.equal(result.transport.threadId, "thread-resolved");
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


for (const provider of ["codex", "claude"]) {
  test(`${provider} keeps image evidence on the selected subscription transport`, async () => {
    const controller = new AbortController();
    const messages = [{ role: "user", content: [
      { type: "text", text: "segment" },
      { type: "image_url", image_url: { url: "data:image/png;base64,AAAA", detail: "high" } },
      { type: "text", text: "compare with Source" },
    ] }];
    let seen;
    const result = await chatWithProvider({
      envelope: { provider, system: "Source DS contract", messages, timeoutMs: 45_000 },
      signal: controller.signal,
      credentials: { has: () => { throw new Error("must not inspect API credentials"); } },
      [provider]: { chat: async (input, options) => { seen = { input, options }; return "ok"; } },
      openaiChat: () => { throw new Error("unexpected API fallback"); },
    });
    assert.deepEqual(seen.input, [{ role: "system", content: "Source DS contract" }, ...messages]);
    assert.equal(seen.options.signal, controller.signal);
    assert.equal(seen.options.timeoutMs, 45_000);
    assert.equal(result.provider, provider);
    assert.equal(result.transport.fallback, null);
  });

  test(`${provider} image failure never falls back to API or the other subscription`, async () => {
    const failure = new Error("subscription vision unavailable");
    let otherCalls = 0;
    const unexpected = { chat: () => { otherCalls++; return "wrong"; } };
    await assert.rejects(chatWithProvider({
      envelope: { provider, messages: [{ role: "user", content: [
        { type: "image_url", image_url: { url: "data:image/png;base64,AAAA" } },
      ] }] },
      codex: unexpected, claude: unexpected,
      [provider]: { chat: () => { throw failure; } },
      credentials: credentials(),
      openaiChat: () => { otherCalls++; return { content: "wrong" }; },
    }), (error) => error === failure);
    assert.equal(otherCalls, 0);
  });
}

test("router applies profile timeouts to both subscription transports", async () => {
  for (const [profile, expected] of [["generator", 600_000], ["quality_judge", 300_000], ["art_direction", 300_000], ["unknown-profile", 600_000]]) {
    let claudeSeen;
    let codexSeen;
    await chatWithProvider({
      provider: "claude", profile,
      envelope: { provider: "claude", messages: [{ role: "user", content: "hi" }] },
      credentials: credentials(false),
      claude: { chat: async (_messages, options) => { claudeSeen = options; return "ok"; } },
    });
    await chatWithProvider({
      provider: "codex", profile,
      envelope: { provider: "codex", messages: [{ role: "user", content: "hi" }] },
      credentials: credentials(false),
      codex: { chat: async (_messages, options) => { codexSeen = options; return "ok"; } },
    });
    assert.equal(claudeSeen.timeoutMs, expected, `claude ${profile}`);
    assert.equal(codexSeen.timeoutMs, expected, `codex ${profile}`);
  }
  assert.equal(profileTimeoutMs("generator", 45_000), 45_000);
  assert.equal(profileTimeoutMs("generator", "oops"), PROFILE_TIMEOUTS_MS.generator);
  assert.equal(PROFILE_TIMEOUTS_MS.generator, 600_000);
});
