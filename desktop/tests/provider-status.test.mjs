import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import {
  getProviderStatus,
  probeCommand,
  providerCommand,
  resetProviderStatusCache,
} from "../services/provider-status.mjs";

test("provider status resolves Windows CLI shims through cmd.exe", () => {
  const spec = providerCommand(
    { command: "codex", args: ["--version"] },
    { platform: "win32", environment: { ComSpec: "C:\\Windows\\System32\\cmd.exe" } },
  );
  assert.equal(spec.command, "C:\\Windows\\System32\\cmd.exe");
  assert.deepEqual(spec.args.slice(0, 3), ["/d", "/s", "/c"]);
  assert.match(spec.args[3], /codex --version$/);
});

test("provider status keeps direct execution on non-Windows", () => {
  assert.deepEqual(
    providerCommand({ command: "codex", args: ["--version"] }, { platform: "linux", environment: {} }),
    { command: "codex", args: ["--version"] },
  );
});

test("provider status honours explicit binary override env", () => {
  assert.deepEqual(
    providerCommand(
      { command: "claude", args: ["--version"], overrideEnv: "DESIGNDNA_CLAUDE" },
      { platform: "win32", environment: { DESIGNDNA_CLAUDE: "D:\\bin\\claude.exe" } },
    ),
    { command: "D:\\bin\\claude.exe", args: ["--version"] },
  );
});

test("provider status uses the same native Claude discovery as chat", () => {
  const binary = "C:\\Users\\qa\\.local\\bin\\claude.exe";
  assert.deepEqual(providerCommand({ command: "claude", args: ["--version"] }, {
    platform: "win32", environment: { USERPROFILE: "C:\\Users\\qa", PATH: "" },
    fileExists: (candidate) => candidate === binary,
  }), { command: binary, args: ["--version"] });
});

/* Фейковый child_process: сценарий задаёт stdout/код выхода/ошибку/зависание. */
function fakeSpawn(scenario) {
  const calls = [];
  const spawnImpl = (command, args) => {
    calls.push({ command, args });
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => { child.killed = true; };
    setImmediate(() => {
      if (scenario.error) { child.emit("error", scenario.error); return; }
      if (scenario.hang) return;
      if (scenario.stdout) child.stdout.emit("data", Buffer.from(scenario.stdout));
      if (scenario.stderr) child.stderr.emit("data", Buffer.from(scenario.stderr));
      child.emit("exit", scenario.code ?? 0);
    });
    return child;
  };
  return { spawnImpl, calls };
}

test("probeCommand reports version on exit 0", async () => {
  const { spawnImpl } = fakeSpawn({ stdout: "codex-cli 1.2.3\n" });
  const result = await probeCommand({ command: "codex", args: ["--version"] }, { spawnImpl, platform: "linux", environment: {} });
  assert.deepEqual(result, { installed: true, version: "codex-cli 1.2.3", error: null });
});

test("probeCommand reports missing binary and non-zero exit", async () => {
  const missing = await probeCommand({ command: "codex", args: ["--version"] }, {
    spawnImpl: fakeSpawn({ error: new Error("spawn codex ENOENT") }).spawnImpl, platform: "linux", environment: {},
  });
  assert.equal(missing.installed, false);
  assert.match(missing.error, /ENOENT/);
  const failed = await probeCommand({ command: "codex", args: ["--version"] }, {
    spawnImpl: fakeSpawn({ code: 1, stderr: "not recognized" }).spawnImpl, platform: "linux", environment: {},
  });
  assert.equal(failed.installed, false);
  assert.match(failed.error, /not recognized/);
});

test("probeCommand kills a hanging process after the timeout", async () => {
  const { spawnImpl } = fakeSpawn({ hang: true });
  const result = await probeCommand({ command: "codex", args: ["--version"] }, { spawnImpl, platform: "linux", environment: {}, timeoutMs: 30 });
  assert.equal(result.installed, false);
  assert.match(result.error, /timeout/);
});

test("getProviderStatus probes CLIs once per cache window and reflects API key", async () => {
  resetProviderStatusCache();
  let clock = 1_000_000;
  const probed = [];
  const probe = async (definition) => { probed.push(definition.command); return { installed: definition.command === "codex", version: "v", error: definition.command === "codex" ? null : "ENOENT" }; };
  const options = { hasCredential: (id) => id === "openai", now: () => clock, probe, platform: "linux", environment: {} };
  const first = await getProviderStatus(options);
  const byId = Object.fromEntries(first.map((item) => [item.id, item]));
  assert.equal(byId.openai.installed, true);
  assert.equal(byId.codex.installed, true);
  assert.equal(byId.claude.installed, false);
  assert.equal(byId.claude.reason, "ENOENT");
  assert.equal(byId.codex.cached, false);
  assert.ok(!("command" in byId.codex));
  assert.deepEqual(probed.sort(), ["claude", "codex"]);

  clock += 30_000;
  const second = await getProviderStatus({ ...options, hasCredential: () => false });
  assert.equal(probed.length, 2, "внутри окна кэша CLI не перепроверяются");
  assert.equal(second.find((item) => item.id === "codex").cached, true);
  assert.equal(second.find((item) => item.id === "openai").installed, false);

  clock += 31_000;
  await getProviderStatus(options);
  assert.equal(probed.length, 4, "после 60 с кэш истёк");
  resetProviderStatusCache();
});
