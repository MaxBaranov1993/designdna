import assert from "node:assert/strict";
import test from "node:test";
import {
  adaptEnvelopeForProvider,
  assertEnvelopeSupported,
  buildOpenAiCompatiblePayload,
  createEnvelope,
  EnvelopeValidationError,
  redactForLog,
  UnsupportedCapabilityError,
} from "../services/provider-envelope.mjs";

test("createEnvelope validates every field and reports all issues at once", () => {
  assert.throws(
    () => createEnvelope({ messages: [], temperature: 5, topP: 2, seed: -1, reasoning: { effort: "extreme" } }),
    (error) => {
      assert.ok(error instanceof EnvelopeValidationError);
      const fields = error.issues.map((i) => i.field);
      for (const expected of ["messages", "temperature", "topP", "seed", "reasoning.effort"]) {
        assert.ok(fields.includes(expected), `missing issue for ${expected}`);
      }
      return true;
    },
  );
});

test("createEnvelope keeps multimodal content parts structured", () => {
  const envelope = createEnvelope({
    provider: "openai",
    messages: [{
      role: "user",
      content: [
        { type: "text", text: "describe" },
        { type: "image_url", image_url: { url: "data:image/png;base64,aGk=" } },
      ],
    }],
  });
  assert.equal(envelope.messages[0].content.length, 2);
  assert.equal(envelope.messages[0].content[1].type, "image_url");
  assert.ok(envelope.id);
});

test("system prompt, stop sequences and tools survive normalization", () => {
  const envelope = createEnvelope({
    system: "be brief",
    messages: [{ role: "user", content: "hi" }],
    stop: ["END"],
    tools: [{ type: "function", function: { name: "lookup", description: "d", parameters: { type: "object" } } }],
  });
  assert.equal(envelope.system, "be brief");
  assert.deepEqual(envelope.stop, ["END"]);
  assert.equal(envelope.tools[0].function.name, "lookup");
});

test("hard-unsupported fields fail loudly instead of being dropped", () => {
  const envelope = createEnvelope({
    provider: "zcode",
    messages: [{ role: "user", content: "hi" }],
    tools: [{ type: "function", function: { name: "x", parameters: { type: "object" } } }],
  });
  assert.throws(
    () => assertEnvelopeSupported(envelope, "zcode"),
    (error) => {
      assert.ok(error instanceof UnsupportedCapabilityError);
      assert.equal(error.code, "UNSUPPORTED_CAPABILITY");
      assert.deepEqual(error.issues.map((i) => i.field), ["tools"]);
      return true;
    },
  );
});

test("kimi value-level adaptation reports every removed parameter", () => {
  const envelope = createEnvelope({
    provider: "kimi",
    messages: [{ role: "user", content: "hi" }],
    temperature: 0.4,
    topP: 0.9,
    stop: ["END"],
    seed: 7,
    reasoning: { effort: "high" },
    responseFormat: { type: "json_object" },
  });
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "kimi");
  assert.equal(adapted.temperature, null);
  assert.equal(adapted.topP, null);
  assert.equal(adapted.reasoning, null);
  const fields = dropped.map((d) => d.field);
  for (const expected of ["temperature", "topP", "reasoning", "responseFormat", "stop", "seed"]) {
    assert.ok(fields.includes(expected), `kimi drop list missing ${expected}`);
  }
  for (const entry of dropped) assert.ok(entry.reason.length > 10, "drop reason must explain itself");
});

test("kimi keeps temperature=1 (the only accepted value)", () => {
  const envelope = createEnvelope({
    provider: "kimi",
    messages: [{ role: "user", content: "hi" }],
    temperature: 1,
  });
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "kimi");
  assert.equal(adapted.temperature, 1);
  assert.equal(dropped.length, 0);
});

test("glm maps reasoning effort to thinking and reports budget removal", () => {
  const envelope = createEnvelope({
    provider: "glm",
    messages: [{ role: "user", content: "hi" }],
    reasoning: { effort: "high", budgetTokens: 4096 },
  });
  const { envelope: adapted, dropped: adaptDropped } = adaptEnvelopeForProvider(envelope, "glm");
  const { payload, dropped: buildDropped } = buildOpenAiCompatiblePayload(adapted, "glm", { defaultModel: "glm-5.3" });
  assert.deepEqual(payload.thinking, { type: "enabled" });
  assert.equal(payload.reasoning_effort, "high");
  const dropped = [...adaptDropped, ...buildDropped];
  assert.ok(dropped.some((d) => d.field === "reasoning.budgetTokens"));
});

test("glm/zai never emit thinking disabled; legacy efforts normalize with an explicit note", () => {
  for (const provider of ["glm", "zai"]) {
    for (const [legacy, mapped] of [["minimal", "low"], ["medium", "high"]]) {
      const envelope = createEnvelope({
        provider,
        messages: [{ role: "user", content: "hi" }],
        reasoning: { effort: legacy },
      });
      const { envelope: adapted } = adaptEnvelopeForProvider(envelope, provider);
      const { payload, dropped } = buildOpenAiCompatiblePayload(adapted, provider, { defaultModel: "glm-5.3" });
      assert.deepEqual(payload.thinking, { type: "enabled" }, `${provider}/${legacy} must stay enabled`);
      assert.equal(payload.reasoning_effort, mapped);
      const note = dropped.find((d) => d.field === "reasoning.effort");
      assert.ok(note, `${provider}/${legacy} must record the normalization`);
      assert.ok(note.reason.includes(legacy) && note.reason.includes(mapped));
    }
    for (const effort of ["low", "high", "max"]) {
      const envelope = createEnvelope({
        provider,
        messages: [{ role: "user", content: "hi" }],
        reasoning: { effort },
      });
      const { envelope: adapted } = adaptEnvelopeForProvider(envelope, provider);
      const { payload, dropped } = buildOpenAiCompatiblePayload(adapted, provider, { defaultModel: "glm-5.3" });
      assert.deepEqual(payload.thinking, { type: "enabled" });
      assert.equal(payload.reasoning_effort, effort);
      assert.ok(!dropped.some((d) => d.field === "reasoning.effort"), `${provider}/${effort} passes through unmodified`);
    }
  }
});

test("grok-4.6 contract: xhigh passthrough, explicit legacy normalization, stop hard-fail", () => {
  const base = { provider: "grok", messages: [{ role: "user", content: "hi" }] };
  // stop несовместим с grok-4.6 — громко, до сети
  assert.throws(
    () => assertEnvelopeSupported(createEnvelope({ ...base, stop: ["END"] }), "grok"),
    (error) => error instanceof UnsupportedCapabilityError && error.issues.some((i) => i.field === "stop"),
  );
  // tools, parallel_tool_calls и json_schema остаются поддерживаемыми
  const withTools = createEnvelope({
    ...base,
    tools: [{ type: "function", function: { name: "t", parameters: { type: "object" } } }],
    parallelToolCalls: true,
    reasoning: { effort: "xhigh" },
  });
  assert.doesNotThrow(() => assertEnvelopeSupported(withTools, "grok"));
  const { payload: toolsPayload } = buildOpenAiCompatiblePayload(withTools, "grok", { defaultModel: "grok-4.6" });
  assert.equal(toolsPayload.parallel_tool_calls, true);
  assert.ok(Array.isArray(toolsPayload.tools));
  assert.equal(toolsPayload.reasoning_effort, "xhigh");
  const withSchema = createEnvelope({
    ...base,
    responseFormat: { type: "json_schema", jsonSchema: { name: "o", schema: { type: "object" } } },
  });
  assert.doesNotThrow(() => assertEnvelopeSupported(withSchema, "grok"));
  const { payload: schemaPayload } = buildOpenAiCompatiblePayload(withSchema, "grok", { defaultModel: "grok-4.6" });
  assert.equal(schemaPayload.response_format.type, "json_schema");
  // legacy canonical значения нормализуются явно, не молча
  for (const [legacy, mapped] of [["minimal", "low"], ["max", "xhigh"]]) {
    const envelope = createEnvelope({ ...base, reasoning: { effort: legacy } });
    const { payload: p, dropped } = buildOpenAiCompatiblePayload(envelope, "grok", { defaultModel: "grok-4.6" });
    assert.equal(p.reasoning_effort, mapped);
    const note = dropped.find((d) => d.field === "reasoning.effort");
    assert.ok(note && note.reason.includes(legacy) && note.reason.includes(mapped));
  }
});

test("zai enforces the official GLM-5.3 value constraints before any network call", () => {
  const base = { provider: "zai", messages: [{ role: "user", content: "hi" }] };
  const expectLoud = (overrides, field) => {
    const envelope = createEnvelope({ ...base, ...overrides });
    assert.throws(
      () => assertEnvelopeSupported(envelope, "zai"),
      (error) => error instanceof UnsupportedCapabilityError
        && error.issues.some((i) => i.field === field),
      `${field} must fail loudly`,
    );
  };
  expectLoud({ temperature: 1.5 }, "temperature");        // Z.AI: [0, 1]
  expectLoud({ topP: 0.005 }, "topP");                    // Z.AI: [0.01, 1]
  expectLoud({ maxOutputTokens: 200_000 }, "maxOutputTokens"); // Z.AI: ≤ 131072
  expectLoud({ toolChoice: "required" }, "toolChoice");   // Z.AI: только auto
  expectLoud({ toolChoice: { name: "t" } }, "toolChoice");
  expectLoud({ responseFormat: { type: "json_schema", jsonSchema: { name: "o", schema: { type: "object" } } } }, "responseFormat");
  expectLoud({ stop: ["A", "B"] }, "stop");               // Z.AI: одно stop-слово

  // валидные значения доходят до wire без потерь
  const valid = createEnvelope({
    ...base,
    temperature: 1,
    topP: 0.95,
    maxOutputTokens: 131_072,
    toolChoice: "auto",
    responseFormat: { type: "json_object" },
    stop: ["END"],
    tools: [{ type: "function", function: { name: "t", parameters: { type: "object" } } }],
  });
  assert.doesNotThrow(() => assertEnvelopeSupported(valid, "zai"));
  const { envelope: adapted } = adaptEnvelopeForProvider(valid, "zai");
  const { payload } = buildOpenAiCompatiblePayload(adapted, "zai", { defaultModel: "glm-5.3" });
  assert.equal(payload.temperature, 1);
  assert.equal(payload.top_p, 0.95);
  assert.equal(payload.max_tokens, 131_072);
  assert.equal(payload.tool_choice, "auto");
  assert.deepEqual(payload.stop, ["END"]);
  // tools + response_format несовместимы на wire — формат снят явно (см. dropped)
  assert.ok(!("response_format" in payload));
});

test("zhipu glm keeps its own looser value contract (scoped separately from Z.AI)", () => {
  // Zhipu bigmodel.cn per-parameter constraints are not verified from its
  // current docs — glm deliberately does NOT inherit the Z.AI-only ranges.
  const envelope = createEnvelope({
    provider: "glm",
    messages: [{ role: "user", content: "hi" }],
    temperature: 1.5,
    toolChoice: { name: "t" },
    tools: [{ type: "function", function: { name: "t", parameters: { type: "object" } } }],
  });
  assert.doesNotThrow(() => assertEnvelopeSupported(envelope, "glm"));
});

test("zai shares the GLM v4 capability family (thinking mapping, seed drop, parallel hard-fail)", () => {
  const envelope = createEnvelope({
    provider: "zai",
    messages: [{ role: "user", content: "hi" }],
    reasoning: { effort: "low" },
    seed: 42,
  });
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "zai");
  assert.equal(adapted.seed, null);
  assert.ok(dropped.some((d) => d.field === "seed"));
  const { payload } = buildOpenAiCompatiblePayload(adapted, "zai", { defaultModel: "glm-5.3" });
  assert.deepEqual(payload.thinking, { type: "enabled" });
  assert.ok(!("seed" in payload));
  assert.equal(payload.reasoning_effort, "low");

  const parallel = createEnvelope({
    provider: "zai",
    messages: [{ role: "user", content: "hi" }],
    tools: [{ type: "function", function: { name: "t", parameters: { type: "object" } } }],
    parallelToolCalls: true,
  });
  assert.throws(
    () => assertEnvelopeSupported(parallel, "zai"),
    (error) => error instanceof UnsupportedCapabilityError && error.issues.some((i) => i.field === "parallelToolCalls"),
  );
});

test("openai payload round-trips the full parameter surface", () => {
  const envelope = createEnvelope({
    provider: "openai",
    model: "gpt-test",
    system: "sys",
    messages: [{ role: "user", content: "hi" }],
    temperature: 0.3,
    topP: 0.8,
    maxOutputTokens: 512,
    reasoning: { effort: "low" },
    responseFormat: { type: "json_schema", jsonSchema: { name: "out", schema: { type: "object" } } },
    stop: ["END"],
    seed: 42,
    toolChoice: "auto",
    parallelToolCalls: false,
  });
  const { payload, dropped } = buildOpenAiCompatiblePayload(envelope, "openai", { defaultModel: "x" });
  assert.equal(payload.model, "gpt-test");
  assert.equal(payload.max_completion_tokens, 512);        // openai-специфичное имя
  assert.equal(payload.reasoning_effort, "low");
  assert.deepEqual(payload.response_format, { type: "json_schema", json_schema: { name: "out", schema: { type: "object" } } });
  assert.deepEqual(payload.stop, ["END"]);
  assert.equal(payload.seed, 42);
  assert.equal(payload.top_p, 0.8);
  assert.equal(payload.tool_choice, "auto");
  assert.equal(payload.parallel_tool_calls, false);
  assert.deepEqual(payload.messages[0], { role: "system", content: "sys" });
  assert.deepEqual(payload.messages[1], { role: "user", content: "hi" });
  assert.equal(dropped.length, 0);
});

test("non-openai providers use max_tokens and named tool_choice", () => {
  const envelope = createEnvelope({
    provider: "grok",
    messages: [{ role: "user", content: "hi" }],
    maxOutputTokens: 128,
    tools: [{ type: "function", function: { name: "t", parameters: { type: "object" } } }],
    toolChoice: { name: "t" },
  });
  const { payload } = buildOpenAiCompatiblePayload(envelope, "grok", { defaultModel: "grok-4.6" });
  assert.equal(payload.max_tokens, 128);
  assert.deepEqual(payload.tool_choice, { type: "function", function: { name: "t" } });
  // tools + форсированный формат ответа несовместимы — формат снимается явно
  assert.ok(!("response_format" in payload));
});

test("foreign providerOptions are not sent to another provider", () => {
  const envelope = createEnvelope({
    provider: "openai",
    messages: [{ role: "user", content: "hi" }],
    providerOptions: { openai: { verbosity: "high" }, glm: { do_sample: false } },
  });
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "openai");
  assert.deepEqual(Object.keys(adapted.providerOptions), ["openai"]);
  assert.ok(dropped.some((d) => d.field === "providerOptions.glm"));
  const { payload } = buildOpenAiCompatiblePayload(adapted, "openai", { defaultModel: "m" });
  assert.equal(payload.verbosity, "high");
});

test("redactForLog strips credential-like values at any depth", () => {
  const redacted = redactForLog({
    apiKey: "sk-secret1234567890",
    nested: { Authorization: "Bearer abc", note: "fine" },
    list: [{ token: "t" }],
  });
  assert.equal(redacted.apiKey, "[redacted]");
  assert.equal(redacted.nested.Authorization, "[redacted]");
  assert.equal(redacted.nested.note, "fine");
  assert.equal(redacted.list[0].token, "[redacted]");
});

test("streaming requests are rejected explicitly (no web-only paths)", () => {
  assert.throws(
    () => createEnvelope({ messages: [{ role: "user", content: "hi" }], stream: true }),
    /streaming is not supported/,
  );
});

test("seed 0 survives validation, adaptation and payload (no falsy drops)", () => {
  const envelope = createEnvelope({
    provider: "openai",
    messages: [{ role: "user", content: "hi" }],
    seed: 0,
  });
  assert.equal(envelope.seed, 0);
  const { envelope: adapted, dropped } = adaptEnvelopeForProvider(envelope, "openai");
  assert.equal(adapted.seed, 0);
  assert.equal(dropped.length, 0);
  const { payload } = buildOpenAiCompatiblePayload(adapted, "openai", { defaultModel: "m" });
  assert.equal(payload.seed, 0);
});

test("UI camelCase tool history (toolCalls/toolCallId) normalizes to the wire shape", () => {
  // This is the exact message shape the desktop AgentWorkspace resubmits on
  // round 2+ of the agent loop — it must not lose the assistant tool calls.
  const envelope = createEnvelope({
    provider: "openai",
    messages: [
      { role: "user", content: "call echo" },
      { role: "assistant", content: "", toolCalls: [{ id: "call_1", name: "echo", arguments: "{\"value\":7}" }] },
      { role: "tool", content: "{\"value\":7}", toolCallId: "call_1", toolName: "echo" },
    ],
  });
  const { payload } = buildOpenAiCompatiblePayload(envelope, "openai", { defaultModel: "m" });
  const assistant = payload.messages[1];
  assert.deepEqual(assistant.tool_calls, [
    { id: "call_1", type: "function", function: { name: "echo", arguments: "{\"value\":7}" } },
  ]);
  const tool = payload.messages[2];
  assert.equal(tool.role, "tool");
  assert.equal(tool.tool_call_id, "call_1");
  assert.equal(tool.name, "echo");
  assert.equal(tool.content, "{\"value\":7}");
});

test("multimodal content is rejected loudly on text-only transports (codex, zcode)", () => {
  const envelope = createEnvelope({
    provider: "codex",
    messages: [{
      role: "user",
      content: [
        { type: "text", text: "describe" },
        { type: "image_url", image_url: { url: "data:image/png;base64,aGk=" } },
      ],
    }],
  });
  for (const provider of ["codex", "zcode"]) {
    assert.throws(
      () => assertEnvelopeSupported(envelope, provider),
      (error) => {
        assert.ok(error instanceof UnsupportedCapabilityError);
        assert.ok(error.issues.some((i) => i.field === "multimodal"));
        return true;
      },
    );
  }
  // OpenAI-compatible providers transport image parts unchanged.
  assert.doesNotThrow(() => assertEnvelopeSupported(envelope, "openai"));
  const { payload } = buildOpenAiCompatiblePayload(envelope, "openai", { defaultModel: "m" });
  assert.equal(payload.messages[0].content[1].type, "image_url");
});

test("tool_call arguments: objects canonicalize deterministically, strings pass verbatim, nothing truncates", () => {
  const roundTrip = (argumentsValue) => createEnvelope({
    provider: "openai",
    messages: [
      { role: "user", content: "x" },
      { role: "assistant", content: "", tool_calls: [{ id: "c1", type: "function", function: { name: "f", arguments: argumentsValue } }] },
      { role: "tool", content: "{}", tool_call_id: "c1", name: "f" },
    ],
  });
  // два порядка ключей → одинаковые байты
  const a = roundTrip({ b: 1, a: { d: 2, c: [3, 4] } });
  const b = roundTrip({ a: { c: [3, 4], d: 2 }, b: 1 });
  const argsA = a.messages[1].toolCalls[0].function.arguments;
  assert.equal(argsA, b.messages[1].toolCalls[0].function.arguments);
  assert.equal(argsA, '{"a":{"c":[3,4],"d":2},"b":1}');
  // строка — дословно (даже не-каноническая)
  const raw = '{ "z": 1,  "a":2 }';
  assert.equal(roundTrip(raw).messages[1].toolCalls[0].function.arguments, raw);
  // длинная валидная строка НЕ усекается
  const longValid = `{"pad":"${"x".repeat(15_000)}"}`;
  assert.equal(roundTrip(longValid).messages[1].toolCalls[0].function.arguments, longValid);
});

test("tool_call arguments: null, primitive, cyclic, non-serializable and oversized fail closed with a field", () => {
  const expectInvalid = (argumentsValue, fragment) => {
    assert.throws(
      () => createEnvelope({
        provider: "openai",
        messages: [
          { role: "user", content: "x" },
          { role: "assistant", content: "", tool_calls: [{ id: "c1", type: "function", function: { name: "f", arguments: argumentsValue } }] },
        ],
      }),
      (error) => {
        assert.ok(error instanceof EnvelopeValidationError);
        const hit = error.issues.find((i) => i.field.includes("tool_calls") && i.field.includes("arguments"));
        assert.ok(hit, `expected an arguments issue, got ${JSON.stringify(error.issues)}`);
        assert.ok(hit.message.includes(fragment), `${hit.message} must mention ${fragment}`);
        return true;
      },
    );
  };
  expectInvalid(null, "null");
  expectInvalid(42, "primitive");
  expectInvalid(true, "primitive");
  expectInvalid("x".repeat(16_001), "exceeds");
  const cyclic = { a: 1 };
  cyclic.self = cyclic;
  expectInvalid(cyclic, "cyclic");
  expectInvalid({ fn: () => 1 }, "non-serializable");
  expectInvalid({ when: new Date(0) }, "non-plain");
});

test("tool_call arguments: string is JSON-validated and UTF-8 byte limits apply", () => {
  const roundTrip = (argumentsValue) => createEnvelope({
    provider: "openai",
    messages: [
      { role: "user", content: "x" },
      { role: "assistant", content: "", tool_calls: [{ id: "c1", type: "function", function: { name: "f", arguments: argumentsValue } }] },
    ],
  });
  const expectInvalid = (value, fragment) => assert.throws(
    () => roundTrip(value),
    (error) => error instanceof EnvelopeValidationError
      && error.issues.some((i) => i.field.includes("arguments") && i.message.includes(fragment)),
  );
  // malformed JSON и закодированные null/примитивы отвергаются
  expectInvalid("{bad json", "malformed");
  expectInvalid("null", "object or array");
  expectInvalid("42", "object or array");
  expectInvalid('"just a string"', "object or array");
  // массив — валидная форма, байты дословно
  assert.equal(roundTrip("[1,2]").messages[1].toolCalls[0].function.arguments, "[1,2]");
  // лимит — UTF-8 БАЙТЫ: 5333 трёхбайтовых символа (~16 КБ) отвергаются,
  // хотя по code points это меньше лимита
  expectInvalid(`{"k":"${"€".repeat(5333)}"}`, "UTF-8 bytes");
  const multibyteOk = `{"k":"${"€".repeat(4000)}"}`;
  assert.equal(roundTrip(multibyteOk).messages[1].toolCalls[0].function.arguments, multibyteOk);
});

test("tool_call arguments: sparse arrays follow JSON semantics, symbols fail closed", () => {
  const sparse = { a: [,,] }; // eslint-disable-line no-sparse-arrays
  const envelope = createEnvelope({
    provider: "openai",
    messages: [
      { role: "user", content: "x" },
      { role: "assistant", content: "", tool_calls: [{ id: "c1", type: "function", function: { name: "f", arguments: sparse } }] },
    ],
  });
  assert.equal(envelope.messages[1].toolCalls[0].function.arguments, '{"a":[null,null]}');
  assert.throws(
    () => createEnvelope({
      provider: "openai",
      messages: [
        { role: "user", content: "x" },
        { role: "assistant", content: "", tool_calls: [{ id: "c1", type: "function", function: { name: "f", arguments: { s: Symbol("x") } } }] },
      ],
    }),
    (error) => error instanceof EnvelopeValidationError
      && error.issues.some((i) => i.field.includes("arguments") && i.message.includes("non-serializable")),
  );
});

test("matrix: every previously silent truncation/clamp is now a structured issue", () => {
  const expectIssue = (input, field, fragment) => assert.throws(
    () => createEnvelope(input),
    (error) => {
      assert.ok(error instanceof EnvelopeValidationError, field);
      const hit = error.issues.find((i) => i.field === field || i.field.startsWith(`${field}`));
      assert.ok(hit, `expected issue for ${field}, got ${JSON.stringify(error.issues.map((i) => i.field))}`);
      if (fragment) assert.ok(hit.message.includes(fragment), `${hit.message} must mention ${fragment}`);
      return true;
    },
  );
  const user = { role: "user", content: "hi" };
  // количества
  expectIssue({ messages: Array.from({ length: 129 }, () => user) }, "messages", "128");
  expectIssue({ messages: [{ role: "user", content: Array.from({ length: 33 }, () => ({ type: "text", text: "x" })) }] }, "messages[0].content", "32");
  expectIssue({ messages: [user, { role: "assistant", content: "a", tool_calls: Array.from({ length: 33 }, (_, i) => ({ id: `c${i}`, function: { name: "f", arguments: "{}" } })) }] }, "messages[1].tool_calls", "32");
  expectIssue({ messages: [user], stop: ["a", "b", "c", "d", "e"] }, "stop", "4");
  // длины (UTF-8 байты)
  expectIssue({ system: "x".repeat(400_001), messages: [user] }, "system", "UTF-8 bytes");
  expectIssue({ messages: [{ role: "user", content: "x".repeat(400_001) }] }, "messages[0].content", "UTF-8 bytes");
  expectIssue({ messages: [{ role: "user", content: [{ type: "image_url", image_url: { url: `https://example.com/${"i".repeat(8_000_100)}` } }] }] }, "messages[0].content[0]", "UTF-8 bytes");
  expectIssue({ messages: [user, { role: "tool", content: "{}", tool_call_id: "x".repeat(200), name: "f" }] }, "messages[1].tool_call_id", "128");
  expectIssue({ messages: [user, { role: "assistant", content: "", tool_calls: [{ id: "x".repeat(200), function: { name: "f", arguments: "{}" } }] }] }, "messages[1].tool_calls[0].id", "128");
  expectIssue({ messages: [user, { role: "assistant", content: "", tool_calls: [{ id: "c", function: { name: "f".padEnd(200, "n"), arguments: "{}" } }] }] }, "messages[1].tool_calls[0].function.name", "128");
  expectIssue({ messages: [user], tools: [{ type: "function", function: { name: "t", description: "d".repeat(2000), parameters: {} } }] }, "tools[0].function.description", "1024");
  expectIssue({ messages: [user], responseFormat: { type: "json_schema", jsonSchema: { name: "n".repeat(200), schema: {} } } }, "responseFormat.jsonSchema.name", "128");
  expectIssue({ messages: [user], toolChoice: { name: "t".padEnd(200, "x") } }, "toolChoice.name", "128");
  expectIssue({ messages: [user], stop: ["s".repeat(300)] }, "stop[0]", "256");
  expectIssue({ messages: [user], metadata: Object.fromEntries(Array.from({ length: 17 }, (_, i) => [`k${i}`, "v"])) }, "metadata", "16");
  expectIssue({ messages: [user], metadata: { ["k".repeat(100)]: "v" } }, "metadata", "64");
  expectIssue({ messages: [user], metadata: { k: "v".repeat(300) } }, "metadata.k", "256");
  // timeout выше MAX — громко, не clamp
  expectIssue({ messages: [user], timeoutMs: 600_001 }, "timeoutMs", "600000");
  // неизвестное верхнеуровневое поле — громко
  expectIssue({ messages: [user], frequencyPenalty: 0.5 }, "frequencyPenalty", "unknown envelope field");
});

test("matrix: providerOptions reserved overrides and unsafe values are rejected loudly", () => {
  const user = { role: "user", content: "hi" };
  const expectIssue = (options, fragment) => assert.throws(
    () => createEnvelope({ provider: "openai", messages: [user], providerOptions: options }),
    (error) => {
      assert.ok(error instanceof EnvelopeValidationError);
      assert.ok(error.issues.some((i) => i.message.includes(fragment)), JSON.stringify(error.issues));
      return true;
    },
  );
  for (const reserved of ["model", "messages", "tools", "tool_choice", "response_format", "reasoning", "thinking", "stream", "temperature", "max_tokens", "seed", "stop", "parallel_tool_calls"]) {
    expectIssue({ openai: { [reserved]: "x" } }, `reserved canonical wire field "${reserved}"`);
  }
  // object literal __proto__ задаёт прототип; own-key форма — через JSON.parse
  expectIssue({ openai: JSON.parse('{"__proto__":{"polluted":true}}') }, "prototype-pollution");
  expectIssue({ openai: { when: new Date(0) } }, "non-plain");
  expectIssue({ openai: { fn: () => 1 } }, "non-serializable");
  expectIssue({ openai: { n: 1n } }, "non-serializable");
  expectIssue({ openai: { nan: Number.NaN } }, "non-finite");
  const cyclic = { a: 1 };
  cyclic.self = cyclic;
  expectIssue({ openai: cyclic }, "cyclic");
  expectIssue({ openai: { deep: { a: { b: { c: { d: { e: { f: { g: { h: 1 } } } } } } } } } }, "nesting");
  expectIssue({ openai: { pad: "x".repeat(9000) } }, "UTF-8 bytes");
  // валидные extras сохраняются точно
  const envelope = createEnvelope({ provider: "openai", messages: [user], providerOptions: { openai: { verbosity: "high", custom: { nested: [1, 2] } } } });
  assert.deepEqual(envelope.providerOptions.openai, { verbosity: "high", custom: { nested: [1, 2] } });
});

test("metadata transport is explicit per provider: openai carries it, others fail loudly pre-network", () => {
  const user = { role: "user", content: "hi" };
  const envelope = createEnvelope({ provider: "openai", messages: [user], metadata: { trace: "abc", tier: "pro" } });
  const { payload } = buildOpenAiCompatiblePayload(envelope, "openai", { defaultModel: "m" });
  assert.deepEqual(payload.metadata, { trace: "abc", tier: "pro" }); // точные байты
  for (const provider of ["kimi", "glm", "zai", "grok", "codex", "zcode"]) {
    assert.throws(
      () => assertEnvelopeSupported(envelope, provider),
      (error) => error instanceof UnsupportedCapabilityError && error.issues.some((i) => i.field === "metadata"),
      `${provider} must reject metadata loudly`,
    );
  }
  // молчаливая String()-коэрция запрещена: не-строковые значения — issue
  assert.throws(
    () => createEnvelope({ provider: "openai", messages: [user], metadata: { count: 5 } }),
    (error) => error instanceof EnvelopeValidationError && error.issues.some((i) => i.field === "metadata.count"),
  );
});

test("nested shapes reject unknown fields instead of silently dropping them", () => {
  const user = { role: "user", content: "hi" };
  const expectIssue = (input, field) => assert.throws(
    () => createEnvelope(input),
    (error) => {
      assert.ok(error instanceof EnvelopeValidationError);
      assert.ok(error.issues.some((i) => i.field === field && i.message.includes("unknown field")),
        `expected unknown-field issue at ${field}, got ${JSON.stringify(error.issues.map((i) => i.field))}`);
      return true;
    },
  );
  expectIssue({ messages: [{ ...user, annotations: { x: 1 } }] }, "messages[0].annotations");
  expectIssue({ messages: [user, { role: "assistant", content: "", tool_calls: [{ id: "c", function: { name: "f", arguments: "{}" }, extra: 1 }] }] }, "messages[1].tool_calls[0].extra");
  expectIssue({ messages: [user, { role: "assistant", content: "", tool_calls: [{ id: "c", function: { name: "f", arguments: "{}", strict: true } }] }] }, "messages[1].tool_calls[0].function.strict");
  expectIssue({ messages: [user], reasoning: { effort: "low", summary: true } }, "reasoning.summary");
  expectIssue({ messages: [user], responseFormat: { type: "json_object", strict: true } }, "responseFormat.strict");
  expectIssue({ messages: [user], responseFormat: { type: "json_schema", jsonSchema: { name: "o", schema: {}, strict: true } } }, "responseFormat.jsonSchema.strict");
  expectIssue({ messages: [user], toolChoice: { name: "t", strict: true } }, "toolChoice.strict");
  expectIssue({ messages: [user], tools: [{ type: "function", function: { name: "t", parameters: {}, strict: true } }] }, "tools[0].function.strict");
  expectIssue({ messages: [user], tools: [{ type: "function", function: { name: "t", parameters: {} }, extra: 1 }] }, "tools[0].extra");
});

test("tool descriptions pass verbatim up to the loud 1024-byte cap (no 500-char UI slice)", () => {
  const description = `d`.repeat(900); // раньше UI молча резал на 500
  const envelope = createEnvelope({
    provider: "openai",
    messages: [{ role: "user", content: "hi" }],
    tools: [{ type: "function", function: { name: "t", description, parameters: {} } }],
  });
  assert.equal(envelope.tools[0].function.description, description);
  assert.equal(envelope.tools[0].function.description.length, 900);
  assert.throws(
    () => createEnvelope({
      provider: "openai",
      messages: [{ role: "user", content: "hi" }],
      tools: [{ type: "function", function: { name: "t", description: "d".repeat(2000), parameters: {} } }],
    }),
    (error) => error instanceof EnvelopeValidationError && error.issues.some((i) => i.field === "tools[0].function.description"),
  );
});

test("scalar types and role-specific nested fields never coerce or disappear", () => {
  const user = { role: "user", content: "hi" };
  const expectField = (input, field) => assert.throws(
    () => createEnvelope(input),
    (error) => error instanceof EnvelopeValidationError && error.issues.some((item) => item.field === field),
  );

  expectField(null, "$");
  expectField({ messages: [user], version: 2 }, "version");
  expectField({ messages: [user], system: { text: "hidden coercion" } }, "system");
  expectField({ messages: [user], temperature: "0.4" }, "temperature");
  expectField({ messages: [user], stream: "false" }, "stream");
  expectField({ messages: [user], parallelToolCalls: "false" }, "parallelToolCalls");
  expectField({ messages: [user], stop: [{ value: "END" }] }, "stop[0]");
  expectField({ messages: [{ ...user, tool_call_id: "wrong-role" }] }, "messages[0].tool_call_id");
  expectField({ messages: [{ ...user, tool_calls: [] }] }, "messages[0].tool_calls");
  expectField({ messages: [{ role: "user", content: [{ type: "text", text: "x", ignored: true }] }] }, "messages[0].content[0].ignored");
  expectField({ messages: [{ role: "user", content: [{ type: "text", text: 7 }] }] }, "messages[0].content[0].text");
  expectField({ messages: [user, { role: "assistant", content: "", tool_calls: [{ id: 7, type: "function", function: { name: "f", arguments: {} } }] }] }, "messages[1].tool_calls[0].id");
  expectField({ messages: [user], tools: [{ type: "retrieval", function: { name: "t", parameters: {} } }] }, "tools[0].type");
  expectField({ messages: [user], tools: [{ type: "function", function: { name: "t", description: 7, parameters: [] } }] }, "tools[0].function.description");
  expectField({ messages: [user], providerOptions: { openai: "unsafe" } }, "providerOptions.openai");

  const image = createEnvelope({
    provider: "openai",
    messages: [{ role: "user", content: [{ type: "image_url", image_url: { url: "https://example.test/a.png", detail: "high" } }] }],
  });
  assert.equal(image.messages[0].content[0].image_url.detail, "high");

  const named = createEnvelope({ messages: [{ role: "user", name: "designer", content: "hi" }] });
  const { payload } = buildOpenAiCompatiblePayload(named, "openai", { defaultModel: "m" });
  assert.equal(payload.messages[0].name, "designer");
});
