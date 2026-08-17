import assert from "node:assert/strict";
import test from "node:test";
import { chatWithKimi } from "../services/provider-chat.mjs";

test("Kimi chat keeps the credential in the Authorization header and returns content", async () => {
  let request;
  const content = await chatWithKimi({
    apiKey: "secret-kimi-key",
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '{"ok":true}' } }] }) };
    },
    environment: {},
  });
  assert.equal(content, '{"ok":true}');
  assert.equal(request.url, "https://api.moonshot.ai/v1/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-kimi-key");
  assert.equal(JSON.parse(request.options.body).model, "kimi-k2.5");
  assert.doesNotMatch(request.options.body, /secret-kimi-key/);
});

test("Kimi chat reports an actionable missing-key error", async () => {
  await assert.rejects(
    chatWithKimi({ apiKey: null, messages: [{ role: "user", content: "Generate" }] }),
    /Agents → Connections/,
  );
});
