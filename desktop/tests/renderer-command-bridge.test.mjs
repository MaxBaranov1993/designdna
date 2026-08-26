import assert from "node:assert/strict";
import test from "node:test";
import { RendererCommandBridge } from "../services/renderer-command-bridge.mjs";

test("routes one cloned command to the current renderer and resolves once", async () => {
  let delivered;
  const bridge = new RendererCommandBridge({ getTarget: () => ({ id: "renderer-1", send: (_channel, payload) => { delivered = payload; } }) });
  const command = { action: "graph.node.move", arguments: { nodeId: "1", x: 10, y: 20 } };
  const pending = bridge.request(command);
  command.arguments.x = 999;
  assert.equal(delivered.command.arguments.x, 10);
  assert.deepEqual(bridge.respond("renderer-1", { requestId: delivered.requestId, ok: true, result: { applied: true } }), { accepted: true });
  assert.deepEqual(await pending, { applied: true });
  assert.deepEqual(bridge.respond("renderer-1", { requestId: delivered.requestId, ok: true, result: {} }), { accepted: false });
});

test("rejects spoofed renderer responses without consuming the pending command", async () => {
  let delivered;
  const bridge = new RendererCommandBridge({ getTarget: () => ({ id: "renderer-1", send: (_channel, payload) => { delivered = payload; } }) });
  const pending = bridge.request({ action: "graph.node.move" });
  assert.throws(() => bridge.respond("renderer-2", { requestId: delivered.requestId, ok: true, result: {} }), (error) => error.code === "RENDERER_MISMATCH");
  bridge.respond("renderer-1", { requestId: delivered.requestId, ok: false, error: { code: "INVALID", message: "bad command" } });
  await assert.rejects(pending, (error) => error.code === "INVALID");
});

test("detach and timeout reject pending work", async () => {
  let delivered;
  const bridge = new RendererCommandBridge({ getTarget: () => ({ id: "renderer-1", send: (_channel, payload) => { delivered = payload; } }) });
  const detached = bridge.request({ action: "graph.node.move" });
  assert.equal(bridge.detach("renderer-1"), 1);
  await assert.rejects(detached, (error) => error.code === "RENDERER_DETACHED");
  const timedOut = bridge.request({ action: "graph.node.move" }, 100);
  assert.ok(delivered.requestId);
  await assert.rejects(timedOut, (error) => error.code === "RENDERER_TIMEOUT");
});
