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
  const configured = await worker.request("runtime.configure", { openaiApiKey: "runtime-smoke-only", kimiApiKey: "runtime-smoke-only" });
  if (configured?.openaiConfigured !== true || configured?.kimiConfigured !== true || JSON.stringify(configured).includes("runtime-smoke-only")) {
    throw new Error(`Packaged credential configuration failed: ${JSON.stringify(configured)}`);
  }
  const config = await worker.request("http.request", {
    method: "GET",
    path: "/api/config",
  });
  if (config?.status !== 200 || !String(config?.headers?.["content-type"] || "").includes("application/json")) {
    throw new Error(`Packaged ASGI request failed: ${JSON.stringify(config)}`);
  }
  console.log(JSON.stringify({ ...health, apiStatus: config.status }));
} finally {
  await worker.stop();
  rmSync(temporaryData, { recursive: true, force: true });
}
