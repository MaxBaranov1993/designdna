import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { resolveBuildPython } from "../lib/build-python.mjs";

const root = path.resolve("fixture-project");

test("explicit runtime build Python wins over project discovery", () => {
  assert.equal(resolveBuildPython({
    projectRoot: root,
    platform: "win32",
    environment: { DESIGNDNA_BUILD_PYTHON: "C:\\Python\\python.exe" },
    exists: () => true,
  }), "C:\\Python\\python.exe");
});

test("Windows runtime build prefers the repository virtual environment", () => {
  const expected = path.join(root, ".venv", "Scripts", "python.exe");
  assert.equal(resolveBuildPython({
    projectRoot: root,
    platform: "win32",
    environment: {},
    exists: (candidate) => candidate === expected,
  }), expected);
});

test("runtime build falls back to the platform Python command", () => {
  assert.equal(resolveBuildPython({ projectRoot: root, platform: "win32", environment: {}, exists: () => false }), "python");
  assert.equal(resolveBuildPython({ projectRoot: root, platform: "linux", environment: {}, exists: () => false }), "python3");
});
