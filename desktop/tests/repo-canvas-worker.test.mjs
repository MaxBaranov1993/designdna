import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { JsonlProcess } from "../lib/jsonl-process.mjs";

const desktopDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(desktopDirectory, "..");

test("Repo Canvas runs as an internal stdio service", async () => {
  const worker = new JsonlProcess({
    command: process.execPath,
    args: [path.join(desktopDirectory, "workers", "repo-canvas-worker.mjs"), repositoryRoot],
    cwd: repositoryRoot,
    env: { DESIGNDNA_PROJECT_ROOT: repositoryRoot },
    name: "repo-canvas test worker",
  });
  const health = await worker.request("health");
  assert.equal(health.ok, true);
  assert.equal(health.transport, "stdio");
  const snapshot = await worker.request("snapshot");
  assert.ok(Array.isArray(snapshot.areas));
  assert.ok(Array.isArray(snapshot.entities));
  await worker.stop();
});
