import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { CredentialStore } from "../services/credential-store.mjs";

const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (value) => Buffer.from(value, "utf8"),
  decryptString: (value) => value.toString("utf8"),
};

test("Provider credentials stay encrypted at rest and status exposes only presence", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    const saved = store.set("kimi", "secret-kimi-key");
    assert.deepEqual(saved, { provider: "kimi", configured: true });
    assert.equal(store.get("kimi"), "secret-kimi-key");
    assert.deepEqual(store.status(), { openai: false, kimi: true, glm: false, grok: false, zai: false });
    assert.doesNotMatch(JSON.stringify(store.status()), /secret-kimi-key/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("Removed openrouter provider is rejected", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    assert.throws(() => store.set("openrouter", "legacy-key"), /Unsupported provider: openrouter/);
    assert.throws(() => store.get("openrouter"), /Unsupported provider: openrouter/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("A stored openrouter entry is silently discarded on load", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const file = path.join(directory, "credentials.bin");
    fs.writeFileSync(file, safeStorage.encryptString(JSON.stringify({ openrouter: "legacy-key", kimi: "kept-key" })));
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    assert.deepEqual(store.status(), { openai: false, kimi: true, glm: false, grok: false, zai: false });
    assert.equal(store.get("kimi"), "kept-key");
    const persisted = JSON.parse(safeStorage.decryptString(fs.readFileSync(file)));
    assert.deepEqual(persisted, { kimi: "kept-key" });
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});


test("GLM key is stored and reported like other providers", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    store.set("glm", "zhipu-key");
    assert.equal(store.get("glm"), "zhipu-key");
    assert.deepEqual(store.status(), { openai: false, kimi: false, glm: true, grok: false, zai: false });
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("Z.AI key is a separate credential from the Zhipu GLM key", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    store.set("glm", "zhipu-key");
    store.set("zai", "zai-direct-key");
    assert.equal(store.get("glm"), "zhipu-key");
    assert.equal(store.get("zai"), "zai-direct-key");
    assert.deepEqual(store.status(), { openai: false, kimi: false, glm: true, grok: false, zai: true });
    // deleting one must not touch the other
    store.delete("zai");
    assert.equal(store.get("zai"), null);
    assert.equal(store.get("glm"), "zhipu-key");
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
