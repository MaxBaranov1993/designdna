import assert from "node:assert/strict";
import test from "node:test";

import {
  attachSourceAuthCookies,
  normalizeSourceAuthCookies,
  sourceAuthIntent,
  validateSourceAuthUrl,
} from "../services/source-auth.mjs";

const requestFor = (payload) => ({
  method: "POST",
  path: "/api/block-parse",
  encoding: "base64",
  body: Buffer.from(JSON.stringify(payload)).toString("base64"),
});

test("source auth accepts only credential-free http URLs", () => {
  assert.equal(validateSourceAuthUrl("https://example.com/account"), "https://example.com/account");
  assert.throws(() => validateSourceAuthUrl("file:///tmp/private"), /http\/https/);
  assert.throws(() => validateSourceAuthUrl("https://user:pass@example.com"), /credentials/);
});

test("source auth intent is limited to block parse", () => {
  const request = requestFor({ url: "https://example.com/private", useAuthenticatedSession: true });
  assert.equal(sourceAuthIntent(request)?.url, "https://example.com/private");
  assert.equal(sourceAuthIntent({ ...request, path: "/api/reskin" }), null);
});

test("cookies are scoped to the imported host and inserted only in the request body", () => {
  const cookies = [
    { name: "session", value: "secret", domain: ".example.com", path: "/", secure: true, httpOnly: true, sameSite: "lax" },
    { name: "foreign", value: "drop", domain: ".evil.test", path: "/" },
  ];
  assert.equal(normalizeSourceAuthCookies(cookies, "https://app.example.com/private").length, 1);
  const attached = attachSourceAuthCookies(
    requestFor({ url: "https://app.example.com/private", useAuthenticatedSession: true }),
    cookies,
    "https://app.example.com/private",
  );
  const payload = JSON.parse(Buffer.from(attached.body, "base64").toString("utf8"));
  assert.equal(payload.useAuthenticatedSession, undefined);
  assert.deepEqual(payload.authCookies.map((cookie) => cookie.name), ["session"]);
  assert.equal(attached.headers["content-length"], String(Buffer.byteLength(Buffer.from(attached.body, "base64"))));
  assert.equal(JSON.stringify({ ...attached, body: "" }).includes("secret"), false);
});

test("an empty authenticated session falls back to a public import", () => {
  const attached = attachSourceAuthCookies(
    requestFor({ url: "https://example.com", useAuthenticatedSession: true }),
    [],
    "https://example.com",
  );
  const payload = JSON.parse(Buffer.from(attached.body, "base64").toString("utf8"));
  assert.equal(payload.useAuthenticatedSession, undefined);
  assert.equal(payload.authCookies, undefined);
  assert.equal(payload.authSessionFallback, true);
});
