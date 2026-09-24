import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Regression (glebkudr presentation, 2026-09-24): pages sit in frame-sized
// clipped boxes inside the camera wrapper, so a camera-pan moved the clip
// itself and every frame after the first seconds rendered blank.
test("story player turns the camera's vertical pan into a page scroll", async () => {
  const source = (await readFile(new URL("../src/engine/video-story.ts", import.meta.url), "utf8")).replace(/\r\n/g, "\n");
  const seek = source.slice(source.indexOf("  seek(time: number)"));
  assert.match(seek, /const panY = cameraState \? cameraState\.y : 0;/);
  assert.match(seek, /\[CAMERA_LAYER_ID\]: \{ \.\.\.cameraState, y: 0 \}/, "the frame wrapper no longer moves vertically");
  assert.match(seek, /\(scrolls\[id\] \|\| 0\) - panY \/ root\.scale/, "the pan scrolls every page inside the frame");
  assert.match(seek, /Math\.min\(max, Math\.max\(0,/, "the scroll stays within the page");
});
