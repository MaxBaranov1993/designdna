import assert from "node:assert/strict";
import test from "node:test";

import { chatWithOpenAI } from "../services/provider-chat.mjs";

const connected = { get: (provider) => provider === "openai" ? "secret-openai-key" : null };

test("OpenAI chat uses the fixed Sol Responses contract", async () => {
  let request;
  const result = await chatWithOpenAI({
    credentials: connected,
    envelope: {
      provider: "openai",
      model: "gpt-5.6-sol",
      messages: [{ role: "user", content: [{ type: "text", text: "Generate" }] }],
      reasoning: { effort: "max" },
    },
    fetchImpl: async (url, options) => {
      request = { url, options, body: JSON.parse(options.body) };
      return {
        ok: true,
        status: 200,
        json: async () => ({ output: [{ type: "message", content: [{ type: "output_text", text: "ok" }] }] }),
      };
    },
  });

  assert.equal(request.url, "https://api.openai.com/v1/responses");
  assert.equal(request.options.headers.Authorization, "Bearer secret-openai-key");
  assert.equal(request.body.model, "gpt-5.6-sol");
  assert.deepEqual(request.body.reasoning, { effort: "max" });
  assert.equal(request.body.store, false);
  assert.equal(result.content, "ok");
  assert.deepEqual(result.transport, { provider: "openai", model: "gpt-5.6-sol", dropped: [] });
});

test("OpenAI chat reports a missing key before network access", async () => {
  await assert.rejects(
    chatWithOpenAI({ credentials: { get: () => null }, messages: [{ role: "user", content: "Generate" }] }),
    /OpenAI is not connected/,
  );
});

test("OpenAI HTTP failures preserve a structured provider code", async () => {
  await assert.rejects(
    chatWithOpenAI({
      credentials: connected,
      messages: [{ role: "user", content: "Generate" }],
      fetchImpl: async () => ({
        ok: false,
        status: 429,
        json: async () => ({ error: { message: "rate limited" } }),
      }),
    }),
    (error) => error.code === "PROVIDER_HTTP" && /429/.test(error.message),
  );
});
