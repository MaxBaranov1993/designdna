import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import {
  ClaudeAgentServer,
  claudeCredentialPaths,
  claudeEffortBudget,
  claudeInstallPaths,
  claudeProcessSpec,
  DEFAULT_CLAUDE_CAPABILITIES,
  parseClaudeCapabilities,
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
    // Системный промпт живёт во временном файле только на время запроса —
    // читаем его в момент spawn, как это сделал бы настоящий CLI.
    const systemIndex = args.indexOf("--system-prompt-file");
    const systemPrompt = systemIndex >= 0 && existsSync(args[systemIndex + 1])
      ? readFileSync(args[systemIndex + 1], "utf8") : null;
    calls.push({ command, args, options, stdin: null, killed: false, systemPrompt });
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
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" },
      args: ["-p"],
    });
    assert.equal(spec.command, "/opt/claude");
    assert.deepEqual(spec.args, ["-p"]);
  }
});

test("Windows shim preserves the empty setting-sources argument", () => {
  const spec = claudeProcessSpec({ platform: "win32", environment: { PATH: "" },
    fileExists: () => false, args: ["-p", "--setting-sources", "", "--model", "opus"],
  });
  assert.equal(spec.args[3], 'chcp 65001>nul && claude -p --setting-sources "" --model opus');
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
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" },
    fileExists: () => true,
  });
  const output = await server.chat([{ role: "user", content: "make it" }], { profile: "generator" });
  assert.equal(output, '{"ir":true}');
  assert.deepEqual(calls[0].args.slice(0, 7), ["-p", "--output-format", "json", "--model", "opus", "--setting-sources", ""]);
  assert.deepEqual(calls[0].args.slice(7, 12), ["--strict-mcp-config", "--tools", "", "--effort", "medium"]);
  assert.equal(calls[0].args[12], "--system-prompt-file");
  assert.match(calls[0].stdin, /USER:\nmake it/);
  assert.match(calls[0].systemPrompt, /Return only the JSON object/);
  assert.doesNotMatch(calls[0].stdin, /Generate the requested Design IR/, "инструкции профиля — системный промпт, не текст пользователя");
});

test("workspace chat accepts prose without requesting Design IR or JSON", async () => {
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ type: "result", is_error: false, result: "Предлагаю упростить навигацию." }),
  });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  const output = await server.chat([{ role: "user", content: "Оцени идею" }], { profile: "chat", model: "opus" });
  assert.equal(output, "Предлагаю упростить навигацию.");
  assert.match(calls[0].systemPrompt, /Answer the user in their language/);
  assert.doesNotMatch(calls[0].systemPrompt, /Return only the JSON object/);
  assert.doesNotMatch(calls[0].stdin, /Return only the JSON object/);
  assert.match(calls[0].systemPrompt, /Do not inspect files, run commands, or call tools/);
});

test("chat passes a supported model through and falls back on unknown", async () => {
  for (const [requested, expected] of [["sonnet", "sonnet"], ["Opus", "opus"], ["gpt-5.6-sol", "opus"], [null, "opus"]]) {
    const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
    const server = new ClaudeAgentServer({
      cwd: "/repo", spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
    });
    await server.chat([{ role: "user", content: "hi" }], { model: requested });
    assert.deepEqual(calls[0].args.slice(0, 7), ["-p", "--output-format", "json", "--model", expected, "--setting-sources", ""]);
  }
});

test("effort goes through --effort on a modern CLI, unknown values fall back to medium", async () => {
  const envelope = JSON.stringify({ result: "ok" });
  for (const [effort, expected] of [["medium", "medium"], ["high", "high"], ["max", "max"], ["ultra", "medium"]]) {
    const { spawnProcess, calls } = fakeSpawn({ stdout: envelope });
    const server = new ClaudeAgentServer({
      cwd: "/repo", spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
    });
    await server.chat([{ role: "user", content: "hi" }], { effort });
    const index = calls[0].args.indexOf("--effort");
    assert.deepEqual(calls[0].args.slice(index, index + 2), ["--effort", expected]);
    assert.equal(Object.hasOwn(calls[0].options.env, "MAX_THINKING_TOKENS"), false, "env-бюджет — только для CLI без --effort");
  }
});

test("without --effort support high effort sets a thinking budget, medium leaves it unset", async () => {
  const envelope = JSON.stringify({ result: "ok" });
  for (const [effort, expected] of [["medium", undefined], ["high", String(claudeEffortBudget("high"))]]) {
    const { spawnProcess, calls } = fakeSpawn({ stdout: envelope });
    const server = new ClaudeAgentServer({
      cwd: "/repo", spawnProcess, capabilities: { ...DEFAULT_CLAUDE_CAPABILITIES, effort: false },
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
    });
    await server.chat([{ role: "user", content: "hi" }], { effort });
    assert.equal(calls[0].options.env.MAX_THINKING_TOKENS, expected);
    assert.equal(calls[0].args.includes("--effort"), false);
  }
});

const API_ROUTE_ENV_NAMES = [
  "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "BASE_URL",
  "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_PROFILE",
  "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_BASE_URL", "AWS_BEARER_TOKEN_BEDROCK",
  "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
  "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH",
];

for (const source of ["inherited OAuth", "app-stored OAuth", "CLI OAuth file"]) {
  test(`subscription child strips API routes and preserves ${source} without mutating parent env`, async () => {
    const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
    // Synthetic values only. Assertions report names/booleans, never credentials.
    const inheritedToken = "fixture-inherited-oauth";
    const appToken = "fixture-app-oauth";
    const environment = Object.freeze({
      DESIGNDNA_CLAUDE: "/opt/claude", USERPROFILE: "C:\\Users\\fixture", Path: "fixture-path",
      SystemRoot: "C:\\Windows", TEMP: "fixture-temp", HTTPS_PROXY: "http://fixture-proxy",
      ...Object.fromEntries(API_ROUTE_ENV_NAMES.flatMap((name) => [[name, "fixture-route"], [name.toLowerCase(), "fixture-route"]])),
      ...(source === "CLI OAuth file" ? {} : { claude_code_oauth_token: inheritedToken }),
    });
    const server = new ClaudeAgentServer({ cwd: "/repo", environment, spawnProcess,
      fileExists: () => true, readFile: () => source === "CLI OAuth file" ? VALID_CREDS : EMPTY_CREDS,
      getStoredToken: () => source === "app-stored OAuth" ? appToken : null,
    });
    if (source === "CLI OAuth file") assert.equal(server.account().ready, true);
    assert.equal(await server.chat([{ role: "user", content: "Judge" }], { effort: "high" }), "ok");
    const childEnv = calls[0].options.env;
    const sourceFlagIndex = calls[0].args.indexOf("--setting-sources");
    assert.ok(sourceFlagIndex >= 0);
    assert.equal(calls[0].args[sourceFlagIndex + 1], "", "headless requests must exclude user/project/local routing settings");
    assert.equal(calls[0].args.includes("--bare"), false, "OAuth must remain available");
    assert.equal(calls[0].args.includes("--settings"), false, "do not load additional routing settings");
    for (const name of API_ROUTE_ENV_NAMES) {
      assert.equal(Object.keys(childEnv).some((key) => key.toUpperCase() === name), false, `${name} must not reach the child`);
      assert.ok(environment[name] === "fixture-route", "parent environment must remain unchanged");
    }
    for (const name of ["USERPROFILE", "Path", "SystemRoot", "TEMP", "HTTPS_PROXY"]) {
      assert.ok(childEnv[name] === environment[name], `${name} must remain available`);
    }
    if (source === "CLI OAuth file") {
      assert.equal(Object.hasOwn(childEnv, "CLAUDE_CODE_OAUTH_TOKEN"), false, "file-based login must not inject an env token");
    } else {
      const expected = source === "app-stored OAuth" ? appToken : inheritedToken;
      assert.ok(childEnv.CLAUDE_CODE_OAUTH_TOKEN === expected, "subscription OAuth must reach the child");
      assert.equal(Object.hasOwn(childEnv, "claude_code_oauth_token"), false, "OAuth env key must be canonical on Windows");
    }
    assert.equal(Object.hasOwn(childEnv, "MAX_THINKING_TOKENS"), false, "modern CLI takes --effort, not an env budget");
    const effortIndex = calls[0].args.indexOf("--effort");
    assert.deepEqual(calls[0].args.slice(effortIndex, effortIndex + 2), ["--effort", "high"]);
    assert.equal(calls.length, 1);
  });
}

test("subscription authentication failure does not retry with stripped API credentials", async () => {
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ is_error: true, result: "Not logged in" }), code: 1,
  });
  const environment = Object.freeze({ DESIGNDNA_CLAUDE: "/opt/claude", ANTHROPIC_API_KEY: "fixture-api" });
  const server = new ClaudeAgentServer({ spawnProcess, environment, fileExists: () => true, getStoredToken: () => "fixture-expired-oauth" });
  await assert.rejects(server.chat([{ role: "user", content: "Judge" }]), /Claude/);
  assert.equal(calls.length, 1);
  assert.equal(Object.hasOwn(calls[0].options.env, "ANTHROPIC_API_KEY"), false);
  assert.ok(environment.ANTHROPIC_API_KEY === "fixture-api", "parent credentials must not change");
});

test("API credentials alone cannot pass the subscription login guard or start a child", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "must not run" }) });
  const server = new ClaudeAgentServer({ spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", ANTHROPIC_API_KEY: "fixture-api",
      ANTHROPIC_AUTH_TOKEN: "fixture-bearer", CLAUDE_CODE_USE_BEDROCK: "1" },
    fileExists: () => false,
  });
  const status = server.account();
  assert.equal(status.loggedIn, false);
  assert.equal(status.ready, false);
  server.materializeMessages = () => { throw new Error("must reject before image materialization"); };
  await assert.rejects(server.chat([{ role: "user", content: "Judge" }]), /OAuth.*Connections/);
  assert.equal(calls.length, 0, "no provider request or automatic login may start");
});

test("inherited OAuth is recognized by readiness without reading or changing credentials", () => {
  const server = new ClaudeAgentServer({
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", claude_code_oauth_token: "fixture-oauth" },
    fileExists: () => false,
    readFile: () => { throw new Error("must not read credentials for env OAuth"); },
  });
  const status = server.account();
  assert.equal(status.viaEnv, true);
  assert.equal(status.loggedIn, true);
  assert.equal(status.ready, true);
});

test("unknown profiles are rejected before the process starts", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: "{}" });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
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
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await assert.rejects(server.chat([{ role: "user", content: "hi" }]), /Claude не подключён.*Подключить Claude/s);
});

test("an authentication failure becomes a readable login instruction", async () => {
  const { spawnProcess } = fakeSpawn({ stderr: "Invalid API key · please run /login", code: 1 });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => false,
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
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
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
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
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
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await assert.rejects(
    server.chat([{ role: "user", content: "hi" }], { signal: controller.signal }),
    /cancelled/,
  );
  assert.equal(spawnProcess.child.killed, true);
});


// ---------- мультимодальный вход: изображения уезжают файлами ----------

const PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==";

for (const separateMessages of [false, true]) {
  test(`materialization failure removes earlier image files (${separateMessages ? "later message" : "same message"})`, async (t) => {
    const imageTempRoot = mkdtempSync(path.join(tmpdir(), "ddna-claude-cleanup-test-"));
    t.after(() => rmSync(imageTempRoot, { recursive: true, force: true }));
    const { spawnProcess, calls } = fakeSpawn();
    const server = new ClaudeAgentServer({ imageTempRoot, spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" },
      fileExists: () => true,
    });
    let materializedFile;
    const good = { type: "image_url", image_url: { url: `data:image/png;base64,${PNG_1PX}` } };
    const bad = { type: "image_url", image_url: { get url() {
      const directories = readdirSync(imageTempRoot);
      assert.equal(directories.length, 1, "first image must already be materialized");
      const directory = path.join(imageTempRoot, directories[0]);
      materializedFile = path.join(directory, readdirSync(directory)[0]);
      assert.equal(readFileSync(materializedFile).toString("base64"), PNG_1PX);
      return "https://example.test/unsupported.png";
    } } };
    const messages = separateMessages
      ? [{ role: "user", content: [good] }, { role: "user", content: [bad] }]
      : [{ role: "user", content: [good, bad] }];
    await assert.rejects(server.chat(messages), /Claude CLI transports only data:image base64 parts/);
    assert.ok(materializedFile, "regression must exercise a partially written image request");
    assert.equal(existsSync(materializedFile), false);
    assert.equal(existsSync(path.dirname(materializedFile)), false);
    assert.deepEqual(readdirSync(imageTempRoot), []);
    assert.equal(calls.length, 0, "materialization failure must not start a provider process");
  });
}

for (const profile of ["generator", "quality_judge", "quality_repair", "editor"]) {
  test(`${profile} ends with a JSON-only reminder and preserves prose-prefixed raw output`, async () => {
    const raw = 'Here is the visual verdict:\n{"approved":false,"score":62}\n';
    const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: raw }) });
    const server = new ClaudeAgentServer({ spawnProcess,
      environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
    });
    assert.equal(await server.chat([{ role: "user", content: "Review the supplied evidence" }], { profile }), raw);
    assert.match(calls[0].stdin, /Review the supplied evidence\n\nFinal response: return only the complete JSON object required above\. No introduction, explanation, or Markdown fences\.$/);
    assert.equal(calls[0].args.includes("--json-schema"), false, "prompt reminder must not force a schema");
  });
}

test("image parts become temp files, Read is allowed, and the dir is cleaned up", async () => {
  const { spawnProcess, calls } = fakeSpawn({
    stdout: JSON.stringify({ type: "result", is_error: false, result: '{"regions":[]}' }),
  });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
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
  const toolsIndex = calls[0].args.indexOf("--tools");
  assert.deepEqual(calls[0].args.slice(toolsIndex, toolsIndex + 2), ["--tools", "Read"], "кроме Read инструментов быть не должно");
  assert.match(calls[0].systemPrompt, /segment/, "system-сообщение уходит в системный промпт");
  assert.doesNotMatch(calls[0].stdin, /SYSTEM:/);
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
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await server.chat([{ role: "user", content: "plain" }]);
  assert.equal(calls[0].args.includes("--allowedTools"), false);
  const toolsIndex = calls[0].args.indexOf("--tools");
  assert.deepEqual(calls[0].args.slice(toolsIndex, toolsIndex + 2), ["--tools", ""], "инструменты выключены на уровне CLI, не просьбой");
  assert.ok(calls[0].args.includes("--strict-mcp-config"), "MCP-серверы пользователя не поднимаются");
  assert.match(calls[0].systemPrompt, /Do not inspect files, run commands, or call tools/);
});

test("non-data image urls are rejected loudly before any spawn", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: "{}" });
  const server = new ClaudeAgentServer({
    cwd: "/repo", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await assert.rejects(
    server.chat([{ role: "user", content: [
      { type: "image_url", image_url: { url: "https://example.com/x.png" } },
    ] }]),
    /data:image/,
  );
  assert.equal(calls.length, 0);
});

test("hermetic cwd is used for headless requests instead of the project root", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
  const server = new ClaudeAgentServer({
    cwd: "/repo", hermeticCwd: "/app-data/agent-cwd/claude", spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await server.chat([{ role: "user", content: "hi" }]);
  assert.equal(calls[0].options.cwd, "/app-data/agent-cwd/claude");
});

test("system messages travel through --system-prompt-file, never through stdin", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
  const server = new ClaudeAgentServer({ spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await server.chat([
    { role: "system", content: "DESIGN CONTRACT §1" },
    { role: "user", content: "make it" },
  ], { profile: "editor" });
  const file = calls[0].args[calls[0].args.indexOf("--system-prompt-file") + 1];
  assert.ok(file, "system prompt file argument is required");
  assert.match(calls[0].systemPrompt, /Apply the requested visual edit/);
  assert.match(calls[0].systemPrompt, /DESIGN CONTRACT §1/);
  assert.doesNotMatch(calls[0].stdin, /SYSTEM:/);
  assert.doesNotMatch(calls[0].stdin, /DESIGN CONTRACT/);
  assert.match(calls[0].stdin, /USER:\nmake it/);
  assert.match(calls[0].stdin, /Final response: return only the complete JSON object required above/);
  assert.equal(existsSync(file), false, "временный системный промпт удаляется после запроса");
});

test("legacy CLI capabilities fall back to the pre-flag contract", async () => {
  const { spawnProcess, calls } = fakeSpawn({ stdout: JSON.stringify({ result: "ok" }) });
  const server = new ClaudeAgentServer({ spawnProcess,
    capabilities: { ...DEFAULT_CLAUDE_CAPABILITIES, tools: false, strictMcpConfig: false, systemPromptFile: false, effort: false },
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  await server.chat([{ role: "system", content: "CONTRACT" }, { role: "user", content: "hi" }], { effort: "high" });
  assert.deepEqual(calls[0].args, ["-p", "--output-format", "json", "--model", "opus", "--setting-sources", ""]);
  assert.equal(calls[0].options.env.MAX_THINKING_TOKENS, String(claudeEffortBudget("high")));
  assert.match(calls[0].stdin, /SYSTEM:\nCONTRACT/);
  assert.match(calls[0].stdin, /Do not inspect files, run commands, or call tools/);
  assert.equal(calls[0].systemPrompt, null);
});

test("parseClaudeCapabilities reads flags from --help, including the [-file] shorthand", () => {
  const help = [
    "  --setting-sources <sources>  Comma-separated list of setting sources",
    "  --bare  Minimal mode ... via: --system-prompt[-file], --append-system-prompt[-file]",
    "  --tools <tools...>  Specify the list of available tools",
    "  --strict-mcp-config  Only use MCP servers from --mcp-config",
    "  --effort <level>  Effort level for the current session",
  ].join("\n");
  const caps = parseClaudeCapabilities(help);
  assert.deepEqual(caps, {
    probed: true, settingSources: true, tools: true, strictMcpConfig: true, systemPromptFile: true, effort: true, jsonSchema: false,
  });
  const legacy = parseClaudeCapabilities("  --setting-sources <sources>\n  --allowedTools <tools...>\n  --toolset x");
  assert.equal(legacy.tools, false, "`--toolset` must not count as --tools");
  assert.equal(legacy.settingSources, true);
  assert.equal(legacy.effort, false);
});

test("probeCapabilities runs --help once and downgrades unsupported flags", async () => {
  const help = "  --setting-sources <sources>\n  --tools <tools...>\n";
  const { spawnProcess, calls } = fakeSpawn({ stdout: help });
  const server = new ClaudeAgentServer({ spawnProcess,
    environment: { DESIGNDNA_CLAUDE: "/opt/claude", CLAUDE_CODE_OAUTH_TOKEN: "fixture-oauth" }, fileExists: () => true,
  });
  const caps = await server.probeCapabilities();
  assert.deepEqual(calls[0].args, ["--help"]);
  assert.equal(caps.probed, true);
  assert.equal(caps.tools, true);
  assert.equal(caps.effort, false);
  assert.equal(caps.systemPromptFile, false);
  assert.equal(server.capabilities, caps);
  assert.equal(calls.length, 1);
});
