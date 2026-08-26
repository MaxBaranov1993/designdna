import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { chatWithGlm, chatWithGrok, chatWithKimi, chatWithOpenAI, chatWithZai } from "../services/provider-chat.mjs";

const okResponse = { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '{"ok":true}' } }] }) };

test("Kimi chat uses a plain API key as Bearer on the managed coding endpoint", async () => {
  let request;
  const result = await chatWithKimi({
    credentials: { get: () => "secret-kimi-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return okResponse;
    },
    environment: {},
  });
  assert.equal(result.content, '{"ok":true}');
  assert.equal(result.transport.provider, "kimi");
  // kimi/k3: temperature 0.8 снят ЯВНО — с причиной в transport.dropped
  assert.ok(result.transport.dropped.some((d) => d.field === "temperature"));
  assert.equal(request.url, "https://api.kimi.com/coding/v1/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-kimi-key");
  assert.equal(JSON.parse(request.options.body).model, "k3");
  assert.doesNotMatch(request.options.body, /secret-kimi-key/);
});

test("Kimi chat sends the fresh access token from an imported OAuth bundle", async () => {
  let request;
  const bundle = { access_token: "bundle-access-token", refresh_token: "bundle-refresh", expires_at: Math.floor(Date.now() / 1000) + 3600 };
  const result = await chatWithKimi({
    credentials: { get: () => JSON.stringify(bundle) },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return okResponse;
    },
    environment: {},
  });
  assert.equal(result.content, '{"ok":true}');
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
  const result = await chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => {
      request = { url, options };
      return okResponse;
    },
    environment: {},
  });
  assert.equal(result.content, '{"ok":true}');
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
  const result = await chatWithGlm({
    credentials: { get: () => "secret-glm-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(result.content, '{"ok":true}');
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

test("Z.AI chat posts to the general api.z.ai endpoint with its own credential", async () => {
  let request;
  const result = await chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(result.content, '{"ok":true}');
  assert.equal(result.transport.provider, "zai");
  assert.equal(request.url, "https://api.z.ai/api/paas/v4/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-zai-key");
  assert.equal(JSON.parse(request.options.body).model, "glm-5.3");
  assert.doesNotMatch(request.options.body, /secret-zai-key/);
});

test("Z.AI coding-plan endpoint is used only by explicit opt-in", async () => {
  const seen = [];
  const call = (environment) => chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    messages: [{ role: "user", content: "hi" }],
    fetchImpl: async (url, options) => { seen.push(url); return okResponse; },
    environment,
  });
  await call({});
  await call({ DESIGNDNA_ZAI_ENDPOINT: "general" }); // любое значение кроме coding — общий endpoint
  await call({ DESIGNDNA_ZAI_ENDPOINT: "coding" });
  await call({ DESIGNDNA_ZAI_URL: "https://proxy.example.com/v1/chat/completions" });
  assert.deepEqual(seen, [
    "https://api.z.ai/api/paas/v4/chat/completions",
    "https://api.z.ai/api/paas/v4/chat/completions",
    "https://api.z.ai/api/coding/paas/v4/chat/completions",
    "https://proxy.example.com/v1/chat/completions",
  ]);
});

test("Z.AI and Zhipu GLM keys never cross hosts", async () => {
  const requests = [];
  const capture = async (url, options) => { requests.push({ url, auth: options.headers.Authorization }); return okResponse; };
  const credentials = { get: (provider) => ({ glm: "zhipu-key", zai: "zai-key" })[provider] || null };
  await chatWithGlm({ credentials, messages: [{ role: "user", content: "hi" }], fetchImpl: capture, environment: {} });
  await chatWithZai({ credentials, messages: [{ role: "user", content: "hi" }], fetchImpl: capture, environment: {} });
  assert.deepEqual(requests, [
    { url: "https://open.bigmodel.cn/api/paas/v4/chat/completions", auth: "Bearer zhipu-key" },
    { url: "https://api.z.ai/api/paas/v4/chat/completions", auth: "Bearer zai-key" },
  ]);
});

test("Z.AI reports an actionable missing-key error", async () => {
  await assert.rejects(
    chatWithZai({ credentials: { get: () => null }, messages: [{ role: "user", content: "Generate" }] }),
    /Agents → Connections/,
  );
});

test("Z.AI tool mode returns tool_calls with call IDs", async () => {
  const toolResponse = {
    ok: true, status: 200,
    json: async () => ({ choices: [{ message: { content: "", tool_calls: [{ id: "call_zai_1", function: { name: "mcp_list", arguments: "{\"path\":\".\"}" } }] } }] }),
  };
  let request;
  const result = await chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    envelope: {
      provider: "zai",
      messages: [{ role: "user", content: "list files" }],
      tools: [{ type: "function", function: { name: "mcp_list", description: "list", parameters: { type: "object", properties: {} } } }],
    },
    fetchImpl: async (url, options) => { request = { url, options }; return toolResponse; },
    environment: {},
  });
  assert.deepEqual(result.toolCalls, [{ id: "call_zai_1", name: "mcp_list", arguments: '{"path":"."}' }]);
  const body = JSON.parse(request.options.body);
  assert.ok(Array.isArray(body.tools));
  assert.ok(!body.response_format);
});

test("Z.AI GLM-5.3: reasoning_effort max survives to api.z.ai with thinking always enabled", async () => {
  let request;
  await chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    envelope: {
      provider: "zai",
      messages: [{ role: "user", content: "hard coding task" }],
      reasoning: { effort: "max" },
    },
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(request.url, "https://api.z.ai/api/paas/v4/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-zai-key");
  const body = JSON.parse(request.options.body);
  assert.equal(body.reasoning_effort, "max");
  assert.deepEqual(body.thinking, { type: "enabled" });
  assert.doesNotMatch(request.options.body, /secret-zai-key/);
});

test("Z.AI valid GLM-5.3 fields reach the wire unchanged; out-of-contract values fail before fetch", async () => {
  let request;
  await chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    envelope: {
      provider: "zai",
      messages: [{ role: "user", content: "hi" }],
      temperature: 0.5,
      topP: 0.9,
      maxOutputTokens: 4096,
      toolChoice: "auto",
      stop: ["END"],
      tools: [{ type: "function", function: { name: "mcp_list", description: "list", parameters: { type: "object", properties: {} } } }],
    },
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(request.url, "https://api.z.ai/api/paas/v4/chat/completions");
  const body = JSON.parse(request.options.body);
  assert.equal(body.temperature, 0.5);
  assert.equal(body.top_p, 0.9);
  assert.equal(body.max_tokens, 4096);
  assert.equal(body.tool_choice, "auto");
  assert.deepEqual(body.stop, ["END"]);

  // temperature 1.5 — за пределами [0, 1] Z.AI: громкая ошибка ДО сети
  let fetched = false;
  await assert.rejects(
    chatWithZai({
      credentials: { get: () => "secret-zai-key" },
      envelope: { provider: "zai", messages: [{ role: "user", content: "hi" }], temperature: 1.5 },
      fetchImpl: async () => { fetched = true; return okResponse; },
      environment: {},
    }),
    (error) => error.code === "UNSUPPORTED_CAPABILITY" && error.issues.some((i) => i.field === "temperature"),
  );
  assert.equal(fetched, false);
});

test("GLM-5.3 legacy minimal effort normalizes to low with a surfaced transport note", async () => {
  let request;
  const result = await chatWithGlm({
    credentials: { get: () => "secret-glm-key" },
    envelope: {
      provider: "glm",
      messages: [{ role: "user", content: "hi" }],
      reasoning: { effort: "minimal" },
    },
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  const body = JSON.parse(request.options.body);
  assert.deepEqual(body.thinking, { type: "enabled" }); // никогда не "disabled"
  assert.equal(body.reasoning_effort, "low");
  const note = result.transport.dropped.find((d) => d.field === "reasoning.effort");
  assert.ok(note && note.reason.includes("minimal") && note.reason.includes("low"));
});

test("Grok chat posts to api.x.ai with the stored key and grok-4.6 default", async () => {
  let request;
  const result = await chatWithGrok({
    credentials: { get: () => "secret-grok-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(result.content, '{"ok":true}');
  assert.equal(result.transport.provider, "grok");
  assert.equal(request.url, "https://api.x.ai/v1/chat/completions");
  assert.equal(request.options.headers.Authorization, "Bearer secret-grok-key");
  assert.equal(JSON.parse(request.options.body).model, "grok-4.6");
  assert.doesNotMatch(request.options.body, /secret-grok-key/);
});

test("Grok sends a stable x-grok-conv-id from the envelope id (cache affinity, no secrets)", async () => {
  const headers = [];
  const call = () => chatWithGrok({
    credentials: { get: () => "secret-grok-key" },
    envelope: { id: "conv-abc-123", provider: "grok", messages: [{ role: "user", content: "hi" }] },
    fetchImpl: async (url, options) => { headers.push(options.headers); return okResponse; },
    environment: {},
  });
  await call();
  await call();
  assert.equal(headers[0]["x-grok-conv-id"], "conv-abc-123");
  assert.equal(headers[1]["x-grok-conv-id"], "conv-abc-123"); // стабильность в рамках конверсации
  assert.equal(headers[0].Authorization, "Bearer secret-grok-key");
  assert.ok(!Object.values(headers[0]).some((v) => /secret-grok-key/.test(v) && !String(v).startsWith("Bearer ")));
});

test("Grok stop sequences fail loudly before any network call", async () => {
  let fetched = false;
  await assert.rejects(
    chatWithGrok({
      credentials: { get: () => "secret-grok-key" },
      envelope: { provider: "grok", messages: [{ role: "user", content: "hi" }], stop: ["END"] },
      fetchImpl: async () => { fetched = true; return okResponse; },
      environment: {},
    }),
    (error) => error.code === "UNSUPPORTED_CAPABILITY" && error.issues.some((i) => i.field === "stop"),
  );
  assert.equal(fetched, false);
});

test("Grok reasoning: xhigh passes through, minimal/max normalize with a surfaced note", async () => {
  const seen = [];
  const run = (effort) => chatWithGrok({
    credentials: { get: () => "secret-grok-key" },
    envelope: { provider: "grok", messages: [{ role: "user", content: "hi" }], reasoning: { effort } },
    fetchImpl: async (url, options) => { seen.push(JSON.parse(options.body)); return okResponse; },
    environment: {},
  });
  const direct = await run("xhigh");
  assert.equal(seen[0].reasoning_effort, "xhigh");
  assert.ok(!direct.transport.dropped.some((d) => d.field === "reasoning.effort"));
  const minimal = await run("minimal");
  assert.equal(seen[1].reasoning_effort, "low"); // reasoning cannot be disabled
  const max = await run("max");
  assert.equal(seen[2].reasoning_effort, "xhigh");
  for (const [result, from, to] of [[minimal, "minimal", "low"], [max, "max", "xhigh"]]) {
    const note = result.transport.dropped.find((d) => d.field === "reasoning.effort");
    assert.ok(note && note.reason.includes(from) && note.reason.includes(to), `normalization ${from}→${to} must be surfaced`);
  }
});

test("Grok reports an actionable missing-key error", async () => {
  await assert.rejects(
    chatWithGrok({ credentials: { get: () => null }, messages: [{ role: "user", content: "Generate" }] }),
    /Agents → Connections/,
  );
});

test("envelope round-trip: every parameter reaches the wire payload", async () => {
  let request;
  const result = await chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    envelope: {
      id: "corr-1",
      provider: "openai",
      model: "gpt-test-1",
      system: "be strict",
      messages: [{ role: "user", content: "hi" }],
      temperature: 0.25,
      topP: 0.9,
      maxOutputTokens: 777,
      reasoning: { effort: "low" },
      responseFormat: { type: "json_object" },
      stop: ["END"],
      seed: 42,
    },
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  const body = JSON.parse(request.options.body);
  assert.equal(body.model, "gpt-test-1");
  assert.equal(body.temperature, 0.25);
  assert.equal(body.top_p, 0.9);
  assert.equal(body.max_completion_tokens, 777);
  assert.equal(body.reasoning_effort, "low");
  assert.deepEqual(body.response_format, { type: "json_object" });
  assert.deepEqual(body.stop, ["END"]);
  assert.equal(body.seed, 42);
  assert.deepEqual(body.messages[0], { role: "system", content: "be strict" });
  assert.deepEqual(result.transport.dropped, []);
});

test("Kimi payload never forces response_format (k3 endpoint rejects it)", async () => {
  let request;
  await chatWithKimi({
    credentials: { get: () => "secret-kimi-key" },
    messages: [{ role: "user", content: "Generate JSON" }],
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.ok(!("response_format" in JSON.parse(request.options.body)));
});

test("seed 0 reaches the wire payload end-to-end", async () => {
  let request;
  await chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    envelope: { id: "seed0", provider: "openai", messages: [{ role: "user", content: "hi" }], seed: 0 },
    fetchImpl: async (url, options) => { request = { url, options }; return okResponse; },
    environment: {},
  });
  assert.equal(JSON.parse(request.options.body).seed, 0);
});

test("Grok chat returns tool_calls with call IDs", async () => {
  const toolResponse = {
    ok: true, status: 200,
    json: async () => ({
      choices: [{
        message: {
          content: "",
          tool_calls: [{ id: "call_grok_1", function: { name: "mcp_list", arguments: "{\"path\":\".\"}" } }],
        },
      }],
    }),
  };
  const result = await chatWithGrok({
    credentials: { get: () => "secret-grok-key" },
    envelope: {
      messages: [{ role: "user", content: "list files" }],
      tools: [{ type: "function", function: { name: "mcp_list", description: "list", parameters: { type: "object", properties: {} } } }],
    },
    fetchImpl: async () => toolResponse,
    environment: {},
  });
  assert.deepEqual(result.toolCalls, [{ id: "call_grok_1", name: "mcp_list", arguments: '{"path":"."}' }]);
});

test("external abort signal cancels the request with a structured code", async () => {
  const controller = new AbortController();
  const pending = chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    messages: [{ role: "user", content: "slow" }],
    fetchImpl: () => new Promise((_resolve, reject) => {
      controller.signal.addEventListener("abort", () => {
        const error = new Error("This operation was aborted");
        error.name = "AbortError";
        reject(error);
      });
    }),
    environment: {},
    signal: controller.signal,
  });
  controller.abort();
  await assert.rejects(pending, (error) => error.code === "PROVIDER_CANCELLED");
});

test("timeout produces a structured PROVIDER_TIMEOUT code", async () => {
  await assert.rejects(
    chatWithOpenAI({
      credentials: { get: () => "secret-openai-key" },
      envelope: { id: "t1", messages: [{ role: "user", content: "x" }], timeoutMs: 1500 },
      fetchImpl: (url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("The operation was aborted due to timeout");
          error.name = "AbortError";
          reject(error);
        });
      }),
      environment: {},
    }),
    (error) => error.code === "PROVIDER_TIMEOUT",
  );
});

test("Kimi chat now supports tools and returns tool_calls with call IDs", async () => {
  const toolResponse = {
    ok: true, status: 200,
    json: async () => ({
      choices: [{
        message: {
          content: "",
          tool_calls: [{ id: "call_kimi_1", function: { name: "mcp_list", arguments: "{\"path\":\".\"}" } }],
        },
      }],
    }),
  };
  const result = await chatWithKimi({
    credentials: { get: () => "secret-kimi-key" },
    envelope: {
      messages: [{ role: "user", content: "list files" }],
      tools: [{ type: "function", function: { name: "mcp_list", description: "list", parameters: { type: "object", properties: {} } } }],
    },
    fetchImpl: async () => toolResponse,
    environment: {},
  });
  assert.deepEqual(result.toolCalls, [{ id: "call_kimi_1", name: "mcp_list", arguments: '{"path":"."}' }]);
});

test("provider response tool_calls metadata is validated before any MCP call", async () => {
  const call = (toolCalls) => chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    messages: [{ role: "user", content: "hi" }],
    fetchImpl: async () => ({
      ok: true, status: 200,
      json: async () => ({ choices: [{ message: { content: "", tool_calls: toolCalls } }] }),
    }),
    environment: {},
  });
  const validCall = { id: "c1", type: "function", function: { name: "f", arguments: { a: 1 } } };
  const expectReject = async (toolCalls, fragment) => {
    let fetched = true;
    await assert.rejects(
      call(toolCalls).catch((error) => { fetched = false; throw error; }),
      (error) => error.code === "PROVIDER_TOOL_ARGS" && error.message.includes(fragment),
    );
    assert.equal(fetched, false, "must fail during extraction, before tool execution");
  };
  // лимит 32 вызова
  await expectReject(Array.from({ length: 33 }, (_, i) => ({ ...validCall, id: `c${i}` })), "more than 32");
  await expectReject(["not-an-object"], "must be an object");
  await expectReject([{ ...validCall, type: "retrieval" }], "unsupported tool_call type");
  await expectReject([{ ...validCall, function: null }], "must be an object");
  await expectReject([{ ...validCall, id: "" }], "non-empty string");
  await expectReject([{ ...validCall, id: "x".repeat(200) }], "128 UTF-8 bytes");
  await expectReject([{ ...validCall, function: { name: 7, arguments: {} } }], "non-empty string");
  await expectReject([validCall, validCall], "duplicate tool_call id");
  // валидный мультивызов проходит целиком
  const result = await call([validCall, { id: "c2", type: "function", function: { name: "g", arguments: '{"b":2}' } }]);
  assert.equal(result.toolCalls.length, 2);
  assert.equal(result.toolCalls[0].arguments, '{"a":1}');
  assert.equal(result.toolCalls[1].arguments, '{"b":2}');
});
