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
    /edge\(Number\(source\.id\), "tokens", Number\(generator\.id\), "tokens"\)/,
    /edge\(Number\(generator\.id\), "ir", Number\(recorder\.id\), "ir"\)/,
    /edge\(Number\(generator\.id\), "ir", Number\(motion\.id\), "ir"\)/,
    /edge\(Number\(recorder\.id\), "interaction", Number\(motion\.id\), "interaction"\)/,
  ]) {
    assert.match(body, wiring);
  }

  assert.match(body, /withCurrentPageSaved\(state\), page/);
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
