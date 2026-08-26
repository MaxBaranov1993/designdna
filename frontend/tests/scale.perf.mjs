// Production-shaped масштабный профилировщик рендера и композиции.
// Замеряет p50/p95 сборки HTML-строки рендера (доминирующая часть пути
// innerHTML без DOM-парса — отдельная статья бюджета браузера) и компоновки
// страниц (composePage — путь propagate/pull данных между нодами).
// Запуск: node tests/scale.perf.mjs (без новых зависимостей: бандлим TS-движок
// через уже установленный esbuild из vite).
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "package.json"));
const { buildSync } = require("esbuild");

const outdir = fs.mkdtempSync(path.join(os.tmpdir(), "scale-perf-"));
buildSync({
  entryPoints: [path.join(here, "..", "src", "engine", "renderer.ts"), path.join(here, "..", "src", "flow", "compose.ts")],
  bundle: true,
  format: "esm",
  outdir,
  entryNames: "[name]",
  logLevel: "silent",
});
const { IRRendererTest } = await import(pathToFileURL(path.join(outdir, "renderer.js")).href);
const { composePage } = await import(pathToFileURL(path.join(outdir, "compose.js")).href);

function percentile(samples, q) {
  const ordered = [...samples].sort((a, b) => a - b);
  const index = Math.min(ordered.length - 1, Math.max(0, Math.round(q * (ordered.length - 1))));
  return ordered[index];
}

function section(index) {
  return {
    type: "card",
    sourceKey: `sec:${index}`,
    style: { padding: 24, borderRadius: 16 },
    children: [
      { type: "heading", level: 2, text: `Секция ${index}`, align: "left" },
      { type: "text", text: "Описание секции для масштабного прогона рендера", size: "sm" },
      ...Array.from({ length: 4 }, (_, child) => ({
        type: "text",
        text: `Пункт ${child}: текст элемента масштабного прогона`,
      })),
      { type: "button", text: "Действие", variant: "primary" },
      { type: "image", alt: "карточка" },
    ],
  };
}

function buildIr(sectionCount) {
  return {
    version: "1.0",
    tokens: { color: { bg: { value: "#101014" }, muted: { value: "#8b8b96" } } },
    frame: { width: 1440, height: "hug" },
    tree: Array.from({ length: sectionCount }, (_, i) => section(i)),
  };
}

function profileRender(sectionCount, runs) {
  const ir = buildIr(sectionCount);
  const elementCount = ir.tree.reduce((sum, s) => sum + 1 + (s.children || []).length, 0);
  const samples = [];
  let html = "";
  for (let run = 0; run < runs; run++) {
    const t0 = performance.now();
    html = ir.tree.map((node) => IRRendererTest.renderElement(node, 3, true, null)).join("");
    samples.push(performance.now() - t0);
  }
  if (!html.includes("Секция 0")) throw new Error("рендер вернул пустую разметку");
  return { elementCount, p50: percentile(samples, 0.5), p95: percentile(samples, 0.95) };
}

function profileCompose(sectionCount, runs) {
  const blocks = Array.from({ length: sectionCount }, (_, i) => ({
    name: `b${i}`,
    ir: { tokens: { color: { bg: { value: "#101014" } } }, tree: [deepCopy(section(i))] },
  }));
  const samples = [];
  let out = null;
  for (let run = 0; run < runs; run++) {
    const t0 = performance.now();
    out = composePage(blocks, null);
    samples.push(performance.now() - t0);
  }
  if (!out || (out.tree || []).length !== sectionCount) throw new Error("компоновка вернула не всё дерево");
  return { p50: percentile(samples, 0.5), p95: percentile(samples, 0.95) };
}

function deepCopy(value) {
  return JSON.parse(JSON.stringify(value));
}

let failed = false;
for (const [sectionCount, runs] of [[115, 30], [560, 15]]) {
  const render = profileRender(sectionCount, runs);
  console.log(`PROFILE render sections=${sectionCount} elements=${render.elementCount} ` +
    `p50=${render.p50.toFixed(1)}ms p95=${render.p95.toFixed(1)}ms`);
  // мягкий потолок: ловим порядок деградации (гейт решения — 100 мс p95,
  // оцениваем по выведенным числам)
  if (render.p95 > 400) { console.error(`FAIL render p95 ${render.p95.toFixed(1)}ms @ ${render.elementCount} elements`); failed = true; }
}

const composeSections = 1200;
const compose = profileCompose(composeSections, 15);
console.log(`PROFILE compose sections=${composeSections} p50=${compose.p50.toFixed(1)}ms p95=${compose.p95.toFixed(1)}ms`);
if (compose.p95 > 400) { console.error(`FAIL compose p95 ${compose.p95.toFixed(1)}ms`); failed = true; }

if (failed) process.exit(1);
console.log("ALL SCALE PERF CHECKS PASSED");
