import assert from "node:assert/strict";
import test from "node:test";
import { CodexAppServer, codexProcessSpec } from "../services/codex-app-server.mjs";

test("Windows launches the Codex npm shim through cmd without shell mode", () => {
  const spec = codexProcessSpec({ platform: "win32", environment: { ComSpec: "C:\\Windows\\System32\\cmd.exe" } });
  assert.equal(spec.command, "C:\\Windows\\System32\\cmd.exe");
  assert.deepEqual(spec.args, ["/d", "/s", "/c", "chcp 65001>nul && codex app-server --listen stdio://"]);
});

test("an explicit Codex executable bypasses platform discovery", () => {
  const spec = codexProcessSpec({ platform: "win32", environment: { DESIGNDNA_CODEX: "C:\\Tools\\codex.exe" } });
  assert.equal(spec.command, "C:\\Tools\\codex.exe");
  assert.deepEqual(spec.args, ["app-server", "--listen", "stdio://"]);
});

test("generator chat collects the authoritative Codex agent message", async () => {
  const server = new CodexAppServer({ cwd: "C:\\workspace" });
  let threadParams;
  server.start = async () => ({});
  server.startThread = async (params) => { threadParams = params; return { thread: { id: "thread-generator" } }; };
  server.startTurn = async () => {
    queueMicrotask(() => {
      server.emit("notification", {
        method: "item/completed",
        params: { threadId: "thread-generator", item: { type: "agentMessage", text: '{"version":"1.0"}' } },
      });
      server.emit("notification", {
        method: "turn/completed",
        params: { threadId: "thread-generator", turn: { status: "completed" } },
      });
    });
    return { turn: { id: "turn-generator" } };
  };
  assert.equal(await server.chat([{ role: "user", content: "Generate IR" }]), '{"version":"1.0"}');
  assert.equal(threadParams.sandbox, "read-only");
  assert.equal(threadParams.approvalPolicy, "never");
});
