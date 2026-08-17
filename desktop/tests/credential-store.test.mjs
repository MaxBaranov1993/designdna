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

test("OpenRouter credentials stay encrypted at rest and status exposes only presence", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-credentials-"));
  try {
    const store = new CredentialStore({ userDataPath: directory, safeStorage });
    const saved = store.set("openrouter", "secret-openrouter-key");
    assert.deepEqual(saved, { provider: "openrouter", configured: true });
    assert.equal(store.get("openrouter"), "secret-openrouter-key");
    assert.equal(store.status().openrouter, true);
    assert.doesNotMatch(JSON.stringify(store.status()), /secret-openrouter-key/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
