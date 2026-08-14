import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JsonlProcess } from "../lib/jsonl-process.mjs";

const desktopDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(desktopDirectory, "..");
const executable = path.join(
  desktopDirectory,
  "runtime",
  "python",
  "designdna-python",
  process.platform === "win32" ? "designdna-python.exe" : "designdna-python",
);
const temporaryData = mkdtempSync(path.join(os.tmpdir(), "designdna-runtime-"));
const worker = new JsonlProcess({
  name: "packaged DesignDNA Python runtime",
  command: executable,
  cwd: projectRoot,
  env: {
    DESIGNDNA_RUNTIME_ROOT: projectRoot,
    DESIGNDNA_APP_DIR: path.join(projectRoot, "app"),
    DESIGNDNA_DATA_DIR: temporaryData,
    PLAYWRIGHT_BROWSERS_PATH: path.join(desktopDirectory, "runtime", "playwright"),
    PLAYWRIGHT_SKIP_BROWSER_GC: "1",
  },
  timeoutMs: 120_000,
});

try {
  const health = await worker.request("health");
  if (health?.ok !== true || health?.transport !== "stdio") {
    throw new Error(`Unexpected runtime health payload: ${JSON.stringify(health)}`);
  }
  console.log(JSON.stringify(health));
} finally {
  await worker.stop();
  rmSync(temporaryData, { recursive: true, force: true });
}
