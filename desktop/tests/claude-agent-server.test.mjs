import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import path from "node:path";

import {
  ClaudeAgentServer,
  claudeCredentialPaths,
  claudeEffortBudget,
  claudeInstallPaths,
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
      if (stdout) child.stdout.emit("data", Buffer.from(stdout));
      if (stderr) child.stderr.emit("data", Buffer.isBuffer(stderr) ? stderr : Buffer.from(stderr));
      child.emit("exit", code);
    });
    return child;
  };
  return { spawnProcess, calls };
}

test("the official ~/.local/bin install is found even when PATH omits it", () => {
  // Регрессия: установщик Claude Code кладёт бинарь в ~/.local/bin, которого
  // нет в PATH процесса Electron — запуск падал в cmd.exe.
  const installed = "C:\\Users\\dev\\.local\\bin\\claude.exe";
  const spec = claudeProcessSpec({
    platform: "win32",
    environment: { PATH: "", USERPROFILE: "C:\\Users\\dev" },
    args: ["-p"],
    fileExists: (file) => file === installed,
  });
  assert.equal(spec.command, installed);
  assert.equal(spec.resolved, true);
  assert.deepEqual(spec.args, ["-p"]);
  assert.ok(claudeInstallPaths({ USERPROFILE: "C:\\Users\\dev" }).includes(installed));
});

test("Windows falls back to the cmd.exe shim only when nothing resolves", () => {
  const spec = claudeProcessSpec({
    platform: "win32",
    environment: { PATH: "", ComSpec: "C:\\Windows\\system32\\cmd.exe" },
    args: ["-p", "--model", "opus"],
    fileExists: () => false,
  });
  assert.equal(spec.command, "C:\\Windows\\system32\\cmd.exe");
  assert.equal(spec.resolved, false);
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

/* Валидные креды CLI: непустой accessToken (logout оставляет файл с пустыми). */
const VALID_CREDS = JSON.stringify({ claudeAiOauth: { accessToken: "tok", refreshToken: "tok" } });
const EMPTY_CREDS = JSON.stringify({ claudeAiOauth: { accessToken: "", refreshToken: "" } });

test("status reports logged out with an app-connect hint", () => {
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\dev" },
    fileExists: () => false,
  });
  const status = server.account();
  assert.equal(status.provider, "claude");
  assert.equal(status.installed, true);
  assert.equal(status.loggedIn, false);
  assert.equal(status.ready, false);
  assert.match(status.hint, /Подключить Claude/);
});

test("credentials without a resolvable binary are not reported as connected", () => {
  // Регрессия: файл кредов существовал, бинаря не было — статус показывал
  // «подключён по подписке», а генерация падала кракозябрами из cmd.exe.
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { PATH: "", USERPROFILE: "C:\\Users\\dev" },
    fileExists: (file) => file.endsWith(".credentials.json"),
    readFile: () => VALID_CREDS,
  });
  const status = server.account();
  assert.equal(status.loggedIn, true);
  assert.equal(status.installed, false);
  assert.equal(status.ready, false);
  assert.match(status.hint, /CLI не найден/);
});

test("status reports connected once Claude Code holds credentials", () => {
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\dev" },
    fileExists: () => true,
    readFile: () => VALID_CREDS,
  });
  const status = server.account();
  assert.equal(status.loggedIn, true);
  assert.equal(status.ready, true);
  assert.equal(status.hint, null);
  assert.equal(status.model, "opus");
});

test("credentials file with wiped tokens is logged out (logout leaves the skeleton)", () => {
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\dev" },
    fileExists: () => true,
    readFile: () => EMPTY_CREDS,
  });
  const status = server.account();
  assert.equal(status.loggedIn, false);
  assert.equal(status.ready, false);
});

test("an app-stored setup token counts as logged in", () => {
  const server = new ClaudeAgentServer({
    cwd: ".",
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\dev" },
    fileExists: (file) => !file.endsWith(".credentials.json"),
    getStoredToken: () => "sk-ant-oat01-test",
  });
  const status = server.account();
  assert.equal(status.loggedIn, true);
  assert.equal(status.viaApp, true);
  assert.equal(status.ready, true);
});

test("chat fails fast with an install hint when no binary resolves", async () => {
  let spawned = false;
  const server = new ClaudeAgentServer({
    cwd: ".",
    spawnProcess: () => { spawned = true; throw new Error("must not spawn"); },
    environment: { PATH: "", USERPROFILE: "C:\\Users\\dev" },
    fileExists: (file) => file.endsWith(".credentials.json"),
  });
  await assert.rejects(server.chat([{ role: "user", content: "hi" }]), /CLI не найден/);
  assert.equal(spawned, false);
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

test("chat passes a supported model through and falls back on unknown", async () => {
  for (const [requested, expected] of [["sonnet", "sonnet"], ["Opus", "opus"], ["gpt-5.6-sol", "opus"], [null, "opus"]]) {
    const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
    const server = new ClaudeAgentServer({
      cwd: "/repo", spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
    });
    await server.chat([{ role: "user", content: "hi" }], { model: requested });
    assert.deepEqual(calls[0].args, ["-p", "--output-format", "json", "--model", expected]);
  }
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

test("a login failure reported on stdout is surfaced, not swallowed as exit 1", async () => {
  // Регрессия: CLI кладёт причину в JSON-конверт на stdout, stderr при этом
  // пуст — пользователь видел голое «завершился с кодом 1».
  const { spawnProcess } = fakeSpawn({
    stdout: JSON.stringify({ type: "result", is_error: true, result: "Not logged in · Please run /login" }),
    code: 1,
  });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  await assert.rejects(server.chat([{ role: "user", content: "hi" }]), /Claude не подключён.*Подключить Claude/s);
});

test("an authentication failure becomes a readable login instruction", async () => {
  const { spawnProcess } = fakeSpawn({ stderr: "Invalid API key · please run /login", code: 1 });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => false,
  });
  await assert.rejects(server.chat([{ role: "user", content: "hi" }]), /Claude не подключён.*Подключить Claude/s);
});

test("cmd.exe OEM-encoded failures are decoded, not shown as mojibake", async () => {
  // cmd.exe печатает свои ошибки в cp866 даже после chcp 65001.
  const oem = Buffer.from([0x22, 0x63, 0x6c, 0x61, 0x75, 0x64, 0x65, 0x22, 0x20,
    0xad, 0xa5, 0x20, 0xef, 0xa2, 0xab, 0xef, 0xa5, 0xe2, 0xe1, 0xef]); // "claude" не является
  const { spawnProcess } = fakeSpawn({ stderr: oem, code: 1 });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  await assert.rejects(
    server.chat([{ role: "user", content: "hi" }]),
    (error) => {
      assert.doesNotMatch(error.message, /�/, "сообщение не должно содержать кракозябр");
      assert.match(error.message, /CLI не найден/);
      return true;
    },
  );
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


// ---------- мультимодальный вход: изображения уезжают файлами ----------

const PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==";

test("image parts become temp files, Read is allowed, and the dir is cleaned up", async () => {
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ type: "result", is_error: false, result: '{"regions":[]}' }),
  });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  const output = await server.chat([
    { role: "system", content: "segment" },
    { role: "user", content: [
      { type: "text", text: '{"tile":0}' },
      { type: "image_url", image_url: { url: `data:image/png;base64,${PNG_1PX}`, detail: "high" } },
    ] },
  ]);
  assert.equal(output, '{"regions":[]}');
  assert.ok(calls[0].args.includes("--allowedTools"), "vision-запрос обязан разрешить Read");
  assert.ok(calls[0].args.includes("Read"));
  const match = /IMAGE FILE \(view it with the Read tool\): (.+)/.exec(calls[0].stdin);
  assert.ok(match, "путь к изображению обязан попасть в промпт");
  assert.equal(existsSync(match[1].trim()), false, "временный файл обязан удаляться после запроса");
});

test("text-only requests keep the no-tools contract and flat prompt", async () => {
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ result: "ok" }),
  });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  await server.chat([{ role: "user", content: "plain" }]);
  assert.equal(calls[0].args.includes("--allowedTools"), false);
  assert.match(calls[0].stdin, /Do not inspect files, run commands, or call tools/);
});

test("non-data image urls are rejected loudly before any spawn", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: "{}" });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude" }, fileExists: () => true,
  });
  await assert.rejects(
    server.chat([{ role: "user", content: [
      { type: "image_url", image_url: { url: "https://example.com/x.png" } },
    ] }]),
    /data:image/,
  );
  assert.equal(calls.length, 0);
});
