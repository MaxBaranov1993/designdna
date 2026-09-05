import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const storeUrl = new URL("../src/flow/store.ts", import.meta.url);

test("addVideoChainPage builds the parallel rsale.net to video chain", async () => {
  const source = await readFile(storeUrl, "utf-8");
  const start = source.indexOf("addVideoChainPage: (options) => {");
  const end = source.indexOf("switchPage: (id) => {", start);
  assert.ok(start > 0 && end > start, "addVideoChainPage must exist in the flow store");
  const body = source.slice(start, end);

  assert.match(body, /rsale\.net/);
  assert.match(body, /mode: "url", url, mine: true/);
  assert.match(body, /const provider = "openai"/);

  for (const wiring of [
    /edge\(Number\(prompt\.id\), "out", Number\(generator\.id\), "prompt"\)/,
    /edge\(Number\(source\.id\), "tokens", Number\(generator\.id\), "designSystem"\)/,
    /edge\(Number\(generator\.id\), "ir", Number\(recorder\.id\), "ir"\)/,
    /edge\(Number\(generator\.id\), "ir", Number\(motion\.id\), "ir"\)/,
    /edge\(Number\(recorder\.id\), "interaction", Number\(motion\.id\), "interaction"\)/,
    /edge\(Number\(prompt\.id\), "out", Number\(motionDesign\.id\), "prompt"\)/,
    /edge\(Number\(motion\.id\), "motion", Number\(motionDesign\.id\), "motion"\)/,
    /edge\(Number\(motion\.id\), "video", Number\(motionDesign\.id\), "video"\)/,
  ]) {
    assert.match(body, wiring);
  }

  assert.match(body, /withCurrentPageSaved\(state\), page/);
});

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
