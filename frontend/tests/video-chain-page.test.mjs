import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const storeUrl = new URL("../src/flow/store.ts", import.meta.url);

// The new Page → Video workspace is covered by executable store tests in video-history.test.mjs.

test("Motion Design keeps planning separate from the confirmed paid Seedance call", async () => {
  const store = await readFile(storeUrl, "utf-8");
  const node = await readFile(new URL("../src/nodes/MotionDesignNode.svelte", import.meta.url), "utf-8");
  const ports = await readFile(new URL("../src/flow/ports.ts", import.meta.url), "utf-8");

  assert.match(ports, /motiondesign: \{ title: "Motion Design"/);
  assert.match(ports, /\{ name: "video", label: "готовое видео", kind: "video" \}/);
  assert.match(store, /planMotionDesign:/);
  assert.match(store, /runMotionDesign: async \(id, confirmedPaid\)/);
  assert.match(store, /confirmed_paid: true/);
  assert.match(store, /type: "video_url"/);
  assert.match(store, /job сохранён/);
  assert.match(node, /Подтверждаю платный вызов/);
  assert.match(node, /Claude Code/);
  assert.match(node, /GPT-5\.6 Sol/);
});

test("PagesPanel exposes the video-branch button next to + Page", async () => {
  const source = await readFile(new URL("../src/PagesPanel.svelte", import.meta.url), "utf-8");
  assert.match(source, /addVideoChainPage\(\)/);
});

test("Generator node routes provider and effort through the shared picker", async () => {
  const source = await readFile(new URL("../src/nodes/GeneratorNode.svelte", import.meta.url), "utf-8");
  assert.match(source, /\["medium", "high", "max"\]\.includes\(data\.effort\)/);
  assert.match(source, /ProviderPicker/);
  assert.doesNotMatch(source, /zcode|kimi|grok|glm/i);

  const picker = await readFile(new URL("../src/components/ProviderPicker.svelte", import.meta.url), "utf-8");
  // Закрытый контракт выбора: Sol, Codex, Claude — и только три усилия.
  assert.match(picker, /GPT-5\.6 Sol/);
  assert.match(picker, /Codex/);
  assert.match(picker, /Claude Opus/);
  for (const effort of ["medium", "high", "max"]) {
    assert.match(picker, new RegExp(`value: "${effort}"`));
  }
  assert.doesNotMatch(picker, /zcode|kimi|grok|glm/i);
});
