import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { LiveCommandPipeServer, liveCommandEndpoint } from "../services/live-command-pipe-server.mjs";

function call(endpoint, message) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(endpoint);
    let text = "";
    socket.setEncoding("utf8");
    socket.on("connect", () => socket.write(`${JSON.stringify(message)}\n`));
    socket.on("data", (chunk) => { text += chunk; });
    socket.on("end", () => resolve(JSON.parse(text)));
    socket.on("error", reject);
  });
}

test("capability-gated local pipe executes a command and rejects a bad token", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "ddna-live-pipe-"));
  const endpoint = process.platform === "win32" ? `\\\\.\\pipe\\ddna-test-${process.pid}-${Date.now()}` : path.join(directory, "test.sock");
  const seen = [];
  const server = new LiveCommandPipeServer({ dataDirectory: directory, endpoint, execute: async (command) => { seen.push(command); return { revision: "a".repeat(64) }; } });
  try {
    await server.start();
    const capability = JSON.parse(await readFile(path.join(directory, "live-command.json"), "utf8"));
    const accepted = await call(endpoint, { token: capability.token, requestId: "r1", command: { action: "project.get" } });
    assert.equal(accepted.ok, true);
    assert.equal(accepted.result.revision, "a".repeat(64));
    assert.deepEqual(seen, [{ action: "project.get" }]);
    const rejected = await call(endpoint, { token: "bad", command: {} });
    assert.equal(rejected.error.code, "UNAUTHORIZED");
  } finally {
    await server.stop();
    await rm(directory, { recursive: true, force: true });
  }
});

test("pipe names are stable per data directory and platform", () => {
  assert.equal(liveCommandEndpoint("C:/data", "win32"), liveCommandEndpoint("C:/data", "win32"));
  assert.notEqual(liveCommandEndpoint("C:/data-a", "win32"), liveCommandEndpoint("C:/data-b", "win32"));
});

test("startup replaces a capability document left by a crashed process", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "ddna-live-stale-"));
  const endpoint = process.platform === "win32" ? `\\\\.\\pipe\\ddna-stale-${process.pid}-${Date.now()}` : path.join(directory, "stale.sock");
  const capabilityPath = path.join(directory, "live-command.json");
  await writeFile(capabilityPath, JSON.stringify({ version: 1, token: "stale" }), "utf8");
  const server = new LiveCommandPipeServer({ dataDirectory: directory, endpoint, execute: async () => ({}) });
  try {
    await server.start();
    const capability = JSON.parse(await readFile(capabilityPath, "utf8"));
    assert.notEqual(capability.token, "stale");
    assert.equal(capability.pid, process.pid);
    assert.equal(server.info().listening, true);
  } finally {
    await server.stop();
    await rm(directory, { recursive: true, force: true });
  }
});
