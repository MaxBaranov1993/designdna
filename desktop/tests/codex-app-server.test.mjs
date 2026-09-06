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
  server.account = async () => ({ account: { type: "chatgpt" } });
  server.startThread = async (params) => { threadParams = params; return { model: "fixture-model", modelProvider: "openai", thread: { id: "thread-generator" } }; };
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
  assert.equal(threadParams.ephemeral, true);
});

test("quality judge uses a neutral read-only Codex profile", async () => {
  const server = new CodexAppServer({ cwd: "C:\\workspace" });
  let turnInput = "";
  server.start = async () => ({});
  server.account = async () => ({ account: { type: "chatgpt" } });
  server.startThread = async () => ({ model: "fixture-model", modelProvider: "openai", thread: { id: "thread-quality" } });
  server.startTurn = async ({ input }) => {
    turnInput = input[0].text;
    queueMicrotask(() => {
      server.emit("notification", {
        method: "item/completed",
        params: { threadId: "thread-quality", item: { type: "agentMessage", text: '{"score":92}' } },
      });
      server.emit("notification", {
        method: "turn/completed",
        params: { threadId: "thread-quality", turn: { status: "completed" } },
      });
    });
    return { turn: { id: "turn-quality" } };
  };
  assert.equal(
    await server.chat([{ role: "user", content: "Judge this IR" }], { profile: "quality_judge" }),
    '{"score":92}',
  );
  assert.match(turnInput, /Evaluate the supplied Design IR/);
  assert.doesNotMatch(turnInput, /Generate the requested Design IR/);
});

test("Codex chat rejects unknown profiles before starting a thread", async () => {
  const server = new CodexAppServer({ cwd: "C:\\workspace" });
  server.start = async () => ({});
  server.account = async () => ({ account: { type: "chatgpt" } });
  server.startThread = async () => { throw new Error("must not start"); };
  await assert.rejects(() => server.chat([], { profile: "unsafe" }), /Unsupported Codex chat profile/);
});

test("quality repair uses the repair Codex profile", async () => {
  const server = new CodexAppServer({ cwd: "C:\workspace" });
  let turnInput = "";
  server.start = async () => ({});
  server.account = async () => ({ account: { type: "chatgpt" } });
  server.startThread = async () => ({ model: "fixture-model", modelProvider: "openai", thread: { id: "thread-repair" } });
  server.startTurn = async ({ input }) => {
    turnInput = input[0].text;
    queueMicrotask(() => {
      server.emit("notification", {
        method: "item/completed",
        params: { threadId: "thread-repair", item: { type: "agentMessage", text: '{"version":"1.0"}' } },
      });
      server.emit("notification", {
        method: "turn/completed",
        params: { threadId: "thread-repair", turn: { status: "completed" } },
      });
    });
    return { turn: { id: "turn-repair" } };
  };
  assert.equal(
    await server.chat([{ role: "user", content: "Repair this IR" }], { profile: "quality_repair" }),
    '{"version":"1.0"}',
  );
  assert.match(turnInput, /Repair the supplied Design IR/);
  assert.doesNotMatch(turnInput, /Generate the requested Design IR/);
});

test("envelope part-arrays flatten into prompt text (not [object Object])", async () => {
  const server = new CodexAppServer({ cwd: "C:\workspace" });
  let sentPrompt = "";
  server.start = async () => ({});
  server.account = async () => ({ account: { type: "chatgpt" } });
  server.startThread = async () => ({ model: "fixture-model", modelProvider: "openai", thread: { id: "thread-parts" } });
  server.startTurn = async (params) => {
    sentPrompt = String(params.input?.[0]?.text ?? params.prompt ?? JSON.stringify(params));
    queueMicrotask(() => {
      server.emit("notification", {
        method: "item/completed",
        params: { threadId: "thread-parts", item: { type: "agentMessage", text: "{}" } },
      });
      server.emit("notification", {
        method: "turn/completed",
        params: { threadId: "thread-parts", turn: { status: "completed" } },
      });
    });
    return { turn: { id: "turn-parts" } };
  };
  await server.chat([
    { role: "system", content: [{ type: "text", text: "contract line" }] },
    { role: "user", content: [{ type: "text", text: "edit request" }] },
  ], { profile: "editor" });
  assert.ok(!sentPrompt.includes("[object Object]"), sentPrompt.slice(0, 200));
  assert.ok(sentPrompt.includes("contract line"));
  assert.ok(sentPrompt.includes("edit request"));
});

test("Codex chat surfaces provider failure with a readable error", async () => {
  const server = new CodexAppServer({ cwd: "C:\workspace" });
  server.start = async () => ({});
  server.account = async () => ({ account: { type: "chatgpt" } });
  server.startThread = async () => ({ model: "fixture-model", modelProvider: "openai", thread: { id: "thread-fail" } });
  server.startTurn = async () => {
    queueMicrotask(() => {
      server.emit("notification", {
        method: "turn/completed",
        params: { threadId: "thread-fail", turn: { status: "failed", error: { message: "provider overloaded" } } },
      });
    });
    return { turn: { id: "turn-fail" } };
  };
  await assert.rejects(
    () => server.chat([{ role: "user", content: "Judge" }], { profile: "quality_judge" }),
    /provider overloaded/,
  );
});
