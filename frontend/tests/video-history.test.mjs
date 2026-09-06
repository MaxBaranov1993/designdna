import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const { buildSync } = createRequire(import.meta.url)('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'video-history-'));
globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
const timer = globalThis.setTimeout;
globalThis.setTimeout = (...args) => { const result = timer(...args); result.unref(); return result; };
const bundle = (name) => {
  const outfile = join(dir, name + '.mjs');
  buildSync({ entryPoints: [fileURLToPath(new URL('../src/flow/' + name + '.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile, logLevel: 'silent' });
  return import(pathToFileURL(outfile));
};
const { useFlowStore: store } = await bundle('store');
const { CTX_ITEMS, CTX_GROUPS, defaultData } = await bundle('ports');
const { buildSavePayload, payloadToRf, compactForStorage } = await bundle('serialize');
after(() => rmSync(dir, { recursive: true, force: true }));
const ir = { version: '1.1', frame: { width: 1440 }, tree: [{ id: 'hero', type: 'hero', props: { heading: 'Разместить объявление' } }] };
const timeline = (x) => ({ version: 'timeline-ir/1.0', composition: { width: 1920, height: 1080, fps: 30, duration: 8000 }, groups: [], layers: [{ id: 'hero', in: 0, out: 8000, transform: { properties: { x: { keyframes: [{ t: 0, value: x }] } } } }] });
const state = () => store.getState();
let id;
const data = () => state().nodes.find(n => Number(n.id) === id).data;
const commit = (doc, change) => state().commitTimeline(id, data().timeline, state().getNodeIrRevision(id), doc, change);
const setup = () => {
  store.setState({ nodes: [], edges: [], nextId: 1, statuses: {}, busy: {}, graphHistory: { past: [], future: [] } });
  id = Number(state().addNode('timeline', 0, 0).id);
  state().setNodeData(id, { ir, timeline: timeline(0) });
};
test('new projects expose one editor; saved Motion data remains supported', () => {
  for (const menu of [CTX_ITEMS, CTX_GROUPS.flatMap(g => g.items)]) {
    assert.equal(menu.filter(n => n.type === 'timeline').length, 1);
    assert.equal(menu.filter(n => n.type === 'motion').length, 0);
  }
  assert.equal(defaultData('timeline').provider, 'codex');
  assert.ok(defaultData('motion').sceneIrs);
});
test('manual work, old prompt branches and exact prompts survive save/load', () => {
  setup();
  const change = { kind: 'prompt', label: 'Приближение', prompt: 'Приблизь hero на 10%', provider: 'claude', effort: 'high' };
  assert.equal(commit(timeline(10), change), true);
  const first = data().revisions.at(-1);
  assert.equal(commit(timeline(20)), true); // manual change
  assert.equal(commit(timeline(30), { ...change, prompt: 'Сдвинь ещё правее' }), true);
  const beforeRestore = structuredClone(data().revisions);
  assert.equal(beforeRestore.length, 4);
  assert.equal(beforeRestore[2].kind, 'manual');
  assert.deepEqual(beforeRestore[2].timeline, timeline(20));
  assert.equal(commit(first.timeline, { kind: 'restore', label: 'Вернуться', restoredFrom: first.id }), true);
  assert.equal(data().revisions.at(-1).parentId, first.id);
  assert.deepEqual(data().revisions.slice(0, 4), beforeRestore);
  assert.equal(commit(timeline(40), { ...change, prompt: 'Новая ветка' }), true);
  const saved = JSON.parse(JSON.stringify(compactForStorage(buildSavePayload(state()))));
  const loaded = payloadToRf(saved).nodes.find(n => Number(n.id) === id).data;
  assert.deepEqual(loaded.revisions, data().revisions);
  assert.equal(loaded.activeRevisionId, data().activeRevisionId);
  assert.equal(loaded.revisions[1].prompt, change.prompt);
  assert.deepEqual(loaded.revisions[0].sourceIr, ir);
});
test('stale AI commits cannot append history or overwrite another editor', () => {
  setup();
  const old = data().timeline;
  const revision = state().getNodeIrRevision(id);
  commit(timeline(12));
  const before = structuredClone(data());
  assert.equal(state().commitTimeline(id, old, revision, timeline(30), { kind: 'prompt', label: 'stale' }), false);
  assert.deepEqual(data(), before);
  state().setNodeData(id, { ir: { ...ir, tree: [] } });
  assert.equal(state().commitTimeline(id, data().timeline, revision, timeline(30), { kind: 'prompt', label: 'stale source' }), false);
});
test('restoration refuses mismatched source and does not corrupt history', () => {
  setup(); commit(timeline(10), { kind: 'prompt', label: 'First' });
  const version = data().revisions[0];
  state().setNodeData(id, { ir: { ...ir, frame: { width: 390 } } });
  const before = structuredClone(data());
  assert.throws(() => commit(version.timeline, { kind: 'restore', label: 'Restore', restoredFrom: version.id }), /другой исходной/);
  assert.deepEqual(data(), before);
});
test('+ Video starts from an assembled page snapshot without replacing the original graph', () => {
  setup();
  const source = Number(state().addNode('page', 100, 100).id);
  state().setNodeData(source, { ir });
  const originalPage = state().activePageId;
  const originalNodes = structuredClone(state().nodes);
  state().addVideoChainPage();
  assert.deepEqual(state().nodes.map(n => n.type), ['page', 'timeline']);
  assert.equal(state().edges.length, 1);
  assert.deepEqual(state().nodes[1].data.ir, ir);
  assert.equal(state().nodes[1].data.provider, 'codex');
  assert.equal(state().nodes[1].data.timeline, null);
  state().switchPage(originalPage);
  assert.deepEqual(state().nodes, originalNodes);
});


test('multiple page inputs survive persistence and later page changes reject stale edits', () => {
  setup();
  const a = Number(state().addNode('page', 0, 0).id);
  const b = Number(state().addNode('page', 0, 0).id);
  state().setNodeData(a, { ir });
  state().setNodeData(b, { ir: { ...ir, tree: [{ id: 'done', type: 'hero', props: { heading: 'Готово' } }] } });
  state().connect({node:a,port:'ir'}, {node:id,port:'ir'});
  state().addVideoInput(id);
  state().connect({node:b,port:'ir'}, {node:id,port:'page2'});
  assert.equal(data().sourcePages.length, 2);
  const story = { pages: structuredClone(data().sourcePages), initialPageId:'ir', actions:[] };
  const doc = { ...timeline(0), story };
  state().setNodeData(id, {timeline:doc});
  const revision = state().getNodeIrRevision(id);
  commit({...doc, composition:{...doc.composition, duration:9000}}, {kind:'prompt',label:'First'});
  const version = data().revisions.at(-1);
  commit({...doc, composition:{...doc.composition, duration:10000}});
  const manualBeforeSourceChange = structuredClone(data().timeline);
  const saved = JSON.parse(JSON.stringify(compactForStorage(buildSavePayload(state()))));
  const loaded = payloadToRf(saved).nodes.find(n => Number(n.id) === id).data;
  assert.deepEqual(loaded.inputs, ['ir','page2']);
  assert.deepEqual(loaded.sourcePages, data().sourcePages);
  state().setNodeData(b, {ir:{...ir, tree:[{id:'different',type:'hero'}]}});
  state().propagate(b);
  assert.equal(data().timeline, null);
  assert.deepEqual(data().revisions.at(-1).timeline, manualBeforeSourceChange);
  assert.ok(state().getNodeIrRevision(id) > revision);
  assert.equal(state().commitTimeline(id, doc, revision, doc), false);
  assert.throws(() => commit(version.timeline, {kind:'restore',label:'Restore',restoredFrom:version.id}), /другой исходной/);
  state().removeVideoInput(id,'page2');
  assert.deepEqual(data().inputs,['ir']);
  assert.equal(state().edges.some(e => e.target === String(id) && e.targetHandle === 'page2'),false);
});
