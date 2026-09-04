import assert from "node:assert/strict";
import test from "node:test";
import { prepareProviderRequest, chatWithProvider } from "../services/provider-router.mjs";
import { chatWithOpenAI } from "../services/provider-chat.mjs";

const credentials = { has: () => true, get: () => "test-only" };
const messages = [{ role: "user", content: "Review this design" }];

for (const [provider, model] of [["openai", "gpt-5.6-sol"], ["astra", "gpt-6-astra"], ["openai", "gpt-6-astra"]]) {
  test(`${provider}/${model} survives IPC, routing and Responses serialization`, async () => {
    const prepared = prepareProviderRequest({ provider, model, messages, reasoning: { effort: "max" } }, "chosen-model");
    let wire;
    const result = await chatWithProvider({
      ...prepared, credentials,
      openaiChat: (args) => chatWithOpenAI({ ...args, fetchImpl: async (_url, init) => {
        wire = JSON.parse(init.body);
        return { ok: true, json: async () => ({ status: "completed", output_text: "ok" }) };
      } }),
    });
    assert.equal(wire.model, model);
    assert.deepEqual(wire.reasoning, { effort: "max" });
    assert.equal(result.transport.model, model);
    assert.equal(result.transport.fallback, null);
    assert.deepEqual(result.transport.dropped, []);
  });
}

for (const model of ["opus", "sonnet", "haiku"]) {
  test(`explicit Claude ${model} survives IPC without a Sol replacement`, async () => {
    const prepared = prepareProviderRequest({ provider: "claude", model, messages }, "claude-selection");
    let options;
    const result = await chatWithProvider({
      ...prepared, credentials: { has: () => false },
      claude: { chat: async (_messages, input) => { options = input; return "ok"; } },
      openaiChat: () => { throw new Error("must not call OpenAI"); },
    });
    assert.equal(options.model, model);
    assert.equal(result.transport.model, model);
    assert.equal(result.provider, "claude");
  });
}

test("Astra keeps image evidence and structured output on the wire", async () => {
  const image = "data:image/png;base64,aGVsbG8=";
  const { envelope } = prepareProviderRequest({
    provider: "astra",
    messages: [{ role: "user", content: [
      { type: "text", text: "Compare" },
      { type: "image_url", image_url: { url: image, detail: "high" } },
    ] }],
    responseFormat: { type: "json_schema", jsonSchema: {
      name: "review", schema: { type: "object", properties: { ok: { type: "boolean" } }, required: ["ok"], additionalProperties: false },
    } },
  }, "vision-review");
  let wire;
  await chatWithOpenAI({ credentials, envelope, fetchImpl: async (_url, init) => {
    wire = JSON.parse(init.body);
    return { ok: true, json: async () => ({ status: "completed", output_text: '{"ok":true}' }) };
  } });
  assert.equal(wire.model, "gpt-6-astra");
  assert.deepEqual(wire.input[0].content, [
    { type: "input_text", text: "Compare" },
    { type: "input_image", image_url: image, detail: "high" },
  ]);
  assert.equal(wire.text.format.type, "json_schema");
  assert.equal(wire.text.format.name, "review");
  assert.deepEqual(wire.text.format.schema.required, ["ok"]);
});

test("partial Responses output is never reported as a successful result", async () => {
  await assert.rejects(chatWithOpenAI({ credentials, messages,
    fetchImpl: async () => ({ ok: true, json: async () => ({
      status: "incomplete", incomplete_details: { reason: "max_output_tokens" }, output_text: "partial",
    }) }),
  }), (error) => error.code === "PROVIDER_INCOMPLETE" && /max_output_tokens/.test(error.message));
});

test("an unavailable Astra key does not fall back to another account", async () => {
  const prepared = prepareProviderRequest({ provider: "astra", messages }, "missing-key");
  await assert.rejects(chatWithProvider({ ...prepared, credentials: { has: () => false },
    claude: { chat: () => { throw new Error("unexpected Claude call"); } },
  }), /OpenAI.*Connections/);
});
