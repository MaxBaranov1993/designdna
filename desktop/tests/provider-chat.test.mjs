import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { chatWithGlm, chatWithKimi, chatWithOpenAI } from "../services/provider-chat.mjs";

const okResponse = { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '{"ok":true}' } }] }) };

test("Kimi chat uses a plain API key as Bearer on the managed coding endpoint", async () => {
  let request;
  const content = await chatWithKimi({
    credentials: { get: () => "secret-kimi-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return okResponse;
    },
    environment: {},
  });
  assert.equal(content, '{"ok":true}');
  assert.equal(request.url, "https://api.kimi.com/coding/v1/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-kimi-key");
  assert.equal(JSON.parse(request.options.body).model, "k3");
  assert.doesNotMatch(request.options.body, /secret-kimi-key/);
});

test("Kimi chat sends the fresh access token from an imported OAuth bundle", async () => {
  let request;
  const bundle = { access_token: "bundle-access-token", refresh_token: "bundle-refresh", expires_at: Math.floor(Date.now() / 1000) + 3600 };
  const content = await chatWithKimi({
    credentials: { get: () => JSON.stringify(bundle) },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return okResponse;
    },
    environment: {},
  });
  assert.equal(content, '{"ok":true}');
  assert.equal(request.options.headers.Authorization, "Bearer bundle-access-token");
});

test("Kimi chat reports an actionable missing-key error", async () => {
  // A local CLI session is never imported implicitly; the user must approve it
  // through Agents → Connections.
  const emptyHome = fs.mkdtempSync(path.join(os.tmpdir(), "kimi-home-"));
  process.env.KIMI_CODE_HOME = emptyHome;
  try {
    await assert.rejects(
      chatWithKimi({ credentials: { get: () => null }, messages: [{ role: "user", content: "Generate" }] }),
      /Agents → Connections/,
    );
  } finally {
    delete process.env.KIMI_CODE_HOME;
  }
});

test("OpenAI chat posts to api.openai.com with the stored key and gpt-5.6-sol", async () => {
  let request;
  const content = await chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return okResponse;
    },
    environment: {},
  });
  assert.equal(content, '{"ok":true}');
  assert.equal(request.url, "https://api.openai.com/v1/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-openai-key");
  assert.equal(JSON.parse(request.options.body).model, "gpt-5.6-sol");
  assert.doesNotMatch(request.options.body, /secret-openai-key/);
});

test("OpenAI chat reports an actionable missing-key error", async () => {
  await assert.rejects(
    chatWithOpenAI({ credentials: { get: () => null }, messages: [{ role: "user", content: "Generate" }] }),
    /Agents → Connections/,
  );
});


test("GLM chat posts to bigmodel.cn with the stored key and glm-5.3", async () => {
  let request;
  const content = await chatWithGlm({
    credentials: { get: () => "secret-glm-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(content, '{"ok":true}');
  assert.equal(request.url, "https://open.bigmodel.cn/api/paas/v4/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-glm-key");
  assert.equal(JSON.parse(request.options.body).model, "glm-5.3");
  assert.ok(JSON.parse(request.options.body).response_format);
});

test("GLM tool mode returns tool_calls instead of forcing json_object", async () => {
  const toolResponse = {
    ok: true, status: 200,
    json: async () => ({ choices: [{ message: { content: "", tool_calls: [{ id: "c1", function: { name: "mcp_list", arguments: "{\"path\":\".\"}" } }] } }] }),
  };
  let request;
  const result = await chatWithGlm({
    credentials: { get: () => "secret-glm-key" },
    messages: [{ role: "user", content: "list files" }],
    tools: [{ type: "function", function: { name: "mcp_list", description: "list", parameters: { type: "object", properties: {} } } }],
    returnToolCalls: true,
    fetchImpl: async (url, options) => { request = { url, options }; return toolResponse; },
    environment: {},
  });
  assert.deepEqual(result.toolCalls, [{ id: "c1", name: "mcp_list", arguments: '{"path":"."}' }]);
  const body = JSON.parse(request.options.body);
  assert.ok(Array.isArray(body.tools));
  assert.ok(!body.response_format);
});

test("GLM chat reports an actionable missing-key error", async () => {
  await assert.rejects(
    chatWithGlm({ credentials: { get: () => null }, messages: [{ role: "user", content: "Generate" }] }),
    /Agents → Connections/,
  );
});
