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

test("only the OpenAI credential is stored and status exposes presence", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    assert.deepEqual(store.set("openai", "secret-openai-key"), { provider: "openai", configured: true });
    assert.equal(store.get("openai"), "secret-openai-key");
    assert.deepEqual(store.status(), { openai: true });
    assert.doesNotMatch(JSON.stringify(store.status()), /secret-openai-key/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("retired providers are rejected", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    for (const provider of ["codex", "kimi", "glm", "zai", "grok", "zcode", "openrouter"]) {
      assert.throws(() => store.set(provider, "legacy-key"), new RegExp(`Unsupported provider: ${provider}`));
    }
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("loading credentials deletes all retired secrets and preserves OpenAI", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const file = path.join(directory, "credentials.bin");
    fs.writeFileSync(file, safeStorage.encryptString(JSON.stringify({
      openai: "kept-openai-key", kimi: "deleted-kimi", glm: "deleted-glm", grok: "deleted-grok",
    })));
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    assert.deepEqual(store.status(), { openai: true });
    assert.equal(store.get("openai"), "kept-openai-key");
    const persisted = JSON.parse(safeStorage.decryptString(fs.readFileSync(file)));
    assert.deepEqual(persisted, { openai: "kept-openai-key" });
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
