// Engine regression tests — Phase 2 acceptance (K3):
//  1) editable:false raster fallback слои рендерятся с data-ir-locked и
//     остаются selectable (data-ir-path сохраняется);
//  2) responsive reflow (.ir-mobile/.ir-tablet .sec-free) не сбрасывает
//     захваченный frame.transform — Source Import linked viewports хранят
//     измеренный transform каждого viewport.
// Acceptance repair (Codex review): copy/cut/paste отказывает locked-слоям
// (отложенный дубликат), parentRef sourceKey-структурен (parentKeyByKey через
// locateByKey): родитель сгруппированного child — группа, после ungroup —
// снова валидный.
// Запуск: node tests/engine.regression.test.mjs (без новых зависимостей:
// бандлим TS-движок через уже установленный esbuild из vite).
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "package.json"));
const { buildSync } = require("esbuild");

const outdir = fs.mkdtempSync(path.join(os.tmpdir(), "engine-regression-"));
buildSync({
  entryPoints: [
    path.join(here, "..", "src", "engine", "renderer.ts"),
    path.join(here, "..", "src", "engine", "locked.ts"),
    path.join(here, "..", "src", "engine", "sourcepath.ts"),
    path.join(here, "..", "src", "flow", "compose.ts"),
  ],
  bundle: true,
  format: "esm",
  outdir,
  entryNames: "[name]",
  logLevel: "silent",
});
const { IRRenderer, IRRendererTest } = await import(pathToFileURL(path.join(outdir, "renderer.js")).href);
const { isLockedNode, lockedReason } = await import(pathToFileURL(path.join(outdir, "locked.js")).href);
const { isSourceKeyPath, sourceParentPath, findByKey, locateByKey, parentKeyByKey, rekeyCloneKeys } =
  await import(pathToFileURL(path.join(outdir, "sourcepath.js")).href);
const { composePage } = await import(pathToFileURL(path.join(outdir, "compose.js")).href);

let passed = 0;
function check(name, fn) {
  fn();
  passed++;
  console.log("OK", name);
}

/* ---------- Page: common artboard follows every editable block ---------- */

check("Page artboard is auto-height and viewport metadata sums all blocks", () => {
  const block = (label, desktopHeight, mobileHeight) => ({
    version: "1.1",
    frame: { width: 1440, height: desktopHeight },
    tree: [{
      id: "imported-block",
      type: "source-block",
      sourceKey: "root",
      frame: { width: 1440, height: desktopHeight, layout: "free" },
      responsive: { mobile: { frame: { width: 390, height: mobileHeight } } },
      children: [{ type: "text", text: label, sourceKey: "root/text:1", frame: { x: 10, y: 10, width: 120, height: 24 } }],
    }],
  });
  const page = composePage([
    { name: "header", ir: block("Header", 120, 180) },
    { name: "main", ir: block("Main", 480, 720) },
  ], null, "desktop");

  assert.equal(page.frame.height, "hug");
  assert.equal(page.responsive.viewports.desktop.height, 600);
  assert.equal(page.responsive.viewports.mobile.height, 900);
  assert.equal(new Set(page.tree.flatMap((section) => [section.sourceKey, ...section.children.map((child) => child.sourceKey)])).size, 4);
});

check("responsive materialization keeps Page auto-height instead of fixed viewport crop", () => {
  const page = composePage([{
    name: "source",
    ir: {
      tree: [{ id: "source", type: "source-block", sourceKey: "root", frame: { height: 1200 }, children: [] }],
    },
  }], null, "desktop");
  const mobile = IRRenderer.materializeResponsiveIR(page, "mobile");
  assert.equal(mobile.frame.width, 390);
  assert.equal(mobile.frame.height, "hug");
});

/* ---------- defect 2: measured transforms survive mobile/tablet reflow ---------- */

check("mobile reflow rule does not strip captured transforms", () => {
  const css = IRRendererTest.baseCss(7);
  assert.ok(
    css.includes(".ir-7.ir-mobile .sec-free > [data-ir-path]:not([data-ir-transform])"),
    "mobile sec-free rule must exclude [data-ir-transform] layers",
  );
  // голый селектор с transform:none больше не должен существовать
  assert.ok(
    !/\.sec-free\s*>\s*\[data-ir-path\]\s*\{[^}]*transform:\s*none/.test(css),
    "bare .sec-free > [data-ir-path] transform:none override must be gone",
  );
});

check("tablet reflow rule does not strip captured transforms", () => {
  const css = IRRendererTest.baseCss(9);
  assert.ok(
    css.includes(".ir-9.ir-tablet .sec-free > [data-ir-path]:not([data-ir-transform])"),
    "tablet sec-free rule must exclude [data-ir-transform] layers",
  );
});

check("captured frame.transform renders inline and marks the layer in every viewport", () => {
  const transform = "matrix(0.9945, 0.1045, -0.1045, 0.9945, 20, 0)";
  for (const viewport of ["desktop", "tablet", "mobile"]) {
    // renderer CSS viewport-независим (класс переключает правила); контракт:
    // wrapper несёт data-ir-transform + inline transform во всех viewports.
    const html = IRRendererTest.withFrame(
      "<p>Tilted</p>",
      { width: 200, height: 80, absolute: true, x: 16, y: 16, transform },
      true, false, `stage2-${viewport}:root/div:1`, "", null, "",
    );
    assert.ok(html.includes("data-ir-transform"), `${viewport}: wrapper must carry data-ir-transform`);
    assert.ok(html.includes(`transform:${transform}`), `${viewport}: inline transform must be preserved`);
    assert.ok(html.includes('data-ir-path="stage2-' + viewport + ':root/div:1"'), `${viewport}: layer stays selectable`);
  }
});

check("plain rotation without captured transform still reflows on mobile", () => {
  // rotation (не полный transform источника) НЕ помечается data-ir-transform —
  // мобильный reflow по-прежнему сбрасывает его, как и раньше.
  const html = IRRendererTest.withFrame(
    "<p>Rot</p>", { width: 40, height: 40, rotation: 15 }, true, false, "children.0", "", null, "",
  );
  assert.ok(!html.includes("data-ir-transform"), "rotation-only frame must not be marked");
  assert.ok(html.includes("transform:rotate(15deg)"), "rotation still renders inline");
});

/* ---------- defect 1: editable:false layers are marked but stay selectable ---------- */

check("locked raster layer renders data-ir-locked and keeps data-ir-path", () => {
  const node = {
    type: "image",
    src: "data:image/png;base64,AAAA",
    alt: "canvas",
    editable: false,
    lockedReason: "canvas: raster surface",
    sourceKey: "raster:root/canvas:1",
    __path: "raster:root/canvas:1",
    style: { objectFit: "fill" },
    frame: { absolute: true, x: 0, y: 0, width: 160, height: 80 },
  };
  const html = IRRendererTest.renderElement(node, 3, true, null);
  assert.ok(html.includes('data-ir-locked="canvas: raster surface"'), "locked reason must be exposed");
  assert.ok(html.includes('data-ir-path="raster:root/canvas:1"'), "layer must stay selectable");
  assert.ok(html.includes("<img"), "raster image must still render");
});

check("unlocked layers are not marked", () => {
  const node = {
    type: "image", src: "data:image/png;base64,AAAA", alt: "img",
    sourceKey: "b:root/img:1", __path: "b:root/img:1",
    frame: { absolute: true, x: 0, y: 0, width: 10, height: 10 },
  };
  const html = IRRendererTest.renderElement(node, 3, true, null);
  assert.ok(!html.includes("data-ir-locked"), "editable layer must not be locked");
});

check("isLockedNode/lockedReason predicate contract", () => {
  assert.equal(isLockedNode({ editable: false }), true);
  assert.equal(isLockedNode({ editable: true }), false);
  assert.equal(isLockedNode({}), false);
  assert.equal(isLockedNode(null), false);
  assert.equal(lockedReason({ editable: false, lockedReason: "iframe" }), "iframe");
  assert.equal(lockedReason({ editable: false }), "intrinsically non-editable surface");
  assert.equal(lockedReason({ editable: true }), "");
});

/* ---------- defect 1: mutation guards stay wired (geoedit/inspector/server) ---------- */

check("geoedit refuses content/geometry mutations on locked layers", () => {
  const src = fs.readFileSync(path.join(here, "..", "src", "engine", "geoedit.ts"), "utf8");
  // центральная точка записи frame (drag/resize/padding/nudge/inspector)
  assert.ok(/function setFrameData\(ref, frame\) \{\s*\/\/ editable:false[\s\S]*?if \(refuseLocked\(ref\)\) return;/.test(src),
    "setFrameData must refuse locked refs");
  assert.ok(/function lockedNodeFor\(ref\)/.test(src), "lockedNodeFor resolver must exist");
  for (const guard of ["setNodeStyle", "onDblClick", "deleteSelections", "duplicateSelections", "zOrder", "moveSibling"]) {
    const idx = src.indexOf(`function ${guard}(`);
    assert.ok(idx >= 0, `${guard} must exist`);
    const body = src.slice(idx, idx + 1200);
    // duplicateSelections фильтрует цели (включая lock-guard) в collectDuplicateTargets
    const accept = guard === "duplicateSelections" ? /refuseLocked|lockedNodeFor|isLockedNode|collectDuplicateTargets/ : /refuseLocked|lockedNodeFor|isLockedNode/;
    assert.ok(accept.test(body), `${guard} must consult the lock guard`);
  }
  const collectIdx = src.indexOf("function collectDuplicateTargets(");
  assert.ok(collectIdx >= 0 && /lockedNodeFor/.test(src.slice(collectIdx, collectIdx + 1200)),
    "collectDuplicateTargets must apply the lock guard (duplicateSelections delegates to it)");
});

check("geoedit refuses locked duplication on the copy/cut/paste path", () => {
  const src = fs.readFileSync(path.join(here, "..", "src", "engine", "geoedit.ts"), "utf8");
  // Ctrl+C/Ctrl+X: копия locked-слоя — отложенный дубликат, отказ с подсказкой
  const copyIdx = src.indexOf("function copySelection(");
  assert.ok(copyIdx >= 0, "copySelection must exist");
  const copyBody = src.slice(copyIdx, copyIdx + 900);
  assert.ok(/lockedNodeFor/.test(copyBody) && /refuseLocked/.test(copyBody),
    "copySelection must refuse locked selections with a hint (cut reuses it)");
  // вставка: locked-клон не создаётся, даже если буфер набит обходом copySelection
  const insIdx = src.indexOf("function insertItems(");
  assert.ok(insIdx >= 0, "insertItems must exist");
  assert.ok(/isLockedNode\(node\)\) return;/.test(src.slice(insIdx, insIdx + 1600)),
    "insertItems must skip locked clones on every structural path");
});

check("geoedit parentRef is sourceKey-structural, not string parsing", () => {
  const src = fs.readFileSync(path.join(here, "..", "src", "engine", "geoedit.ts"), "utf8");
  const idx = src.indexOf("function parentRef(");
  assert.ok(idx >= 0, "parentRef must exist");
  const body = src.slice(idx, idx + 900);
  assert.ok(/parentKeyByKey/.test(body), "parentRef must resolve the actual parentNode via locateByKey");
  assert.ok(!/sourceParentPath\(/.test(body),
    "parentRef must not guess the parent from the key format (stale after groupSelection)");
});

check("inspector and AI assist refuse locked-layer edits", () => {
  const insp = fs.readFileSync(path.join(here, "..", "src", "editor", "inspector", "wireInspector.ts"), "utf8");
  assert.ok(/isLockedNode/.test(insp), "wireInspector must guard data-el-prop/data-textprop edits");
  const assist = fs.readFileSync(path.join(here, "..", "..", "app", "editor_assist.py"), "utf8");
  assert.ok(/_locked_node_reason/.test(assist) && /editable:false/.test(assist),
    "server AI validator must reject ops on editable:false nodes");
});

/* ---------- defect 3: path-agnostic structural mutation for sourceKey refs ---------- */

const SOURCE_SEC = () => ({
  id: "imported-block", type: "source-block", variant: "dom-capture", sourceKey: "root",
  children: [
    { type: "card", sourceKey: "root/div:1", children: [
      { type: "text", sourceKey: "root/div:1::text0", text: "Market" },
      { type: "rect", sourceKey: "root/div:1::bg0" },
    ] },
    { type: "button", sourceKey: "root/button:1", children: [
      { type: "text", sourceKey: "root/button:1::text0", text: "Find" },
    ] },
    { type: "image", sourceKey: "root/canvas:1", editable: false },
  ],
});

check("locateByKey returns the actual parent children array and exact index", () => {
  const sec = SOURCE_SEC();
  const top = locateByKey(sec, "root/button:1");
  assert.ok(top && top.siblings === sec.children && top.index === 1 && top.parentNode === sec,
    "top-level sourceKey: siblings must be the section children array, index exact");
  const nested = locateByKey(sec, "root/div:1::bg0");
  assert.ok(nested && nested.siblings === sec.children[0].children && nested.index === 1
    && nested.parentNode === sec.children[0],
    "synthetic layer: parent must be its element's children array, index exact");
  assert.equal(locateByKey(sec, "root/div:99"), null, "unknown key must not resolve");
  assert.equal(locateByKey(sec, "root/div:1::bg7"), null,
    "synthetic key outside the tree must be structurally refused");
});

check("sourceParentPath string navigation stays consistent with locateByKey", () => {
  const sec = SOURCE_SEC();
  assert.equal(sourceParentPath("root/div:1::text0"), "root/div:1");
  assert.equal(sourceParentPath("root/button:1"), null);
  assert.equal(sourceParentPath("children.0"), undefined);
  assert.equal(sourceParentPath("props.cta"), undefined);
  const located = locateByKey(sec, "root/div:1::text0");
  assert.equal(findByKey(sec, sourceParentPath("root/div:1::text0")), located.parentNode);
});

check("rekeyCloneKeys gives the duplicate a unique non-colliding sourceKey subtree", () => {
  const sec = SOURCE_SEC();
  let n = 0;
  const clone = rekeyCloneKeys(JSON.parse(JSON.stringify(sec.children[1])), () => "u" + (++n));
  assert.ok(clone.sourceKey !== "root/button:1", "clone root key must differ from the original");
  assert.ok(clone.sourceKey.startsWith("root/button:1~"), "clone keeps the parent hierarchy prefix");
  const kid = clone.children[0];
  assert.equal(kid.sourceKey, clone.sourceKey + "::text0",
    "descendant keys follow the new root (synthetic suffix preserved)");
  assert.equal(sourceParentPath(kid.sourceKey), clone.sourceKey,
    "string navigation from a duplicated descendant resolves to the clone root");
  assert.ok(!("__path" in clone) && !("__path" in kid), "stale renderer __path must be dropped");
  // вставка рядом с оригиналом: ключи клона не пересекаются с захваченными
  sec.children.splice(2, 0, clone);
  assert.equal(locateByKey(sec, "root/button:1").node, sec.children[1],
    "original still resolves to itself after the duplicate is inserted");
  assert.equal(locateByKey(sec, clone.sourceKey).node, clone, "clone resolves independently");
  assert.equal(locateByKey(sec, "root/button:1::text0").node, sec.children[1].children[0],
    "original synthetic child is not shadowed by the clone");
});

check("isSourceKeyPath classifies addressing modes", () => {
  assert.equal(isSourceKeyPath("root/button:1"), true);
  assert.equal(isSourceKeyPath("root/button:1~geo-1"), true);
  assert.equal(isSourceKeyPath("children.0"), false);
  assert.equal(isSourceKeyPath("props.cta"), false);
  assert.equal(isSourceKeyPath(null), false);
});

/* ---------- defect 2 (repair): group/ungroup parent resolution is structural ---------- */

check("group child parent resolves to the group; ungroup restores a valid parent", () => {
  const sec = SOURCE_SEC();
  // структурный эквивалент groupSelection: div:1 + button:1 уходят в free-группу,
  // sourceKey детей НЕ меняются (именно здесь строковый разбор ключа ломался)
  const group = {
    type: "card", sourceKey: "root/group~u1",
    frame: { layout: "free", x: 0, y: 0, width: 100, height: 40 },
    children: [sec.children[0], sec.children[1]],
  };
  sec.children.splice(0, 2, group);
  assert.equal(parentKeyByKey(sec, "root/button:1"), "root/group~u1",
    "grouped child must resolve to its actual group parent, not the old root");
  assert.equal(parentKeyByKey(sec, "root/div:1::text0"), "root/div:1",
    "synthetic layer inside the group still resolves to its element");
  assert.equal(parentKeyByKey(sec, "root/group~u1"), null,
    "top-level group parent is the section (ref.path null)");
  assert.equal(sourceParentPath("root/button:1"), null,
    "string parsing proves stale: it still points at the pre-group root");
  // уникальные selectable identity сохраняются: каждый ключ — ровно один узел
  for (const k of ["root/div:1", "root/button:1", "root/canvas:1", "root/group~u1"]) {
    assert.ok(locateByKey(sec, k), `key ${k} must stay selectable after grouping`);
  }
  // locked exclusion: raster остался вне группы и по-прежнему locked
  const raster = locateByKey(sec, "root/canvas:1");
  assert.ok(raster && raster.parentNode === sec && raster.node.editable === false,
    "locked raster stays a top-level locked layer, excluded from the group");
  // ungroup: дети возвращаются в секцию, родитель снова валиден
  const idx = sec.children.indexOf(group);
  sec.children.splice(idx, 1, ...group.children);
  assert.equal(parentKeyByKey(sec, "root/button:1"), null,
    "ungrouped child parent is the section again");
  assert.equal(parentKeyByKey(sec, "root/group~u1"), undefined,
    "dissolved group key must not resolve");
  assert.ok(locateByKey(sec, "root/div:1") && locateByKey(sec, "root/button:1"),
    "ungrouped children keep their selectable identities");
  assert.equal(parentKeyByKey(sec, "root/div:99"), undefined,
    "unknown key is structurally refused");
});

console.log(`ALL ENGINE REGRESSION CHECKS PASSED (${passed})`);
