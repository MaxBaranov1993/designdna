import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import test from "node:test";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const picker = read("../src/editor/inspector/ColorPicker.svelte");
const wiring = read("../src/editor/inspector/wireInspector.ts");
const clone = (value) => JSON.parse(JSON.stringify(value));
function functions(source, names) {
  const ast = ts.createSourceFile("test.ts", source, ts.ScriptTarget.Latest, true);
  const found = new Map();
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) {
      found.set(node.name.text, node.getText(ast).replace(/^export /, ""));
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.equal(found.size, names.length);
  return ts.transpileModule([...found.values()].join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
}
const pickerScript = [...picker.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((match) => match[1]).join("\n");

// Minimized RSALE hero-slide selection from run 1788697439992693900:
// editable card/div, auto-layout children, measured styles, responsive branches.
const baseline = {
  responsive: { viewports: { desktop: { width: 1433, height: 272 }, mobile: { width: 390, height: 200 } } },
  tree: [{ type: "card", sourceKey: "hero", children: [
    { type: "card", role: "div", sourceKey: "hero/div:1",
      frame: { absolute: true, layout: "auto", direction: "column", width: 648, height: 260, padding: [32, 32, 32, 32] },
      style: { borderRadius: 0, borderWidth: 0, color: "#000000", fontSize: 14, opacity: 1 },
      responsive: { mobile: { visible: true, frame: { width: 214.7, height: 182.36 } } },
      children: [{ type: "text", sourceKey: "hero/div:1/text", text: "Marketplace robe i usluga u Srbiji" }] },
    { type: "card", sourceKey: "hero/div:2", children: [{ type: "image", sourceKey: "hero/image", src: "fixture.png" }] },
  ] }],
};

function harness() {
  const state = { ir: clone(baseline), activeIR: clone(baseline), viewport: "desktop" };
  let mutations = 0;
  const saveCtx = { state, manualSourceKey: 0 };
  runInNewContext(functions(read("../src/editor/controller.ts"),
    ["deepClone", "sourceNodeMap", "syncSharedStructure", "syncActiveIR", "copyWithoutRenderMetadata"]), saveCtx);
  const geoCtx = { selections: [{ ref: "selected" }], styleSessionUntil: 0, onCommit() {},
    refuseLocked: () => state.activeIR.tree[0].children[0].editable === false,
    irNodeAt: () => state.activeIR.tree[0].children[0],
    onMutated() { mutations++; saveCtx.syncActiveIR(); } };
  runInNewContext(functions(read("../src/engine/geoedit.ts"), ["setNodeStyle"]), geoCtx);
  let currentGeo = geoCtx;
  const session = { sel: [{ ref: "selected" }], get geo() { return currentGeo; } };
  const ctl = { getSession: () => session, setInspScrubbing() {} };
  const color = Object.assign(new EventTarget(), { value: "#ffffff", hasAttribute: () => true });
  const text = Object.assign(new EventTarget(), { value: "", hasAttribute: () => true });
  const clear = Object.assign(new EventTarget(), { hasAttribute: () => true });
  const fields = { "[data-style-color]": [color], "[data-style-text]": [text], "[data-clear-style]": [clear] };
  const root = {
    querySelector: (selector) => selector.includes("data-style-color") ? color : selector.includes("data-style-text") ? text : null,
    querySelectorAll: (selector) => fields[selector] || [],
  };
  const wireCtx = { ctl };
  runInNewContext(functions(wiring, ["sess", "geo", "applyInspectorColor", "wireInspector", "wireSingle", "wireActs", "wireTypeGroups", "wireResponsive"]), wireCtx);
  const pickerCtx = { ctl, fieldEl: root, styleKey: "background", Event,
    applyInspectorColor: wireCtx.applyInspectorColor };
  runInNewContext(functions(pickerScript, ["hexToRgb", "rgbToHex", "normalizeHex", "writeHex", "updateInlineHex", "endInlineEdit"]), pickerCtx);
  return { state, color, text, root, pickerCtx, wireCtx,
    save: () => clone(saveCtx.copyWithoutRenderMetadata(state.ir)),
    mutations: () => mutations, setGeo: (geo) => { currentGeo = geo; } };
}

test("legacy synthetic input with no deferred listener displays the new color but saves baseline exactly", () => {
  const h = harness();
  h.text.value = "#123abc";
  h.color.value = h.text.value;
  h.color.dispatchEvent(new Event("input", { bubbles: true }));
  assert.equal(h.text.value, "#123abc");
  assert.deepEqual(h.save(), baseline);
  assert.equal(h.mutations(), 0);
});

test("inline RSALE card color commits before deferred wiring and saves only selected background", () => {
  const h = harness();
  h.text.value = "#123abc";
  h.pickerCtx.updateInlineHex(h.text);
  h.pickerCtx.endInlineEdit(h.text); // fill + Tab from the live probe
  const expected = clone(baseline);
  expected.tree[0].children[0].style.background = "#123abc";
  assert.deepEqual(h.save(), expected);
  assert.equal(h.color.value, "#123abc");
});

test("deferred wiring does not add duplicate listeners to component-owned color fields", () => {
  const h = harness();
  h.wireCtx.wireInspector(h.root);
  h.pickerCtx.writeHex("#AbC");
  assert.equal(h.mutations(), 1);
  assert.equal(h.color.value, "#aabbcc");
  assert.equal(h.text.value, "#aabbcc");
  h.color.dispatchEvent(new Event("input"));
  h.text.dispatchEvent(new Event("change"));
  assert.equal(h.mutations(), 1, "legacy listeners must skip data-direct-change controls");
});

test("invalid drafts do not mutate; transparent clears only background; locked edits remain refused", () => {
  const h = harness();
  h.pickerCtx.writeHex("#123abc");
  h.pickerCtx.writeHex("#12");
  assert.equal(h.mutations(), 1);
  h.pickerCtx.writeHex("transparent");
  assert.deepEqual(h.save(), baseline);
  assert.equal(h.text.value, "");
  h.state.activeIR.tree[0].children[0].editable = false;
  h.pickerCtx.writeHex("#123abc");
  assert.equal(h.state.activeIR.tree[0].children[0].style.background, undefined);
});

test("color events resolve the current GeoEdit after reattachment", () => {
  const h = harness();
  const patches = [];
  h.setGeo({ setNodeStyle: (patch) => patches.push(clone(patch)) });
  h.pickerCtx.writeHex("#123abc");
  assert.deepEqual(patches, [{ background: "#123abc" }]);
  assert.equal(h.mutations(), 0);
});

test("Svelte owns native, inline-change and clear handlers without an animation-frame listener dependency", () => {
  const { parse } = require("svelte/compiler");
  assert.doesNotThrow(() => parse(picker));
  assert.match(picker, /data-style-color=\{styleKey\} data-direct-change[\s\S]*?oninput=/);
  assert.match(picker, /data-style-text=\{styleKey\}\s+data-direct-change[\s\S]*?onchange=/);
  assert.match(picker, /data-clear-style=\{styleKey\}\s+data-direct-change[\s\S]*?onclick=/);
  assert.doesNotMatch(picker, /native\.dispatchEvent/);
});
