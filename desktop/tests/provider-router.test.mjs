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
    zcodeChat: async () => { called = true; return '{"score":85}'; },
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
    zcodeChat: async () => "ok-zcode",
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

test("an unavailable saved OpenAI route falls back to the connected Codex account", async () => {
  const result = await chatWithProvider({
    provider: "openai",
    messages,
    credentials: credentials(),
    codex: {
      account: async () => ({ account: { email: "user@example.com" } }),
      chat: async () => '{"score":91}',
    },
  });
  assert.equal(result.provider, "codex");
  assert.equal(result.content, '{"score":91}');
});

test("an unavailable saved Kimi route falls back to a configured OpenAI account", async () => {
  const result = await chatWithProvider({
    provider: "kimi",
    messages,
    credentials: credentials(["openai"]),
    codex: { account: async () => ({ account: null }) },
    openaiChat: async () => '{"score":89}',
  });
  assert.equal(result.provider, "openai");
  assert.equal(result.content, '{"score":89}');
});

test("explicit Codex route does not fall back after a chat error", async () => {
  await assert.rejects(
    chatWithProvider({
      provider: "codex",
      messages,
      credentials: credentials(["kimi"]),
      codex: { chat: async () => { throw new Error("Codex request failed"); } },
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

test("explicit glm routes to glmChat and disconnected glm falls back", async () => {
  let glmCalls = 0;
  const result = await chatWithProvider({
    provider: "glm",
    messages,
    credentials: credentials(["glm"]),
    codex: { account: async () => ({ account: null }) },
    glmChat: async () => { glmCalls += 1; return "ok-glm"; },
  });
  assert.equal(result.provider, "glm");
  assert.equal(result.content, "ok-glm");
  assert.equal(glmCalls, 1);

  const fallback = await chatWithProvider({
    provider: "glm",
    messages,
    credentials: credentials(["openai"]),
    codex: { account: async () => ({ account: null }) },
    openaiChat: async () => "ok-openai",
  });
  assert.equal(fallback.provider, "openai");
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
