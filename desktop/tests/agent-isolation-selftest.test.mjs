import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CANARY_INSTRUCTION, CANARY_MARKER, ClaudeAgentServer, DEFAULT_CLAUDE_CAPABILITIES } from "../services/claude-agent-server.mjs";
import { CodexAppServer } from "../services/codex-app-server.mjs";
import { HERMETIC_CODEX_CONFIG } from "../services/hermetic-agent.mjs";

// Дубль spawn не умеет отвечать на --help: capabilities передаём как уже прочитанные.
const PROBED = { ...DEFAULT_CLAUDE_CAPABILITIES, probed: true };

const desktopDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CLAUDE_ENV = { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" };

/** Дубль child_process: запоминает cwd и то, лежала ли канарейка над ним в момент spawn. */
function fakeSpawn({ stdout = "" } = {}) {
  const calls = [];
  const spawnProcess = (command, args, options) => {
    const child = new EventEmitter();
    child.stdin = { end: (value) => { calls.at(-1).stdin = value; } };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => {};
    const canary = path.join(path.dirname(String(options.cwd || "")), "CLAUDE.md");
    calls.push({ command, args, options, stdin: null,
      canaryPresent: existsSync(canary), canaryText: existsSync(canary) ? readFileSync(canary, "utf8") : null });
    queueMicrotask(() => {
      if (stdout) child.stdout.emit("data", Buffer.from(stdout));
      child.emit("exit", 0);
    });
    return child;
  };
  return { spawnProcess, calls };
}

function scratchRoot(t) {
  const root = mkdtempSync(path.join(tmpdir(), "ddna-selftest-"));
  t.after(() => { try { rmSync(root, { recursive: true, force: true }); } catch { /* best effort */ } });
  return root;
}

test("Claude self-test plants a canary CLAUDE.md above the cwd and reports isolation", async (t) => {
  const canaryRoot = path.join(scratchRoot(t), "canary");
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "OK" }) });
  const server = new ClaudeAgentServer({ spawnProcess, environment: CLAUDE_ENV, fileExists: () => true, capabilities: PROBED });
  const result = await server.selfTest({ canaryRoot });
  assert.equal(result.provider, "claude");
  assert.equal(result.ok, true);
  assert.equal(result.isolated, true);
  assert.equal(result.model, "haiku");
  assert.match(result.contractVersion, /^agent-contract\//);
  assert.equal(calls.length, 1, "capabilities уже известны: без повторного --help");
  const chat = calls[0];
  assert.equal(chat.options.cwd, path.join(canaryRoot, "work"), "канарейка проверяется из подкаталога work");
  assert.equal(chat.canaryPresent, true, "CLAUDE.md обязан лежать над cwd в момент вызова");
  assert.equal(chat.canaryText.trim(), CANARY_INSTRUCTION);
  assert.ok(chat.args.includes("--setting-sources"), "проверяется реальная производственная конфигурация");
  assert.ok(chat.args.includes("--system-prompt-file"));
  assert.match(chat.stdin, /Reply with the single word OK\./);
  assert.equal(existsSync(canaryRoot), false, "канарейка удаляется после проверки");
});

test("Claude self-test detects a leaked instruction", async (t) => {
  const canaryRoot = path.join(scratchRoot(t), "canary");
  const { spawnProcess } = fakeSpawn({ stdout: JSON.stringify({ result: `${CANARY_MARKER} OK` }) });
  const server = new ClaudeAgentServer({ spawnProcess, environment: CLAUDE_ENV, fileExists: () => true, capabilities: PROBED });
  const result = await server.selfTest({ canaryRoot });
  assert.equal(result.isolated, false);
  assert.equal(result.ok, true);
  assert.match(result.sample, /PINEAPPLE/);
});

test("Claude self-test refuses without a ready account and reports CLI failures", async (t) => {
  const canaryRoot = path.join(scratchRoot(t), "canary");
  const { spawnProcess, calls } = fakeSpawn({ stdout: "" });
  const notReady = new ClaudeAgentServer({ spawnProcess, environment: {}, fileExists: () => false });
  const refused = await notReady.selfTest({ canaryRoot });
  assert.equal(refused.ok, false);
  assert.equal(refused.isolated, null);
  assert.ok(refused.error);
  assert.equal(calls.length, 0, "без подключения CLI не запускается");

  const failing = new ClaudeAgentServer({ spawnProcess, environment: CLAUDE_ENV, fileExists: () => true,
    capabilities: { probed: true } });
  const failed = await failing.selfTest({ canaryRoot });
  assert.equal(failed.ok, false);
  assert.equal(failed.isolated, null);
  assert.match(failed.error, /empty response/);
  assert.equal(existsSync(canaryRoot), false);
});

function stubCodex({ instructionSources, accountType = "chatgpt" }) {
  const server = new CodexAppServer({ cwd: "C:\\workspace" });
  const seen = {};
  server.start = async () => ({});
  server.account = async () => ({ account: { type: accountType } });
  server.startThread = async (params) => {
    seen.threadParams = params;
    seen.canaryPresent = existsSync(path.join(params.cwd, "AGENTS.md"));
    return { model: "gpt-5.6-sol", modelProvider: "openai", thread: { id: "thread-selftest" },
      instructionSources: typeof instructionSources === "function" ? instructionSources(params.cwd) : instructionSources };
  };
  server.startTurn = async () => { throw new Error("self-test must not start a turn"); };
  return { server, seen };
}

test("Codex self-test starts a hermetic thread over a canary AGENTS.md and reads instructionSources", async (t) => {
  const canaryRoot = path.join(scratchRoot(t), "canary");
  const { server, seen } = stubCodex({ instructionSources: ["C:\\Users\\fixture\\.codex\\AGENTS.md"] });
  const result = await server.selfTest({ canaryRoot });
  assert.equal(result.provider, "codex");
  assert.equal(result.ok, true);
  assert.equal(result.isolated, true, "канарейка из cwd не подхвачена");
  assert.deepEqual(result.globalInstructionSources, ["C:\\Users\\fixture\\.codex\\AGENTS.md"]);
  assert.equal(result.model, "gpt-5.6-sol");
  assert.equal(seen.canaryPresent, true, "AGENTS.md обязан лежать в cwd в момент thread/start");
  assert.equal(seen.threadParams.cwd, canaryRoot);
  assert.equal(seen.threadParams.ephemeral, true);
  assert.deepEqual(seen.threadParams.config, { ...HERMETIC_CODEX_CONFIG });
  assert.equal(existsSync(canaryRoot), false, "канарейка удаляется после проверки");
});

test("Codex self-test detects the canary among instructionSources", async (t) => {
  const canaryRoot = path.join(scratchRoot(t), "canary");
  const { server } = stubCodex({ instructionSources: (cwd) => [path.join(cwd, "AGENTS.md")] });
  const result = await server.selfTest({ canaryRoot });
  assert.equal(result.isolated, false);
  assert.deepEqual(result.globalInstructionSources, []);
});

test("Codex self-test refuses without the ChatGPT login", async (t) => {
  const canaryRoot = path.join(scratchRoot(t), "canary");
  const { server, seen } = stubCodex({ instructionSources: [], accountType: "apiKey" });
  const result = await server.selfTest({ canaryRoot });
  assert.equal(result.ok, false);
  assert.equal(result.isolated, null);
  assert.match(result.error, /ChatGPT login/);
  assert.equal(seen.threadParams, undefined);
});

test("main, preload and the workspace expose the self-test end to end", () => {
  const main = readFileSync(path.join(desktopDirectory, "main.mjs"), "utf8");
  const preload = readFileSync(path.join(desktopDirectory, "preload.cjs"), "utf8");
  const workspace = readFileSync(path.join(desktopDirectory, "..", "frontend", "src", "desktop", "AgentWorkspace.svelte"), "utf8");
  const typings = readFileSync(path.join(desktopDirectory, "..", "frontend", "src", "desktop.d.ts"), "utf8");
  assert.ok(main.includes('handleTrusted("providers:self-test"'), "IPC handler must be registered");
  assert.ok(main.includes("claude.selfTest()") && main.includes("codex.selfTest()"));
  assert.ok(preload.includes('ipcRenderer.invoke("providers:self-test", { provider })'));
  assert.ok(typings.includes("selfTest(provider: \"claude\" | \"codex\"): Promise<IsolationSelfTest>"));
  assert.ok(workspace.includes('runIsolationCheck("codex")') && workspace.includes('runIsolationCheck("claude")'));
  assert.ok(workspace.includes("Проверить изоляцию GPT") && workspace.includes("Проверить изоляцию Claude"));
});
