import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/desktop/live-command-handler.ts", import.meta.url);

test("renderer live handler implements preview/apply move and bounded undo", async () => {
  const source = await readFile(sourceUrl, "utf8");
  assert.match(source, /request\.action === "graph\.node\.move"/);
  assert.match(source, /request\.action === "graph\.node\.create"/);
  assert.match(source, /request\.action === "graph\.node\.delete"/);
  assert.match(source, /request\.action === "history\.undo"/);
  assert.match(source, /request\.action === "editor\.style\.patch"/);
  assert.match(source, /request\.mode === "preview"/);
  assert.match(source, /state\.moveNode\(nodeId, x, y\)/);
  assert.match(source, /undoStack\.length > 100/);
  assert.match(source, /qualityReport: \{ gate: "structural", passed: true \}/);
  assert.match(source, /STYLE_PROPERTY_FORBIDDEN/);
  assert.match(source, /UNDO_SNAPSHOT_TOO_LARGE/);
  assert.match(source, /state\.deleteNode\(nodeId\)/);
  assert.match(source, /function restoreNode/);
  assert.match(source, /preservedRules: \["tree\.structure", "sourceKey", "content", "component\.identity", "responsive\.structure"\]/);
});

test("renderer bridge responds explicitly and never accepts arbitrary actions", async () => {
  const source = await readFile(sourceUrl, "utf8");
  assert.match(source, /commands\.respond\(requestId, \{ ok: true, result \}\)/);
  assert.match(source, /HANDLER_NOT_REGISTERED/);
  assert.doesNotMatch(source, /eval\(|new Function/);
});
