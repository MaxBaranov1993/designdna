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

test("OpenAI and OpenRouter credentials are stored and status exposes only presence", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    assert.deepEqual(store.set("openai", "secret-openai-key"), { provider: "openai", configured: true });
    assert.deepEqual(store.set("openrouter", "secret-openrouter-key"), { provider: "openrouter", configured: true });
    assert.equal(store.get("openai"), "secret-openai-key");
    assert.equal(store.get("openrouter"), "secret-openrouter-key");
    assert.deepEqual(store.status(), { openai: true, openrouter: true, claude: false });
    assert.doesNotMatch(JSON.stringify(store.status()), /secret-openai-key/);
    assert.doesNotMatch(JSON.stringify(store.status()), /secret-openrouter-key/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("retired providers are rejected", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    for (const provider of ["codex", "kimi", "glm", "zai", "grok", "zcode"]) {
      assert.throws(() => store.set(provider, "legacy-key"), new RegExp(`Unsupported provider: ${provider}`));
    }
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("loading credentials deletes retired secrets and preserves OpenAI plus OpenRouter", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const file = path.join(directory, "credentials.bin");
    fs.writeFileSync(file, safeStorage.encryptString(JSON.stringify({
      openai: "kept-openai-key", openrouter: "kept-openrouter-key",
      kimi: "deleted-kimi", glm: "deleted-glm", grok: "deleted-grok",
    })));
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    assert.deepEqual(store.status(), { openai: true, openrouter: true, claude: false });
    assert.equal(store.get("openai"), "kept-openai-key");
    assert.equal(store.get("openrouter"), "kept-openrouter-key");
    const persisted = JSON.parse(safeStorage.decryptString(fs.readFileSync(file)));
    assert.deepEqual(persisted, { openai: "kept-openai-key", openrouter: "kept-openrouter-key" });
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
