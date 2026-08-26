import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/* Контракт параллельной видео-ветки: страница-пресет «Source rsale.net →
 * Generator → Recorder → Motion (MP4)», AI-звено через Z.AI без API-ключа
 * (zcode на десктопе, auto-цепочка в web). */

const storeUrl = new URL("../src/flow/store.ts", import.meta.url);

test("addVideoChainPage builds the parallel rsale.net → video chain", async () => {
  const source = await readFile(storeUrl, "utf-8");
  const start = source.indexOf("addVideoChainPage: (options) => {");
  const end = source.indexOf("switchPage: (id) => {", start);
  assert.ok(start > 0 && end > start, "addVideoChainPage must exist in the flow store");
  const body = source.slice(start, end);

  // Source Import с rsale.net по умолчанию и подтверждением прав владельца
  assert.match(body, /rsale\.net/);
  assert.match(body, /mode: "url", url, mine: true/);

  // Генератор: zcode на десктопе (локальный ZCode CLI — Z.AI без ключа),
  // auto в web (серверная цепочка доходит до zcode/GLM-5.3 последней)
  assert.match(body, /desktop \? "zcode" : "auto"/);

  // Полная проводка до видео:
  // prompt.out → generator.prompt, source.tokens → generator.tokens,
  // generator.ir → recorder.ir, generator.ir → motion.ir,
  // recorder.interaction → motion.interaction
  for (const wiring of [
    /edge\(Number\(prompt\.id\), "out", Number\(generator\.id\), "prompt"\)/,
    /edge\(Number\(source\.id\), "tokens", Number\(generator\.id\), "tokens"\)/,
    /edge\(Number\(generator\.id\), "ir", Number\(recorder\.id\), "ir"\)/,
    /edge\(Number\(generator\.id\), "ir", Number\(motion\.id\), "ir"\)/,
    /edge\(Number\(recorder\.id\), "interaction", Number\(motion\.id\), "interaction"\)/,
  ]) {
    assert.match(body, wiring);
  }

  // Ветка не трогает текущий граф: добавляется отдельной страницей
  assert.match(body, /withCurrentPageSaved\(state\), page/);
});

test("PagesPanel exposes the video-branch button next to + Page", async () => {
  const source = await readFile(new URL("../src/PagesPanel.svelte", import.meta.url), "utf-8");
  assert.match(source, /addVideoChainPage\(\)/);
});

test("Generator node selector keeps explicit zcode provider on desktop", async () => {
  const source = await readFile(new URL("../src/nodes/GeneratorNode.svelte", import.meta.url), "utf-8");
  assert.match(source, /"auto", "codex", "kimi", "openai", "glm", "zai", "grok", "zcode"\]\.includes\(data\.provider\)/);
  assert.match(source, /value="zcode">GLM-5\.3 · ZCode/);
});
