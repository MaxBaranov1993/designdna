import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { isAllowedRendererUrl } from "../lib/renderer-policy.mjs";

const appRoot = path.resolve("fixture-app");
const entry = path.join(appRoot, "static", "flow", "index.html");
const packaged = { devUrl: "", rendererEntry: entry };

test("packaged: only the exact renderer entry file is allowed", () => {
  const base = pathToFileURL(entry).href;
  assert.equal(isAllowedRendererUrl(base, packaged), true);
  assert.equal(isAllowedRendererUrl(`${base}#/flow`, packaged), true); // hash-роутинг SPA
  assert.equal(isAllowedRendererUrl(`${base}?v=1`, packaged), true);
});

test("packaged: arbitrary file: and remote URLs are rejected", () => {
  assert.equal(isAllowedRendererUrl(pathToFileURL(path.join(appRoot, "private.txt")).href, packaged), false);
  assert.equal(isAllowedRendererUrl(pathToFileURL(path.join(appRoot, "static", "flow", "evil.html")).href, packaged), false);
  assert.equal(isAllowedRendererUrl(pathToFileURL(path.join(appRoot, "other", "index.html")).href, packaged), false);
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
  assert.equal(isAllowedRendererUrl(pathToFileURL(entry).href, dev), false);
});
