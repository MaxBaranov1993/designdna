import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/* Контракт тонкой полосы прогресса под нодой: Source Import и генерация
 * показывают проценты + elapsed-время, вёрстка видео-цепочки — один ряд
 * без перекрытий, страницы открываются с полным видом (auto-fit). */

const read = (rel) => readFile(new URL(rel, import.meta.url), "utf-8");

test("store: long runs drive setProgress and clear it in finally", async () => {
  const source = await read("../src/flow/store.ts");

  const si = source.slice(
    source.indexOf("runSourceImport: async (id) => {"),
    source.indexOf("runStyleDna: async (id) => {"),
  );
  assert.match(si, /setProgress\(id, \{ expectedMs: 90_000, label:/);
  assert.match(si, /setProgress\(id, null\)/);
  assert.match(si, /Source Import\$\{cacheNote\}\$\{authNote\} · \$\{secs\}с/);
  assert.match(si, /res\.diagnostics\?\.timingsMs/);
  assert.match(si, /lastRun:/);
  assert.match(si, /asyncJob: true/);
  assert.match(si, /apiGet<BlockParseJobResp>/);
  assert.match(si, /percent: job\.progress/);

  const gen = source.slice(
    source.indexOf("runGenerator: async (id) => {"),
    source.indexOf("runMix: async (id) => {"),
  );
  assert.match(gen, /setProgress\(id, \{ expectedMs: 90_000, label: `Генерация · \$\{providerLabel\}` \}\)/);
  assert.match(gen, /setProgress\(id, null\)/);
  assert.match(gen, /Готово: вариантов \$\{variants\.length\}.*· \$\{\(\(Date\.now\(\) - startedAt\) \/ 1000\)\.toFixed\(0\)\}с/);
});

test("Source Import shows measured backend stages after a run", async () => {
  const source = await read("../src/nodes/SourceImportNode.svelte");
  assert.match(source, /Measured run/);
  assert.match(source, /data\.lastRun\.timingsMs/);
  assert.match(source, /captureCompile: "Layers"/);
  assert.match(source, /fidelity: "Fidelity"/);
});

test("NodeShell renders the thin progress bar with percent and clock", async () => {
  const source = await read("../src/nodes/NodeShell.svelte");
  assert.match(source, /flowProgresses/);
  assert.match(source, /role="progressbar"/);
  assert.match(source, /n-progress-track/);
  assert.match(source, /n-progress-fill.*style="width: \{percent\}%"/);
  assert.match(source, /progress\.percent \?\? Math\.min/);
  assert.match(source, /\{Math\.round\(percent\)\}% · \{clock\}/);
  // асимптотическая кривая: до конца операции 100% не показывается
  assert.match(source, /Math\.min\(97, 100 \* \(1 - Math\.exp\(\(-1\.7 \* elapsedMs\) \/ progress\.expectedMs\)\)\)/);
});

test("state exposes the progresses slice", async () => {
  const source = await read("../src/flow/state.ts");
  assert.match(source, /export const flowProgresses = selectReadable\(useFlowStore, \(s\) => s\.progresses/);
});

test("video chain page lays nodes in a single row and auto-fits the view", async () => {
  const source = await read("../src/flow/store.ts");
  const start = source.indexOf("addVideoChainPage: (options) => {");
  const end = source.indexOf("switchPage: (id) => {", start);
  const body = source.slice(start, end);

  const xs = [];
  const ys = [];
  for (const m of body.matchAll(/mkNode\("\w+", (\d+), (\d+)/g)) {
    xs.push(Number(m[1]));
    ys.push(Number(m[1 + 1]));
  }
  assert.equal(xs.length, 6, "six nodes in the preset, including Motion Design");
  assert.ok(ys.every((y) => y === ys[0]), "single row — no vertical overlap");
  for (let i = 1; i < xs.length; i++) {
    assert.ok(xs[i] > xs[i - 1], "left-to-right order");
  }
  assert.match(body, /setTimeout\(fitFlowView, 80\)/);

  const switchBody = source.slice(source.indexOf("switchPage: (id) => {"), source.indexOf("renamePage: (id, name) => {"));
  assert.match(switchBody, /setTimeout\(fitFlowView, 80\)/, "switching pages shows all nodes");
});
