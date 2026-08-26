import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chatWithProvider } from "../services/provider-router.mjs";
import { createEnvelope } from "../services/provider-envelope.mjs";
import { chatWithOpenAI, chatWithZai } from "../services/provider-chat.mjs";
import { McpStdioClient } from "../services/mcp-client.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));

const credentials = (configured = []) => ({
  has: (provider) => configured.includes(provider),
  get: (provider) => configured.includes(provider) ? `test-${provider}-credential` : null,
});

const assistantWithToolCall = {
  role: "assistant",
  content: "",
  tool_calls: [{ id: "call_1", type: "function", function: { name: "mcp_srv__echo", arguments: '{"value":7}' } }],
};

const toolResult = {
  role: "tool",
  content: "{\"value\":7}",
  tool_call_id: "call_1",
  name: "mcp_srv__echo",
};

function makeProviderMock(provider) {
  return async ({ envelope }) => {
    const last = envelope.messages[envelope.messages.length - 1];
    const body = { provider, model: envelope.model || "default", messages: envelope.messages };
    if (last?.role === "tool") {
      return { content: `saw tool result for ${last.toolCallId || last.tool_call_id}`, toolCalls: null, transport: { provider, model: body.model, dropped: [] } };
    }
    return {
      content: "",
      toolCalls: [{ id: "call_1", name: "mcp_srv__echo", arguments: '{"value":7}' }],
      transport: { provider, model: body.model, dropped: [] },
    };
  };
}

for (const provider of ["openai", "kimi", "glm", "zai", "grok"]) {
  test(`${provider} returns toolCalls with preserved call id and passes tool history`, async () => {
    let captured;
    const result = await chatWithProvider({
      provider,
      messages: [{ role: "user", content: "use the echo tool" }],
      credentials: credentials([provider]),
      codex: { account: async () => ({ account: null }) },
      [`${provider}Chat`]: async (opts) => {
        captured = opts.envelope;
        return {
          content: "",
          toolCalls: [{ id: "call_abc", name: "mcp_srv__echo", arguments: '{"value":7}' }],
          transport: { provider, model: "m", dropped: [] },
        };
      },
    });
    assert.deepEqual(result.toolCalls, [{ id: "call_abc", name: "mcp_srv__echo", arguments: '{"value":7}' }]);
    assert.equal(result.transport.requestId, captured.id);
  });
}

for (const provider of ["openai", "kimi", "glm", "zai", "grok"]) {
  test(`${provider} two-round tool loop preserves tool_call_id, name and content`, async () => {
    const calls = [];
    const chat = async ({ envelope }) => {
      calls.push(envelope.messages);
      if (calls.length === 2) {
        const tool = envelope.messages.find((m) => m.role === "tool");
        return { content: `done after ${tool?.toolCallId || tool?.tool_call_id}`, toolCalls: null, transport: { provider, model: "m", dropped: [] } };
      }
      return {
        content: "",
        toolCalls: [{ id: "call_1", name: "mcp_srv__echo", arguments: '{"value":7}' }],
        transport: { provider, model: "m", dropped: [] },
      };
    };
    // Round 1: user asks, assistant requests a tool.
    const round1 = await chatWithProvider({
      provider,
      messages: [{ role: "user", content: "round 1" }],
      credentials: credentials([provider]),
      codex: { account: async () => ({ account: null }) },
      [`${provider}Chat`]: chat,
    });
    assert.deepEqual(round1.toolCalls, [{ id: "call_1", name: "mcp_srv__echo", arguments: '{"value":7}' }]);
    // Round 2: append assistant tool_call + tool result, send again.
    const round2 = await chatWithProvider({
      envelope: createEnvelope({
        provider,
        messages: [
          { role: "user", content: "round 1" },
          assistantWithToolCall,
          toolResult,
          { role: "user", content: "round 2" },
        ],
      }),
      credentials: credentials([provider]),
      codex: { account: async () => ({ account: null }) },
      [`${provider}Chat`]: chat,
    });
    assert.equal(calls.length, 2);
    const wire = calls[1];
    const assistant = wire.find((m) => m.role === "assistant");
    const tool = wire.find((m) => m.role === "tool");
    assert.ok(assistant.toolCalls?.length, "assistant message must carry toolCalls");
    assert.equal(assistant.toolCalls[0].id, "call_1");
    assert.equal(tool.toolCallId, "call_1");
    assert.equal(tool.toolName, "mcp_srv__echo");
    assert.equal(round2.content, "done after call_1");
  });
}

test("provider parameters survive the envelope round-trip for every OpenAI-compatible branch", async () => {
  for (const provider of ["openai", "kimi", "glm", "zai", "grok"]) {
    let captured;
    await chatWithProvider({
      provider,
      messages: [{ role: "user", content: "hi" }],
      temperature: 0.8,
      credentials: credentials([provider]),
      codex: { account: async () => ({ account: null }) },
      [`${provider}Chat`]: async ({ envelope }) => {
        captured = envelope;
        return { content: "ok", transport: { provider, model: "m", dropped: [] } };
      },
    });
    assert.equal(captured.provider, provider);
    assert.equal(captured.temperature, 0.8);
    assert.equal(captured.messages[0].role, "user");
  }
});

test("OpenAI-compatible wire payload preserves assistant tool_calls and tool messages", async () => {
  let request;
  const okResponse = { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "ok" } }] }) };
  await chatWithOpenAI({
    credentials: { get: () => "secret-openai-key" },
    envelope: createEnvelope({
      provider: "openai",
      messages: [
        { role: "user", content: "call echo" },
        assistantWithToolCall,
        toolResult,
      ],
    }),
    fetchImpl: async (_url, options) => { request = options; return okResponse; },
    environment: {},
  });
  const body = JSON.parse(request.body);
  const assistant = body.messages.find((m) => m.role === "assistant");
  const tool = body.messages.find((m) => m.role === "tool");
  assert.ok(assistant.tool_calls, "wire assistant must have tool_calls");
  assert.equal(assistant.tool_calls[0].id, "call_1");
  assert.equal(tool.tool_call_id, "call_1");
  assert.equal(tool.name, "mcp_srv__echo");
  assert.equal(tool.content, '{"value":7}');
});

test("real two-round MCP loop against the local stdio fixture keeps call correlation", async () => {
  // No transport mocks: the tool executes against the real fixture process,
  // and its real result goes back onto the wire in round 2 — in the exact
  // camelCase history shape the AgentWorkspace resubmits.
  const mcp = new McpStdioClient({
    id: "fixture",
    command: process.execPath,
    args: [path.join(directory, "fixtures", "mcp-server.mjs")],
    cwd: directory,
  });
  try {
    // Round 1: provider requests the tool; it runs against the real fixture.
    const round1 = await chatWithProvider({
      provider: "openai",
      messages: [{ role: "user", content: "echo 7" }],
      credentials: credentials(["openai"]),
      codex: { account: async () => ({ account: null }) },
      openaiChat: async () => ({
        content: "",
        toolCalls: [{ id: "call_rt1", name: "mcp_fixture__echo", arguments: '{"value":7}' }],
        transport: { provider: "openai", model: "m", dropped: [] },
      }),
    });
    const call = round1.toolCalls[0];
    const result = await mcp.callTool("echo", JSON.parse(call.arguments), { correlationId: call.id });
    const toolText = result.content[0].text;
    assert.equal(toolText, '{"value":7}');
    // Round 2: the real tool result is correlated back onto the wire payload.
    let request;
    const okResponse = { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "done" } }] }) };
    await chatWithOpenAI({
      credentials: { get: () => "secret-openai-key" },
      envelope: createEnvelope({
        provider: "openai",
        messages: [
          { role: "user", content: "echo 7" },
          { role: "assistant", content: round1.content, toolCalls: round1.toolCalls },
          { role: "tool", content: toolText, toolCallId: call.id, toolName: call.name },
        ],
      }),
      fetchImpl: async (_url, options) => { request = options; return okResponse; },
      environment: {},
    });
    const body = JSON.parse(request.body);
    const assistant = body.messages.find((m) => m.role === "assistant");
    const tool = body.messages.find((m) => m.role === "tool");
    assert.equal(assistant.tool_calls[0].id, "call_rt1");
    assert.equal(tool.tool_call_id, "call_rt1");
    assert.equal(tool.name, "mcp_fixture__echo");
    assert.equal(tool.content, '{"value":7}');
  } finally { mcp.stop(); }
});

test("Z.AI GLM-5.3 object arguments canonicalize, then round two resubmits exact bytes + correlation", async () => {
  // Official Z.AI response shape: function.arguments is an OBJECT.
  const fixture = JSON.parse(readFileSync(path.join(directory, "fixtures", "zai-glm53-toolcall-response.json"), "utf-8"));
  const zaiResponse = { ok: true, status: 200, json: async () => fixture };
  const round1 = await chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    envelope: { id: "conv-zai-1", provider: "zai", messages: [{ role: "user", content: "echo 7" }] },
    fetchImpl: async () => zaiResponse,
    environment: {},
  });
  const call = round1.toolCalls[0];
  assert.equal(call.id, "call_zai_obj_1");
  // deterministic canonical JSON: recursively sorted keys, no "[object Object]"
  const canonicalArgs = '{"options":{"depth":2,"verbose":true},"path":"./src","value":7}';
  assert.equal(call.arguments, canonicalArgs);

  // Round two: resubmit in the exact UI camelCase history shape; outbound
  // payload must carry byte-identical arguments and the matching tool_call_id.
  let request;
  const okResponse = { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "done" } }] }) };
  await chatWithZai({
    credentials: { get: () => "secret-zai-key" },
    envelope: createEnvelope({
      id: "conv-zai-1",
      provider: "zai",
      messages: [
        { role: "user", content: "echo 7" },
        { role: "assistant", content: round1.content, toolCalls: round1.toolCalls },
        { role: "tool", content: '{"value":7}', toolCallId: call.id, toolName: call.name },
      ],
    }),
    fetchImpl: async (_url, options) => { request = options; return okResponse; },
    environment: {},
  });
  const body = JSON.parse(request.body);
  const assistant = body.messages.find((m) => m.role === "assistant");
  const tool = body.messages.find((m) => m.role === "tool");
  assert.equal(assistant.tool_calls[0].function.arguments, canonicalArgs); // byte-exact
  assert.equal(tool.tool_call_id, "call_zai_obj_1");
  assert.equal(tool.name, "mcp_fixture__echo");
});

test("malformed Z.AI tool_call arguments fail closed with a structured code before MCP execution", async () => {
  const badResponse = {
    ok: true, status: 200,
    json: async () => ({ choices: [{ message: { content: "", tool_calls: [{ id: "c1", function: { name: "x", arguments: null } }] } }] }),
  };
  let mcpTouched = false;
  await assert.rejects(
    chatWithZai({
      credentials: { get: () => "secret-zai-key" },
      envelope: { provider: "zai", messages: [{ role: "user", content: "hi" }] },
      fetchImpl: async () => { return badResponse; },
      environment: {},
    }).then(() => { mcpTouched = true; }),
    (error) => error.code === "PROVIDER_TOOL_ARGS" && typeof error.field === "string" && error.field.includes("arguments"),
  );
  assert.equal(mcpTouched, false);
});

test("integration with a real MCP stub: malformed metadata never executes a tool, valid object args execute exactly once", async () => {
  const mcp = new McpStdioClient({
    id: "fixture",
    command: process.execPath,
    args: [path.join(directory, "fixtures", "mcp-server.mjs")],
    cwd: directory,
  });
  let executed = 0;
  const guardedCall = async (name, args, options) => { executed += 1; return mcp.callTool(name, args, options); };
  try {
    await mcp.connect();
    // malformed metadata (duplicate ids) — адаптер отвергает ДО MCP-вызова
    const dupResponse = {
      ok: true, status: 200,
      json: async () => ({
        choices: [{
          message: {
            content: "",
            tool_calls: [
              { id: "dup", type: "function", function: { name: "mcp_fixture__echo", arguments: { value: 1 } } },
              { id: "dup", type: "function", function: { name: "mcp_fixture__echo", arguments: { value: 2 } } },
            ],
          },
        }],
      }),
    };
    await assert.rejects(
      chatWithZai({
        credentials: { get: () => "secret-zai-key" },
        envelope: { provider: "zai", messages: [{ role: "user", content: "hi" }] },
        fetchImpl: async () => dupResponse,
        environment: {},
      }),
      (error) => error.code === "PROVIDER_TOOL_ARGS" && error.message.includes("duplicate"),
    );
    assert.equal(executed, 0);
    // контроль: валидные object arguments из фикстуры Z.AI выполняют ровно
    // один реальный вызов с каноническими байтами arguments
    const fixture = JSON.parse(readFileSync(path.join(directory, "fixtures", "zai-glm53-toolcall-response.json"), "utf-8"));
    const round1 = await chatWithZai({
      credentials: { get: () => "secret-zai-key" },
      envelope: { provider: "zai", messages: [{ role: "user", content: "echo" }] },
      fetchImpl: async () => ({ ok: true, status: 200, json: async () => fixture }),
      environment: {},
    });
    const call = round1.toolCalls[0];
    const result = await guardedCall("echo", JSON.parse(call.arguments), { correlationId: call.id });
    assert.equal(executed, 1);
    assert.deepEqual(JSON.parse(result.content[0].text), { options: { depth: 2, verbose: true }, path: "./src", value: 7 });
  } finally { mcp.stop(); }
});
