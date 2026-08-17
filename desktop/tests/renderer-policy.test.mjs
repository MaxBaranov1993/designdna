import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { isAllowedRendererUrl } from "../lib/renderer-policy.mjs";

const entry = path.join("C:\\app", "static", "flow", "index.html");
const packaged = { devUrl: "", rendererEntry: entry };

test("packaged: only the exact renderer entry file is allowed", () => {
  const base = "file:///C:/app/static/flow/index.html";
  assert.equal(isAllowedRendererUrl(base, packaged), true);
  assert.equal(isAllowedRendererUrl(`${base}#/flow`, packaged), true); // hash-роутинг SPA
  assert.equal(isAllowedRendererUrl(`${base}?v=1`, packaged), true);
});

test("packaged: arbitrary file: and remote URLs are rejected", () => {
  assert.equal(isAllowedRendererUrl("file:///C:/Windows/System32/drivers/etc/hosts", packaged), false);
  assert.equal(isAllowedRendererUrl("file:///C:/app/static/flow/evil.html", packaged), false);
  assert.equal(isAllowedRendererUrl("file:///C:/app/other/index.html", packaged), false);
  assert.equal(isAllowedRendererUrl("https://example.com/", packaged), false);
  assert.equal(isAllowedRendererUrl("http://127.0.0.1:8420/flow", packaged), false);
  assert.equal(isAllowedRendererUrl("javascript:alert(1)", packaged), false);
  assert.equal(isAllowedRendererUrl("not a url", packaged), false);
});

test("dev: only the dev-server origin+path is allowed", () => {
  const dev = { devUrl: "http://localhost:5173/flow", rendererEntry: entry };
  assert.equal(isAllowedRendererUrl("http://localhost:5173/flow", dev), true);
  assert.equal(isAllowedRendererUrl("http://localhost:5173/flow?t=123", dev), true); // Vite reload
  assert.equal(isAllowedRendererUrl("http://localhost:5173/other", dev), false);
  assert.equal(isAllowedRendererUrl("http://evil.localhost:5173/flow", dev), false);
  assert.equal(isAllowedRendererUrl("file:///C:/app/static/flow/index.html", dev), false);
});
