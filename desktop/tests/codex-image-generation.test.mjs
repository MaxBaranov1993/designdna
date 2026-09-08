import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { CodexAppServer } from "../services/codex-app-server.mjs";

const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==";
function fixture({ account = "chatgpt", status = "completed", item, hold = false } = {}) {
  const server = new CodexAppServer();
  const calls = [];
  server.start = async () => {};
  server.account = async () => ({ account: { type: account } });
  server.startThread = async params => { calls.push(["thread", params]); return { modelProvider: "openai", thread: { id: "raster" } }; };
  server.request = async (method, params) => { calls.push([method, params]); };
  server.startTurn = async params => {
    calls.push(["turn", params]);
    if (!hold) queueMicrotask(() => {
      server.emit("notification", { method: "item/completed", params: { threadId: "unrelated", item: { type: "imageGeneration", status: "failed" } } });
      server.emit("notification", { method: "item/completed", params: { threadId: "raster", item: item || { type: "imageGeneration", status: "completed", result: png, transparentBackground: true } } });
      server.emit("notification", { method: "turn/completed", params: { threadId: "raster", turn: { id: "turn", status } } });
    });
    return { turn: { id: "turn" } };
  };
  return { server, calls };
}

test("native image bytes succeed with no assistant text; subscription and private workspace are preserved", async () => {
  const { server, calls } = fixture();
  const response = await server.generateImage({ prompt: "remove background", removeBackground: true, referenceImage: `data:image/png;base64,${png}` });
  assert.equal(response.image, `data:image/png;base64,${png}`);
  const thread = calls.find(([name]) => name === "thread")[1];
  assert.equal(thread.ephemeral, true); assert.equal(thread.sandbox, "read-only");
  assert.equal(thread.config["features.image_generation"], true);
  assert.equal(thread.config["features.shell_tool"], false);
  const input = calls.find(([name]) => name === "turn")[1].input;
  assert.ok(input.some(part => part.type === "localImage"));
  assert.match(input[0].text, /SEGMENTATION MASK/);
  assert.equal(existsSync(thread.cwd), false);
  assert.equal(server.listenerCount("notification"), 0);
});

test("API-key accounts fail before submitting an image turn", async () => {
  const { server, calls } = fixture({ account: "apiKey" });
  await assert.rejects(server.generateImage({ prompt: "draw" }), /ChatGPT/);
  assert.equal(calls.length, 0);
});

for (const [name, options] of [
  ["text-only response", { item: { type: "agentMessage", text: "image is ready" } }],
  ["invalid image bytes", { item: { type: "imageGeneration", status: "completed", result: "AAAA" } }],
  ["failed image tool", { item: { type: "imageGeneration", status: "failed", failure: { message: "image failed" } } }],
  ["failed turn after an image", { status: "failed" }],
]) test(`${name} is not reported as a generated image`, async () => {
  const { server } = fixture(options);
  await assert.rejects(server.generateImage({ prompt: "draw" }));
  assert.equal(server.listenerCount("notification"), 0);
});

test("cancellation interrupts only the image turn and cleans input files", async () => {
  const { server, calls } = fixture({ hold: true });
  const controller = new AbortController();
  const pending = server.generateImage({ prompt: "draw", referenceImage: `data:image/png;base64,${png}` }, { signal: controller.signal });
  await new Promise(resolve => setImmediate(resolve));
  const directory = calls[0][1].cwd;
  controller.abort();
  await assert.rejects(pending, /отменена/);
  assert.equal(existsSync(directory), false);
  assert.deepEqual(calls.find(([name]) => name === "turn/interrupt")[1], { threadId: "raster", turnId: "turn" });
});

test("timeout releases listeners and interrupts the active image turn", async () => {
  const { server, calls } = fixture({ hold: true });
  await assert.rejects(server.generateImage({ prompt: "draw" }, { timeoutMs: 20 }), /не завершил/);
  assert.ok(calls.some(([name]) => name === "turn/interrupt"));
  assert.equal(server.listenerCount("notification"), 0);
});


test("selected image model reaches native thread/start; default remains unset", async () => {
  for (const model of [undefined, 'gpt-6-astra']) {
    const { server, calls } = fixture();
    await server.generateImage({ prompt: 'draw', model });
    assert.equal(calls.find(([name]) => name === 'thread')[1].model, model);
  }
});
