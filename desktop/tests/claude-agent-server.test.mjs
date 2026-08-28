import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import path from "node:path";

import {
  ClaudeAgentServer,
  claudeCredentialPaths,
  claudeEffortBudget,
  claudeProcessSpec,
} from "../services/claude-agent-server.mjs";

/** Минимальный дубль child_process: собирает stdin, отдаёт заданный stdout. */
function fakeSpawn({ stdout = "", stderr = "", code = 0 } = {}) {
  const calls = [];
  const spawnProcess = (command, args, options) => {
    const child = new EventEmitter();
    child.stdin = { end: (value) => { calls.at(-1).stdin = value; } };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => { calls.at(-1).killed = true; };
    calls.push({ command, args, options, stdin: null, killed: false });
    queueMicrotask(() => {
      if (stdout) child.stdout.emit("data", stdout);
      if (stderr) child.stderr.emit("data", stderr);
      child.emit("exit", code);
    });
    return child;
  };
  return { spawnProcess, calls };
}

test("Windows falls back to the cmd.exe shim with UTF-8 code page", () => {
  const spec = claudeProcessSpec({
    platform: "win32",
    environment: { PATH: "", ComSpec: "C:\\Windows\\system32\\cmd.exe" },
    args: ["-p", "--model", "opus"],
  });
  assert.equal(spec.command, "C:\\Windows\\system32\\cmd.exe");
  assert.deepEqual(spec.args.slice(0, 3), ["/d", "/s", "/c"]);
  assert.match(spec.args[3], /^chcp 65001>nul && claude /);
  assert.match(spec.args[3], /-p --model opus/);
});

test("DESIGNDNA_CLAUDE bypasses discovery on every platform", () => {
  for (const platform of ["win32", "darwin", "linux"]) {
    const spec = claudeProcessSpec({
      platform,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude" },
      args: ["-p"],
    });
    assert.equal(spec.command, "/opt/claude");
    assert.deepEqual(spec.args, ["-p"]);
  }
});

test("POSIX invokes the claude binary directly", () => {
  const spec = claudeProcessSpec({ platform: "linux", environment: {}, args: ["-p"] });
  assert.equal(spec.command, "claude");
  assert.deepEqual(spec.args, ["-p"]);
});

test("effort maps to a thinking budget, unknown values fall back to medium", () => {
  assert.equal(claudeEffortBudget("medium"), 0);
  assert.ok(claudeEffortBudget("high") > 0);
  assert.ok(claudeEffortBudget("max") > claudeEffortBudget("high"));
  assert.equal(claudeEffortBudget("turbo"), claudeEffortBudget("medium"));
  assert.equal(claudeEffortBudget(undefined), claudeEffortBudget("medium"));
});

test("credential probe looks at the Claude Code login file, never at its contents", () => {
  const paths = claudeCredentialPaths({ USERPROFILE: "C:\\Users\\dev" });
  assert.ok(paths.length > 0);
  assert.ok(paths.every((file) => path.basename(file) === ".credentials.json"));
  assert.equal(claudeCredentialPaths({}).length, 0);
});

test("status reports logged out with an actionable hint", () => {
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\dev" },
    fileExists: () => false,
  });
  const status = server.account();
  assert.equal(status.provider, "claude");
  assert.equal(status.installed, true);
  assert.equal(status.loggedIn, false);
  assert.match(status.hint, /\/login/);
});

test("status reports connected once Claude Code holds credentials", () => {
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\dev" },
    fileExists: () => true,
  });
  const status = server.account();
  assert.equal(status.loggedIn, true);
  assert.equal(status.hint, null);
  assert.equal(status.model, "opus");
});

test("chat sends a headless JSON request and returns the result field", async () => {
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ type: "result", is_error: false, result: '{"ir":true}' }),
  });
  const server = new ClaudeAgentServer({
    cwd: "/repo",
    spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" },
    fileExists: () => true,
  });
  const output = await server.chat([{ role: "user", content: "make it" }], { profile: "generator" });
  assert.equal(output, '{"ir":true}');
  assert.deepEqual(calls[0].args, ["-p", "--output-format", "json", "--model", "opus"]);
  assert.match(calls[0].stdin, /USER:\nmake it/);
  assert.match(calls[0].stdin, /Return only the JSON object/);
});

test("high effort sets a thinking budget, medium leaves it unset", async () => {
  const envelope = JSON.stringify({ result: "ok" });
  for (const [effort, expected] of [["medium", undefined], ["high", String(claudeEffortBudget("high"))]]) {
    const { spawnProcess, calls } = fakeSpawn({ stdout: envelope });
    const server = new ClaudeAgentServer({
      cwd: "/repo", spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
    });
    await server.chat([{ role: "user", content: "hi" }], { effort });
    assert.equal(calls[0].options.env.MAX_THINKING_TOKENS, expected);
  }
});

test("unknown profiles are rejected before the process starts", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: "{}" });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  await assert.rejects(
    server.chat([{ role: "user", content: "hi" }], { profile: "shell" }),
    /Unsupported Claude chat profile/,
  );
  assert.equal(calls.length, 0);
});

test("an authentication failure becomes a readable login instruction", async () => {
  const { spawnProcess } = fakeSpawn({ stderr: "Invalid API key · please run /login", code: 1 });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => false,
  });
  await assert.rejects(server.chat([{ role: "user", content: "hi" }]), /Claude не подключён.*\/login/s);
});

test("an error envelope and an empty result both surface as failures", async () => {
  const errored = fakeSpawn({ stdout: JSON.stringify({ is_error: true, result: "rate limited" }) });
  const emptyOut = fakeSpawn({ stdout: JSON.stringify({ result: "   " }) });
  for (const [{ spawnProcess }, pattern] of [[errored, /rate limited/], [emptyOut, /empty response/]]) {
    const server = new ClaudeAgentServer({
      cwd: "/repo", spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
    });
    await assert.rejects(server.chat([{ role: "user", content: "hi" }]), pattern);
  }
});

test("cancellation kills the CLI process", async () => {
  const controller = new AbortController();
  const spawnProcess = (command, args, options) => {
    const child = new EventEmitter();
    child.stdin = { end: () => {} };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.killed = false;
    child.kill = () => { child.killed = true; };
    queueMicrotask(() => controller.abort());
    spawnProcess.child = child;
    return child;
  };
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  await assert.rejects(
    server.chat([{ role: "user", content: "hi" }], { signal: controller.signal }),
    /cancelled/,
  );
  assert.equal(spawnProcess.child.killed, true);
});
