import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pythonWorkerEnvironment, pythonWorkerSpec } from "../lib/runtime-paths.mjs";

test("packaged Windows uses the bundled Python sidecar", () => {
  const spec = pythonWorkerSpec({
    isPackaged: true,
    platform: "win32",
    resourcesPath: path.join("C:", "DesignDNA", "resources"),
    sourceRoot: "ignored",
    pythonOverride: "ignored",
  });
  assert.equal(spec.args.length, 0);
  assert.match(spec.command, /runtime[\\/]python[\\/]designdna-python[\\/]designdna-python\.exe$/);
});

test("packaged macOS uses the bundled Python sidecar", () => {
  const spec = pythonWorkerSpec({
    isPackaged: true,
    platform: "darwin",
    resourcesPath: "/Applications/DesignDNA.app/Contents/Resources",
    sourceRoot: "ignored",
  });
  assert.equal(spec.args.length, 0);
  assert.match(spec.command, /runtime\/python\/designdna-python\/designdna-python$/);
});

test("development keeps the source worker and explicit Python override", () => {
  const spec = pythonWorkerSpec({
    isPackaged: false,
    platform: "linux",
    resourcesPath: "ignored",
    sourceRoot: "/workspace/designdna",
    pythonOverride: "/venv/bin/python",
  });
  assert.equal(spec.command, "/venv/bin/python");
  assert.equal(spec.args[0], "/workspace/designdna/app/desktop_worker.py");
});

test("packaged environment separates read-only runtime from writable data", () => {
  const environment = pythonWorkerEnvironment({
    isPackaged: true,
    runtimeRoot: "/Applications/DesignDNA.app/Contents/Resources",
    userDataPath: "/Users/max/Library/Application Support/DesignDNA",
  });
  assert.equal(environment.DESIGNDNA_APP_DIR, path.join("/Applications/DesignDNA.app/Contents/Resources", "app"));
  assert.equal(environment.DESIGNDNA_DATA_DIR, path.join("/Users/max/Library/Application Support/DesignDNA", "data"));
  assert.equal(
    environment.PLAYWRIGHT_BROWSERS_PATH,
    path.join("/Applications/DesignDNA.app/Contents/Resources", "runtime", "playwright"),
  );
});
