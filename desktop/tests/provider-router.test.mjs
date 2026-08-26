import assert from "node:assert/strict";
import test from "node:test";
import { chatWithProvider } from "../services/provider-router.mjs";

const messages = [{ role: "user", content: "Judge this IR" }];
const credentials = (configured = []) => ({
  has: (provider) => configured.includes(provider),
  get: (provider) => configured.includes(provider) ? `test-${provider}-credential` : null,
});

test("auto provider prefers an authenticated Codex account and keeps its profile", async () => {
  let options;
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    profile: "quality_judge",
    credentials: credentials(["kimi", "openai"]),
    codex: {
      account: async () => ({ account: { email: "user@example.com" } }),
      chat: async (_messages, received) => { options = received; return '{"score":90}'; },
    },
  });
  assert.equal(result.provider, "codex");
  assert.equal(result.content, '{"score":90}');
  assert.equal(options.profile, "quality_judge");
  assert.equal(options.timeoutMs, 180_000);
});

test("Codex generator profile gets a production-page timeout budget", async () => {
  let options;
  await chatWithProvider({
    provider: "codex",
    messages,
    profile: "generator",
    credentials: credentials(),
    codex: {
      account: async () => ({ account: { email: "user@example.com" } }),
      chat: async (_messages, received) => { options = received; return '{"ok":true}'; },
    },
  });
  assert.equal(options.timeoutMs, 300_000);
});

test("auto provider uses an explicitly connected Kimi account when Codex is signed out", async () => {
  let called = false;
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(["kimi", "openai"]),
    codex: { account: async () => ({ account: null }) },
    kimiChat: async () => { called = true; return '{"score":88}'; },
  });
  assert.equal(result.provider, "kimi");
  assert.equal(called, true);
});

test("auto provider falls back to a configured OpenAI key", async () => {
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(["openai"]),
    codex: { account: async () => { throw new Error("not running"); } },
    openaiChat: async () => '{"score":87}',
  });
  assert.equal(result.provider, "openai");
});

test("auto provider fails clearly when no account is connected", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "auto",
      messages,
      credentials: credentials(),
      codex: { account: async () => ({ account: null }) },
      zcodeAvailable: () => null,
    }),
    /Нет подключённого AI-аккаунта/,
  );
});

test("auto provider falls back to the local ZCode CLI when no account is connected", async () => {
  let called = false;
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(),
    codex: { account: async () => ({ account: null }) },
    zcodeAvailable: () => "C:/fake/zcode.cjs",
    zcodeChat: async () => { called = true; return { content: '{"score":85}' }; },
  });
  assert.equal(result.provider, "zcode");
  assert.equal(result.content, '{"score":85}');
  assert.equal(called, true);
});

test("explicit zcode route works without credentials and fails clearly when unavailable", async () => {
  const result = await chatWithProvider({
    provider: "zcode",
    messages,
    credentials: credentials(),
    codex: { account: async () => ({ account: null }) },
    zcodeAvailable: () => "C:/fake/zcode.cjs",
    zcodeChat: async () => ({ content: "ok-zcode" }),
  });
  assert.equal(result.provider, "zcode");
  assert.equal(result.content, "ok-zcode");

  await assert.rejects(
    chatWithProvider({
      provider: "zcode",
      messages,
      credentials: credentials(),
      codex: { account: async () => ({ account: null }) },
      zcodeAvailable: () => null,
    }),
    /ZCode CLI не найден/,
  );
});

test("explicit OpenAI route fails deterministically when no key is configured", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "openai",
      messages,
      credentials: credentials(),
      codex: { account: async () => ({ account: { email: "user@example.com" } }) },
    }),
    /Провайдер openai не подключён/,
  );
});

test("explicit Kimi route fails deterministically when no key is configured", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "kimi",
      messages,
      credentials: credentials(["openai"]),
      codex: { account: async () => ({ account: null }) },
    }),
    /Провайдер kimi не подключён/,
  );
});

test("auto provider reports the selected fallback in transport.fallback", async () => {
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(["openai"]),
    codex: { account: async () => ({ account: null }) },
    openaiChat: async () => ({ content: '{"score":89}' }),
  });
  assert.equal(result.provider, "openai");
  assert.equal(result.transport.fallback, "openai");
});

test("explicit Codex route does not fall back after a chat error", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "codex",
      messages,
      credentials: credentials(["kimi"]),
      codex: {
        account: async () => ({ account: { email: "user@example.com" } }),
        chat: async () => { throw new Error("Codex request failed"); },
      },
      kimiChat: async () => '{"unexpected":true}',
    }),
    /Codex request failed/,
  );
});

test("auto provider uses a GLM key when Codex is signed out and Kimi is absent", async () => {
  let called = false;
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(["glm"]),
    codex: { account: async () => ({ account: null }) },
    glmChat: async () => { called = true; return '{"score":86}'; },
  });
  assert.equal(result.provider, "glm");
  assert.equal(called, true);
});

test("explicit glm routes to glmChat and fails clearly when disconnected", async () => {
  let glmCalls = 0;
  const result = await chatWithProvider({
    provider: "glm",
    messages,
    credentials: credentials(["glm"]),
    codex: { account: async () => ({ account: null }) },
    glmChat: async () => { glmCalls += 1; return { content: "ok-glm" }; },
  });
  assert.equal(result.provider, "glm");
  assert.equal(result.content, "ok-glm");
  assert.equal(glmCalls, 1);

  await assert.rejects(
    chatWithProvider({
      provider: "glm",
      messages,
      credentials: credentials(["openai"]),
      codex: { account: async () => ({ account: null }) },
      openaiChat: async () => ({ content: "ok-openai" }),
    }),
    /Провайдер glm не подключён/,
  );
});

test("glm tool-calls pass through to the caller (MCP agent loop)", async () => {
  const result = await chatWithProvider({
    provider: "glm",
    messages,
    credentials: credentials(["glm"]),
    codex: { account: async () => ({ account: null }) },
    tools: [{ type: "function", function: { name: "mcp_list_files", description: "list", parameters: { type: "object", properties: {} } } }],
    glmChat: async () => ({ content: "", toolCalls: [{ id: "1", name: "mcp_list_files", arguments: "{}" }] }),
  });
  assert.deepEqual(result.toolCalls, [{ id: "1", name: "mcp_list_files", arguments: "{}" }]);
});

test("explicit Grok route fails deterministically when no key is configured", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "grok",
      messages,
      credentials: credentials(["openai"]),
      codex: { account: async () => ({ account: null }) },
    }),
    /Провайдер grok не подключён/,
  );
});

test("explicit Z.AI route fails deterministically when no key is configured", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "zai",
      messages,
      credentials: credentials(["glm"]),
      codex: { account: async () => ({ account: null }) },
    }),
    /Провайдер zai не подключён/,
  );
});

test("explicit Z.AI route reaches the zai adapter and reports fallback: null", async () => {
  let called = false;
  const result = await chatWithProvider({
    provider: "zai",
    messages,
    credentials: credentials(["zai"]),
    codex: { account: async () => ({ account: null }) },
    zaiChat: async () => { called = true; return { content: "ok-zai", transport: { provider: "zai", model: "glm-5.3", dropped: [] } }; },
  });
  assert.equal(called, true);
  assert.equal(result.provider, "zai");
  assert.equal(result.content, "ok-zai");
  assert.equal(result.transport.fallback, null);
});

test("auto provider can select a configured Z.AI account", async () => {
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(["zai"]),
    codex: { account: async () => ({ account: null }) },
    zaiChat: async () => ({ content: "auto-zai", transport: { provider: "zai", model: "glm-5.3", dropped: [] } }),
  });
  assert.equal(result.provider, "zai");
  assert.equal(result.transport.fallback, "zai");
});

test("auto provider prefers direct Z.AI over legacy Zhipu GLM when both exist", async () => {
  let used = null;
  const result = await chatWithProvider({
    provider: "auto",
    messages,
    credentials: credentials(["glm", "zai"]),
    codex: { account: async () => ({ account: null }) },
    glmChat: async () => { used = "glm"; return { content: "glm" }; },
    zaiChat: async () => { used = "zai"; return { content: "zai", transport: { provider: "zai", model: "glm-5.3", dropped: [] } }; },
  });
  assert.equal(used, "zai");
  assert.equal(result.provider, "zai");
});

test("explicit Codex route without an account fails deterministically", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "codex",
      messages,
      credentials: credentials(["openai"]),
      codex: { account: async () => ({ account: null }) },
      openaiChat: async () => ({ content: "unexpected" }),
    }),
    /Codex не подключён/,
  );
});

test("explicit provider routes report transport.fallback === null", async () => {
  const result = await chatWithProvider({
    provider: "openai",
    messages,
    credentials: credentials(["openai"]),
    codex: { account: async () => ({ account: null }) },
    openaiChat: async () => ({ content: "ok-openai" }),
  });
  assert.equal(result.provider, "openai");
  assert.equal(result.transport.fallback, null);
});

test("explicit codex route rejects image parts instead of silently flattening them", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "codex",
      messages: [{
        role: "user",
        content: [
          { type: "text", text: "describe" },
          { type: "image_url", image_url: { url: "data:image/png;base64,aGk=" } },
        ],
      }],
      credentials: credentials(),
      codex: {
        account: async () => ({ account: { email: "user@example.com" } }),
        chat: async () => "unexpected",
      },
    }),
    (error) => error.code === "UNSUPPORTED_CAPABILITY" && /multimodal/.test(error.message),
  );
});
