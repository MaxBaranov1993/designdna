import { createInterface } from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workerDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(workerDirectory, "../..");
const projectRoot = path.resolve(process.env.DESIGNDNA_PROJECT_ROOT || process.argv[2] || repositoryRoot);
process.env.REPO_CANVAS_ROOT = projectRoot;

const store = await import("../../tools/repo-canvas/repo-canvas/scripts/canvas-store.mjs");
const { runArchitect } = await import("../../tools/repo-canvas/repo-canvas/scripts/architect.mjs");

function result(id, value) {
  process.stdout.write(`${JSON.stringify({ id, result: value })}\n`);
}

function failure(id, error) {
  process.stdout.write(`${JSON.stringify({
    id,
    error: { code: error.code || "REPO_CANVAS_ERROR", message: error.message, data: error.data },
  })}\n`);
}

async function dispatch(method, params) {
  if (method === "health") return { ok: true, projectRoot, transport: "stdio" };
  if (method === "snapshot") return store.getSnapshot();
  if (method === "check") {
    const snapshot = store.getSnapshot();
    return { ok: snapshot.errors.length === 0, errors: snapshot.errors, summary: snapshot.summary, revision: snapshot.revision };
  }
  if (method === "architect.refresh") {
    return runArchitect({ root: projectRoot, refresh: true, model: params?.model, effort: params?.effort });
  }
  if (method === "shutdown") return { ok: true, shutdown: true };
  throw Object.assign(new Error(`Unknown method: ${method}`), { code: "METHOD_NOT_FOUND" });
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  let message;
  try {
    message = JSON.parse(line);
    const value = await dispatch(message.method, message.params || {});
    result(message.id, value);
    if (value?.shutdown) process.exit(0);
  } catch (error) {
    failure(message?.id ?? null, error);
  }
}
