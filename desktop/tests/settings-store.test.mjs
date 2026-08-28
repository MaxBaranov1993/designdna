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
    const saved = store.saveMcpServers([{ name: "OpenAI tools", transport: "stdio", command: "openai-mcp", args: ["serve"], credentialEnv: { OPENAI_API_KEY: "openai" } }]);
    assert.equal(saved[0].id, "openai-tools");
    assert.deepEqual(store.listMcpServers(), saved);
    assert.throws(() => store.saveMcpServers([{ name: "Blocked", transport: "stdio", command: "x", credentialEnv: { API_KEY: "anthropic" } }]), /unsupported credential reference/);
    assert.throws(() => store.saveMcpServers([{ name: "Remote", transport: "http", url: "https://example.com/mcp" }]), /Unsupported MCP transport/);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test("MCP stdio servers may reference only the OpenAI credential without storing secrets", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-settings-"));
  try {
    const store = new SettingsStore(directory);
    const saved = store.saveMcpServers([{
      name: "OpenAI tools",
      transport: "stdio",
      command: "openai-mcp",
      credentialEnv: { OPENAI_API_KEY: "openai" },
    }]);
    assert.deepEqual(saved[0].credentialEnv, { OPENAI_API_KEY: "openai" });
    // persistence round-trip keeps the references
    assert.deepEqual(store.listMcpServers()[0].credentialEnv, saved[0].credentialEnv);
    // settings.json holds provider NAMES only — never secret material
    const onDisk = fs.readFileSync(path.join(directory, "settings.json"), "utf8");
    assert.doesNotMatch(onDisk, /sk-|xai-[A-Za-z0-9]|Bearer\s/i);
    for (const reference of saved[0].credentialEnv ? Object.values(saved[0].credentialEnv) : []) {
      assert.equal(reference, "openai");
    }
    for (const retired of ["kimi", "glm", "zai", "grok", "zcode", "codex"]) {
      assert.throws(() => store.saveMcpServers([{ name: "Bad", transport: "stdio", command: "x", credentialEnv: { KEY: retired } }]), /unsupported credential reference/);
    }
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});
