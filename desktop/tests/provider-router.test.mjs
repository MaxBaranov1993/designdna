import assert from "node:assert/strict";
import test from "node:test";
import { chatWithProvider } from "../services/provider-router.mjs";

const messages = [{ role: "user", content: "Judge this IR" }];
const credentials = (configured = []) => ({ has: (provider) => configured.includes(provider) });

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
    }),
    /Нет подключённого AI-аккаунта/,
  );
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
