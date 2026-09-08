import assert from "node:assert/strict";
import test from "node:test";

import { chatWithOpenAI } from "../services/provider-chat.mjs";
import { createEnvelope } from "../services/provider-envelope.mjs";
import { chatWithProvider } from "../services/provider-router.mjs";


const credentials = {
  has: (provider) => provider === "openai",
  get: (provider) => provider === "openai" ? "secret-openai-key" : null,
};

test("Sol adapter uses Responses with explicit effort and flat function tools", async () => {
  let request;
  const envelope = createEnvelope({
    provider: "openai",
    model: "gpt-5.6-sol",
    reasoning: { effort: "high" },
    messages: [{ role: "user", content: "inspect" }],
    tools: [{
      type: "function",
      function: { name: "mcp_list", description: "List files", parameters: { type: "object", properties: {} } },
    }],
  });
  const result = await chatWithOpenAI({
    credentials,
    envelope,
    fetchImpl: async (url, options) => {
      request = { url, options, body: JSON.parse(options.body) };
      return {
        ok: true,
        status: 200,
        json: async () => ({
          model: "gpt-5.6-sol",
          output: [{ type: "function_call", call_id: "call_1", name: "mcp_list", arguments: "{}" }],
        }),
      };
    },
  });

  assert.equal(request.url, "https://api.openai.com/v1/responses");
  assert.equal(request.body.model, "gpt-5.6-sol");
  assert.deepEqual(request.body.reasoning, { effort: "high" });
  assert.deepEqual(request.body.tools[0], {
    type: "function", name: "mcp_list", description: "List files",
    parameters: { type: "object", properties: {} }, strict: false,
  });
  assert.equal(request.body.temperature, undefined);
  assert.deepEqual(result.toolCalls, [{ id: "call_1", name: "mcp_list", arguments: "{}" }]);
});

test("provider router migrates a retired selection to Sol medium", async () => {
  let passed;
  const result = await chatWithProvider({
    provider: "glm",
    gptTransport: "openai",
    messages: [{ role: "user", content: "hello" }],
    credentials,
    openaiChat: async ({ envelope }) => {
      passed = envelope;
      return { content: "ok", toolCalls: null, transport: { provider: "openai", model: "gpt-5.6-sol", dropped: [] } };
    },
  });
  assert.equal(passed.provider, "openai");
  assert.equal(passed.model, "gpt-5.6-sol");
  assert.deepEqual(passed.reasoning, { effort: "medium", budgetTokens: null });
  assert.equal(result.provider, "openai");
  assert.equal(result.transport.fallback, "openai");
});

test("agent UI exposes only Medium, High and Max", async () => {
  const source = await import("node:fs/promises").then(({ readFile }) => readFile(
    new URL("../../frontend/src/desktop/AgentWorkspace.svelte", import.meta.url), "utf-8",
  ));
  for (const effort of ["medium", "high", "max"]) assert.match(source, new RegExp(`agentEffort === "${effort}"`));
  assert.doesNotMatch(source, />Kimi</);
  assert.doesNotMatch(source, />Grok</);
  assert.doesNotMatch(source, />GLM-/);
  assert.doesNotMatch(source, />ZCode</);
});
