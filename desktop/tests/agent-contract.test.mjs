import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { existsSync, readFileSync } from "node:fs";

import { DEFAULT_AGENT_CONTRACT_DIR, loadAgentContract } from "../services/agent-contract.mjs";
import { ClaudeAgentServer, DEFAULT_CLAUDE_CAPABILITIES } from "../services/claude-agent-server.mjs";
import { CodexAppServer } from "../services/codex-app-server.mjs";
import { chatWithProvider } from "../services/provider-router.mjs";

const contract = loadAgentContract();
const ROLES = ["chat", "generator", "quality_judge", "quality_repair", "editor", "graphics", "art_direction"];
const CLAUDE_ENV = { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" };

/** Дубль child_process для Claude: собирает stdin и системный промпт в момент spawn. */
function fakeSpawn({ stdout = "" } = {}) {
  const calls = [];
  const spawnProcess = (command, args, options) => {
    const child = new EventEmitter();
    child.stdin = { end: (value) => { calls.at(-1).stdin = value; } };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => {};
    const systemIndex = args.indexOf("--system-prompt-file");
    const systemPrompt = systemIndex >= 0 && existsSync(args[systemIndex + 1])
      ? readFileSync(args[systemIndex + 1], "utf8") : null;
    calls.push({ command, args, options, stdin: null, systemPrompt });
    queueMicrotask(() => {
      if (stdout) child.stdout.emit("data", Buffer.from(stdout));
      child.emit("exit", 0);
    });
    return child;
  };
  return { spawnProcess, calls };
}

/** Codex с заглушками app-server: возвращает параметры thread/start. */
function fakeCodex(threadId = "thread-contract") {
  const codex = new CodexAppServer({ cwd: "C:\\workspace" });
  const seen = { threadParams: null, input: null };
  codex.start = async () => ({});
  codex.account = async () => ({ account: { type: "chatgpt" } });
  codex.startThread = async (params) => { seen.threadParams = params; return { model: "fixture-model", modelProvider: "openai", thread: { id: threadId } }; };
  codex.startTurn = async ({ input }) => {
    seen.input = input;
    queueMicrotask(() => {
      codex.emit("notification", { method: "item/completed", params: { threadId, item: { type: "agentMessage", text: "{}" } } });
      codex.emit("notification", { method: "turn/completed", params: { threadId, turn: { status: "completed" } } });
    });
    return { turn: { id: `turn-${threadId}` } };
  };
  return { codex, seen };
}

test("the pack loads from app/prompts/agent-contract with the expected roles", () => {
  assert.match(contract.version, /^agent-contract\/1\.1$/);
  assert.deepEqual(Object.keys(contract.roles).sort(), [...ROLES].sort());
  assert.equal(contract.dir, DEFAULT_AGENT_CONTRACT_DIR);
  assert.ok(existsSync(DEFAULT_AGENT_CONTRACT_DIR));
  for (const role of ROLES) assert.ok(contract.roles[role].instructions.length > 20, role);
  assert.throws(() => contract.role("nope"), /Unsupported agent role/);
  assert.throws(() => contract.composeInstructions("generator", "shell"), /Unsupported tool rule/);
  assert.equal(loadAgentContract(), contract, "повторная загрузка отдаёт тот же объект");
});

test("composeInstructions is role + tool rule + output rule", () => {
  assert.equal(contract.composeInstructions("generator", "none"),
    `${contract.roles.generator.instructions} ${contract.toolRules.none} ${contract.outputRules.json}`);
  assert.equal(contract.composeInstructions("chat", "none"), `${contract.roles.chat.instructions} ${contract.toolRules.none}`);
  assert.equal(contract.composeInstructions("graphics", "inline-images"),
    `${contract.roles.graphics.instructions} ${contract.toolRules["inline-images"]} ${contract.outputRules.svg}`);
  assert.match(contract.reminder("graphics"), /<svg>/);
  assert.match(contract.reminder("editor"), /JSON object/);
  assert.equal(contract.reminder("chat"), "");
});

test("a broken pack fails loudly instead of sending empty instructions", () => {
  const files = {
    "contract.json": JSON.stringify({ version: "agent-contract/1.0", roles: { generator: { output: "json", file: "roles/generator.md" } },
      toolRules: { none: "x" }, outputRules: { json: "y" }, reminders: { json: "z" } }),
    "roles/generator.md": "   \n",
  };
  const readFile = (file) => {
    const key = Object.keys(files).find((name) => file.replace(/\\/g, "/").endsWith(name));
    if (!key) throw new Error(`ENOENT ${file}`);
    return files[key];
  };
  assert.throws(() => loadAgentContract("/fixtures/pack-empty", { readFile, reload: true }), /empty instructions/);
  files["contract.json"] = JSON.stringify({ version: "v9", roles: {}, toolRules: {}, outputRules: {}, reminders: {} });
  assert.throws(() => loadAgentContract("/fixtures/pack-version", { readFile, reload: true }), /unsupported version/);
});

for (const role of ROLES) {
  test(`Claude and Codex send the same ${role} instructions from the pack`, async () => {
    const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
    const claude = new ClaudeAgentServer({ spawnProcess, environment: CLAUDE_ENV, fileExists: () => true });
    await claude.chat([{ role: "system", content: "S" }, { role: "user", content: "U" }], { profile: role });
    const expectedClaude = contract.composeInstructions(role, "none");
    assert.ok(calls[0].systemPrompt.startsWith(expectedClaude), `${role}: ${calls[0].systemPrompt.slice(0, 80)}`);
    if (role !== "chat") assert.ok(calls[0].stdin.endsWith(contract.reminder(role)), role);

    const { codex, seen } = fakeCodex();
    await codex.chat([{ role: "system", content: "S" }, { role: "user", content: "U" }], { profile: role });
    const expectedCodex = contract.composeInstructions(role, "inline-images");
    assert.ok(seen.threadParams.developerInstructions.startsWith(expectedCodex), role);
    // Текст роли один; различается только правило инструментов (транспорт).
    assert.equal(expectedClaude.replace(contract.toolRules.none, "<tools>"),
      expectedCodex.replace(contract.toolRules["inline-images"], "<tools>"));
  });
}

test("chat role works for Codex too (Agent Workspace on GPT)", async () => {
  const { codex, seen } = fakeCodex("thread-chat");
  await codex.chat([{ role: "user", content: "Оцени идею" }], { profile: "chat" });
  assert.match(seen.threadParams.developerInstructions, /design assistant/);
  assert.doesNotMatch(seen.threadParams.developerInstructions, /Return only the JSON object/);
});

test("structured output: --json-schema and structured_output for Claude", async () => {
  const schema = { type: "object", additionalProperties: false, required: ["approved"], properties: { approved: { type: "boolean" } } };
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ type: "result", is_error: false, result: '{"approved":true}', structured_output: { approved: true } }),
  });
  const claude = new ClaudeAgentServer({ spawnProcess, environment: CLAUDE_ENV, fileExists: () => true });
  let metadata = null;
  const output = await claude.chat([{ role: "user", content: "judge" }], {
    profile: "quality_judge",
    responseFormat: { type: "json_schema", jsonSchema: { name: "verdict", schema } },
    onResponseMetadata: (value) => { metadata = value; },
  });
  assert.equal(output, JSON.stringify({ approved: true }));
  const index = calls[0].args.indexOf("--json-schema");
  assert.ok(index > 0, "schema flag must be passed");
  assert.deepEqual(JSON.parse(calls[0].args[index + 1]), schema);
  assert.equal(calls[0].args.includes("--max-turns"), false, "structured output needs the internal tool turn");
  assert.equal(metadata.structuredOutput, true);
  assert.deepEqual(metadata.dropped, []);
  assert.equal(metadata.contractVersion, contract.version);
  assert.equal(metadata.effort, "medium");
});

test("structured output is dropped loudly when the CLI lacks --json-schema", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: '{"approved":false}' }) });
  const claude = new ClaudeAgentServer({
    spawnProcess, environment: CLAUDE_ENV, fileExists: () => true,
    capabilities: { ...DEFAULT_CLAUDE_CAPABILITIES, jsonSchema: false },
  });
  let metadata = null;
  const output = await claude.chat([{ role: "user", content: "judge" }], {
    profile: "quality_judge",
    responseFormat: { type: "json_schema", jsonSchema: { name: "verdict", schema: { type: "object" } } },
    onResponseMetadata: (value) => { metadata = value; },
  });
  assert.equal(output, '{"approved":false}');
  assert.equal(calls[0].args.includes("--json-schema"), false);
  assert.equal(metadata.structuredOutput, false);
  assert.equal(metadata.dropped[0].field, "responseFormat");
});

test("structured output is not sent through the cmd.exe shim", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "{}" }) });
  // Бинарь не найден: спека уходит через cmd.exe (resolved=false), OAuth по env.
  const claude = new ClaudeAgentServer({
    spawnProcess, environment: { USERPROFILE: "C:\\Users\\fixture", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth", ComSpec: "C:\\Windows\\System32\\cmd.exe" },
    fileExists: () => false,
  });
  claude.account = () => ({ installed: true, loggedIn: true, ready: true, hint: null });
  let metadata = null;
  await claude.chat([{ role: "user", content: "judge" }], {
    profile: "quality_judge",
    responseFormat: { type: "json_schema", jsonSchema: { name: "verdict", schema: { type: "object" } } },
    onResponseMetadata: (value) => { metadata = value; },
  });
  assert.equal(calls[0].args.some((arg) => /--json-schema/.test(String(arg))), false);
  assert.match(metadata.dropped[0].reason, /cmd\.exe/);
});

test("router forwards responseFormat to Claude and reports the contract version", async () => {
  const seen = {};
  const claude = {
    contract,
    chat: async (messages, options) => {
      seen.options = options;
      options.onResponseMetadata?.({ contractVersion: contract.version, structuredOutput: true, dropped: [] });
      return '{"approved":true}';
    },
  };
  const result = await chatWithProvider({
    provider: "claude", messages: [{ role: "user", content: "x" }], claude, credentials: { has: () => false },
    profile: "quality_judge",
    envelope: { provider: "claude", id: "req-1", messages: [{ role: "user", content: "x" }],
      responseFormat: { type: "json_schema", jsonSchema: { name: "verdict", schema: { type: "object" } } } },
  });
  assert.equal(seen.options.responseFormat.type, "json_schema");
  assert.equal(result.transport.contractVersion, contract.version);
  assert.equal(result.transport.structuredOutput, true);
  assert.deepEqual(result.transport.dropped, []);
});

test("Codex transport carries the contract version", async () => {
  const { codex } = fakeCodex("thread-version");
  const result = await chatWithProvider({
    provider: "codex", messages: [{ role: "user", content: "Judge" }], codex, credentials: { has: () => false }, profile: "quality_judge",
  });
  assert.equal(result.transport.contractVersion, contract.version);
});
