import assert from "node:assert/strict";
import test from "node:test";

import { chatWithOpenAI } from "../services/provider-chat.mjs";
import { createEnvelope } from "../services/provider-envelope.mjs";

const credentials = { get: () => "test-key" };

test("Sol function calls preserve correlation and canonical argument bytes", async () => {
  const first = await chatWithOpenAI({
    credentials,
    envelope: createEnvelope({
      provider: "openai",
      messages: [{ role: "user", content: "echo 7" }],
      tools: [{ type: "function", function: { name: "echo", parameters: { type: "object", properties: { value: { type: "number" } } } } }],
    }),
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ output: [{ type: "function_call", call_id: "call_1", name: "echo", arguments: "{\"value\":7}" }] }),
    }),
  });
  assert.deepEqual(first.toolCalls, [{ id: "call_1", name: "echo", arguments: "{\"value\":7}" }]);

  let secondBody;
  await chatWithOpenAI({
    credentials,
    envelope: createEnvelope({
      provider: "openai",
      messages: [
        { role: "assistant", content: "", toolCalls: [{ id: "call_1", type: "function", function: { name: "echo", arguments: "{\"value\":7}" } }] },
        { role: "tool", toolCallId: "call_1", name: "echo", content: "7" },
      ],
    }),
    fetchImpl: async (_url, options) => {
      secondBody = JSON.parse(options.body);
      return { ok: true, status: 200, json: async () => ({ output_text: "done", output: [] }) };
    },
  });
  assert.deepEqual(secondBody.input, [
    { type: "function_call", call_id: "call_1", name: "echo", arguments: "{\"value\":7}" },
    { type: "function_call_output", call_id: "call_1", output: "7" },
  ]);
});

test("Sol rejects malformed tool arguments before MCP execution", async () => {
  await assert.rejects(
    chatWithOpenAI({
      credentials,
      messages: [{ role: "user", content: "call" }],
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({ output: [{ type: "function_call", call_id: "call_1", name: "echo", arguments: "{" }] }),
      }),
    }),
    /arguments|JSON/i,
  );
});
