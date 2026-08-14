import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { SettingsStore } from "../services/settings-store.mjs";

test("MCP settings persist only stdio servers and approved credential references", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-settings-"));
  try {
    const store = new SettingsStore(directory);
    const saved = store.saveMcpServers([{ name: "Kimi tools", transport: "stdio", command: "kimi-mcp", args: ["serve"], credentialEnv: { KIMI_API_KEY: "kimi" } }]);
    assert.equal(saved[0].id, "kimi-tools");
    assert.deepEqual(store.listMcpServers(), saved);
    assert.throws(() => store.saveMcpServers([{ name: "Blocked", transport: "stdio", command: "x", credentialEnv: { API_KEY: "anthropic" } }]), /unsupported credential reference/);
    assert.throws(() => store.saveMcpServers([{ name: "Remote", transport: "http", url: "https://example.com/mcp" }]), /Unsupported MCP transport/);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});
