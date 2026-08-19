import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { getValidToken, importFromCli, kimiAccountStatus } from "../services/kimi-account.mjs";

const memoryStore = (initial = {}) => ({
  values: { ...initial },
  get(provider) { return this.values[provider] ?? null; },
  set(provider, value) { this.values[provider] = String(value); return { provider, configured: true }; },
});

const futureExpiry = () => Math.floor(Date.now() / 1000) + 3600;
const pastExpiry = () => Math.floor(Date.now() / 1000) - 3600;

test("importFromCli stores a validated OAuth bundle and returns account status", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-kimi-home-"));
  try {
    fs.mkdirSync(path.join(home, "credentials"), { recursive: true });
    const bundle = { access_token: "cli-access", refresh_token: "cli-refresh", expires_at: futureExpiry(), token_type: "Bearer" };
    fs.writeFileSync(path.join(home, "credentials", "kimi-code.json"), JSON.stringify(bundle));
    const store = memoryStore();
    const status = importFromCli(store, { kimiCodeHome: home });
    assert.deepEqual(status, { connected: true, kind: "oauth", expiresAt: bundle.expires_at });
    const stored = JSON.parse(store.get("kimi"));
    assert.deepEqual(stored, { access_token: "cli-access", refresh_token: "cli-refresh", expires_at: bundle.expires_at });
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("importFromCli tells the user to sign in to the Kimi CLI when the file is missing", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-kimi-home-"));
  try {
    assert.throws(
      () => importFromCli(memoryStore(), { kimiCodeHome: home }),
      /Kimi CLI \(команда kimi\).*импорт/,
    );
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("getValidToken returns a plain API key unchanged", async () => {
  const store = memoryStore({ kimi: "sk-plain-key" });
  const token = await getValidToken(store, { fetchImpl: async () => { throw new Error("must not be called"); } });
  assert.equal(token, "sk-plain-key");
});

test("getValidToken passes through a fresh bundle access token without a refresh call", async () => {
  const bundle = { access_token: "fresh-access", refresh_token: "r", expires_at: futureExpiry() };
  const store = memoryStore({ kimi: JSON.stringify(bundle) });
  const token = await getValidToken(store, { fetchImpl: async () => { throw new Error("must not be called"); } });
  assert.equal(token, "fresh-access");
});

test("getValidToken refreshes an expired bundle and persists the rotated tokens", async () => {
  const bundle = { access_token: "expired-access", refresh_token: "old-refresh", expires_at: pastExpiry() };
  const store = memoryStore({ kimi: JSON.stringify(bundle) });
  let request;
  const token = await getValidToken(store, {
    fetchImpl: async (url, options) => {
      request = { url, options };
      return { ok: true, status: 200, json: async () => ({ access_token: "new-access", refresh_token: "new-refresh", expires_in: 7200 }) };
    },
  });
  assert.equal(token, "new-access");
  assert.equal(request.url, "https://auth.kimi.com/api/oauth/token");
  assert.equal(request.options.headers["Content-Type"], "application/x-www-form-urlencoded");
  assert.deepEqual(Object.fromEntries(new URLSearchParams(request.options.body)), {
    grant_type: "refresh_token",
    refresh_token: "old-refresh",
    client_id: "17e5f671-d194-4dfb-9706-5516cb48c098",
  });
  const persisted = JSON.parse(store.get("kimi"));
  assert.equal(persisted.access_token, "new-access");
  assert.equal(persisted.refresh_token, "new-refresh");
  assert.ok(persisted.expires_at > Math.floor(Date.now() / 1000));
});

test("getValidToken advises re-import when the refresh fails", async () => {
  const bundle = { access_token: "expired-access", refresh_token: "old-refresh", expires_at: pastExpiry() };
  const store = memoryStore({ kimi: JSON.stringify(bundle) });
  await assert.rejects(
    getValidToken(store, { fetchImpl: async () => ({ ok: false, status: 401, json: async () => ({}) }) }),
    /импорт из Kimi CLI/,
  );
  assert.equal(JSON.parse(store.get("kimi")).access_token, "expired-access");
});

test("getValidToken advises re-import for an expired bundle without a refresh token", async () => {
  const store = memoryStore({ kimi: JSON.stringify({ access_token: "expired-access", expires_at: pastExpiry() }) });
  await assert.rejects(getValidToken(store), /Повторите импорт/);
});

test("getValidToken requires an explicit Kimi CLI import", async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "designdna-kimi-home-"));
  process.env.KIMI_CODE_HOME = home;
  try {
    fs.mkdirSync(path.join(home, "credentials"), { recursive: true });
    const bundle = { access_token: "not-silently-imported", refresh_token: "r", expires_at: futureExpiry() };
    fs.writeFileSync(path.join(home, "credentials", "kimi-code.json"), JSON.stringify(bundle));
    const store = memoryStore();
    await assert.rejects(getValidToken(store), /Явно импортируйте аккаунт Kimi CLI/);
    assert.equal(store.get("kimi"), null);
  } finally {
    delete process.env.KIMI_CODE_HOME;
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("kimiAccountStatus reflects missing, plain-key, and OAuth credentials", () => {
  assert.deepEqual(kimiAccountStatus(memoryStore()), { connected: false, kind: null, expiresAt: null });
  assert.deepEqual(kimiAccountStatus(memoryStore({ kimi: "sk-plain-key" })), { connected: true, kind: "api-key", expiresAt: null });
  const expiresAt = futureExpiry();
  assert.deepEqual(
    kimiAccountStatus(memoryStore({ kimi: JSON.stringify({ access_token: "a", expires_at: expiresAt }) })),
    { connected: true, kind: "oauth", expiresAt },
  );
});
