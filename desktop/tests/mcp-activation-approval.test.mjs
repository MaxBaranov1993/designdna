import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { canonicalMcpSpec, createMcpActivationApprover, mcpSpecHash, summarizeMcpSpec } from "../services/mcp-activation-approval.mjs";
import { McpManager } from "../services/mcp-manager.mjs";
import { SettingsStore } from "../services/settings-store.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));

const fixtureServer = {
  id: "fixture",
  name: "Fixture",
  enabled: true,
  transport: "stdio",
  command: process.execPath,
  args: [path.join(directory, "fixtures", "mcp-server.mjs")],
  credentialEnv: { API_KEY: "openai" },
};

test("canonical spec: deterministic, enabled-only, secrets never included", () => {
  const a = canonicalMcpSpec([fixtureServer, { id: "off", name: "Off", enabled: false, transport: "stdio", command: "rm", args: ["-rf"] }]);
  const b = canonicalMcpSpec([{ ...fixtureServer, credentialEnv: { API_KEY: "openai" }, args: [...fixtureServer.args] }]);
  assert.equal(a.length, 1);
  assert.deepEqual(a[0].credentialEnv, [["API_KEY", "openai"]]);
  assert.equal(JSON.stringify(a).includes("sk-"), false);
  assert.equal(mcpSpecHash(a), mcpSpecHash(b));
  // Изменение команды/args = другой канонический хэш = новый approval.
  const malicious = canonicalMcpSpec([{ ...fixtureServer, command: "powershell.exe", args: ["-enc", "AAAA"] }]);
  assert.notEqual(mcpSpecHash(a), mcpSpecHash(malicious));
  const changedCredential = canonicalMcpSpec([{ ...fixtureServer, credentialEnv: { OPENAI_API_KEY: "openai" } }]);
  assert.notEqual(mcpSpecHash(a), mcpSpecHash(changedCredential));
});

test("summary lists the exact command line and credential variables", () => {
  const text = summarizeMcpSpec(canonicalMcpSpec([fixtureServer]));
  assert.match(text, /Fixture \(stdio\)/);
  assert.match(text, /mcp-server\.mjs/);
  assert.match(text, /API_KEY/);
});

test("approver: native dialog gates activation, caches per canonical spec", async () => {
  let prompts = 0;
  const approver = createMcpActivationApprover({
    showMessageBox: async (options) => {
      prompts += 1;
      assert.equal(options.cancelId, 1);
      assert.equal(options.defaultId, 1); // fail-closed default
      assert.match(options.detail, /Fixture \(stdio\)/);
      return { response: 0 };
    },
  });
  const spec = canonicalMcpSpec([fixtureServer]);
  assert.equal(await approver.ensureApproved(spec), true);
  assert.equal(await approver.ensureApproved(spec), true);
  assert.equal(prompts, 1); // тот же спек — без повторного диалога
  const changed = canonicalMcpSpec([{ ...fixtureServer, args: ["--other"] }]);
  assert.equal(await approver.ensureApproved(changed), true);
  assert.equal(prompts, 2); // изменённый конфиг — новый approval
});

test("approver: decline is not cached and empty config spawns nothing", async () => {
  let prompts = 0;
  const approver = createMcpActivationApprover({
    showMessageBox: async () => { prompts += 1; return { response: 1 }; },
  });
  const spec = canonicalMcpSpec([fixtureServer]);
  assert.equal(await approver.ensureApproved(spec), false);
  assert.equal(await approver.ensureApproved(spec), false);
  assert.equal(prompts, 2); // отказ не кэшируется
  assert.equal(await approver.ensureApproved(canonicalMcpSpec([])), true);
  assert.equal(prompts, 2); // пустой конфиг не спрашивает
});

test("McpManager.refresh spawns nothing when activation is declined", async () => {
  let seenSpec = null;
  const settings = { listMcpServers: () => [fixtureServer] };
  const manager = new McpManager({
    settings,
    credentials: { get: () => null },
    cwd: directory,
    approve: async () => true,
    approveActivation: async (spec) => { seenSpec = spec; return false; },
  });
  const statuses = await manager.refresh();
  assert.equal(statuses.length, 1);
  assert.equal(statuses[0].connected, false);
  assert.match(statuses[0].error, /declined/);
  assert.equal(manager.clients.size, 0); // ни одного процесса
  assert.equal(manager.tools.size, 0);
  assert.deepEqual(seenSpec, canonicalMcpSpec([fixtureServer]));
});

test("McpManager.refresh activates only the approved canonical spec", async () => {
  const settings = { listMcpServers: () => [fixtureServer] };
  const manager = new McpManager({
    settings,
    credentials: { get: () => null },
    cwd: directory,
    approve: async () => true,
    approveActivation: async () => true,
  });
  try {
    const statuses = await manager.refresh();
    assert.equal(statuses[0].connected, true);
    const tools = await manager.listTools();
    assert.equal(tools[0].qualifiedName, "mcp_fixture__echo");
  } finally {
    manager.stop();
  }
});

test("McpManager serializes concurrent refresh activation gates", async () => {
  let releaseFirst;
  let calls = 0;
  let active = 0;
  let maxActive = 0;
  const firstGate = new Promise((resolve) => { releaseFirst = resolve; });
  const manager = new McpManager({
    settings: { listMcpServers: () => [fixtureServer] },
    credentials: { get: () => null },
    cwd: directory,
    approve: async () => true,
    approveActivation: async () => {
      calls += 1;
      active += 1;
      maxActive = Math.max(maxActive, active);
      if (calls === 1) await firstGate;
      active -= 1;
      return false;
    },
  });
  const first = manager.refresh();
  await new Promise((resolve) => setImmediate(resolve));
  const second = manager.refresh();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 1);
  releaseFirst();
  await Promise.all([first, second]);
  assert.equal(calls, 2);
  assert.equal(maxActive, 1);
});

test("SettingsStore.validateMcpServers validates without persisting", async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-settings-"));
  const store = new SettingsStore(userData);
  const normalized = store.validateMcpServers([{ name: "X", transport: "stdio", command: "node", args: ["s.js"] }]);
  assert.equal(normalized[0].id, "x");
  assert.equal(fs.existsSync(store.file), false); // dry-run: ничего не записано
  assert.throws(() => store.validateMcpServers([{ name: "X", transport: "sse", command: "node" }]), /Unsupported MCP transport/);
  assert.throws(() => store.validateMcpServers([{ name: "X", transport: "stdio" }]), /command is required/);
  assert.equal(fs.existsSync(store.file), false);
});
