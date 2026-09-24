import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const { buildSync } = createRequire(import.meta.url)('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'canvas-drag-'));
globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
const timer = globalThis.setTimeout;
globalThis.setTimeout = (...args) => { const result = timer(...args); result.unref(); return result; };
const outfile = join(dir, 'store.mjs');
buildSync({ entryPoints: [fileURLToPath(new URL('../src/flow/store.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile, logLevel: 'silent' });
const { useFlowStore: store, bindPageState } = await import(pathToFileURL(outfile));
after(() => rmSync(dir, { recursive: true, force: true }));
const node = (id, x = 0) => ({ id, type: 'prompt', data: { text: 'draft' }, position: { x, y: 20 }, selected: false });
const setup = () => store.setState({ activePageId: 'a', pages: [{id:'a',name:'A',nodes:[],edges:[],view:{x:0,y:0,zoom:1},nextId:3}], nodes: [node('1'), node('2', 300)], nextId: 3, pageRuntimes: {}, edges: [], graphHistory: { past: [], future: [] }, statuses: {}, busy: {} });

test('drop preserves async results, new nodes and new wires; never resurrects deleted nodes', () => {
  setup();
  const staleDrag = [{ id: '1', position: { x: 80.7, y: 40.2 } }, { id: '2', position: { x: 400, y: 40 } }];
  const freshData = { text: 'finished while dragging' };
  const newNode = node('3', 800);
  const edges = [{ id: 'new-wire', source: '1', target: '3' }];
  store.setState({ nodes: [{ ...node('1'), data: freshData }, newNode], edges });
  store.getState().commitNodeDrag('a', staleDrag, ['1', '2']);
  const st = store.getState();
  assert.deepEqual(st.nodes.map(n => n.id), ['1', '3']);
  assert.equal(st.nodes[0].data, freshData);
  assert.equal(st.nodes[1], newNode);
  assert.equal(st.edges, edges);
  assert.deepEqual(st.nodes[0].position, { x: 81, y: 40 });
  assert.equal(st.nodes[0].selected, true);
});

test('multi-node drag is one undo step and undo/redo keeps selection and data', () => {
  setup();
  const st = store.getState();
  st.commitNodeDrag('a', [{ id: '1', position: { x: 10, y: 30 } }, { id: '2', position: { x: 310, y: 30 } }], ['1', '2']);
  assert.equal(store.getState().graphHistory.past.length, 1);
  assert.ok(store.getState().nodes.every(n => n.selected));
  st.undoGraph();
  assert.deepEqual(store.getState().nodes.map(n => n.position.x), [0, 300]);
  st.redoGraph();
  assert.deepEqual(store.getState().nodes.map(n => n.position.x), [10, 310]);
});

test('late drop after page switch cannot move nodes with matching IDs', () => {
  setup();
  store.setState({ activePageId: 'b' });
  const before = store.getState().nodes;
  store.getState().commitNodeDrag('a', [{ id: '1', position: { x: 999, y: 999 } }], ['1']);
  assert.equal(store.getState().nodes, before);
  assert.equal(store.getState().graphHistory.past.length, 0);
});

test('no-op drag creates no history; invalid geometry cannot corrupt a node', () => {
  setup();
  store.getState().commitNodeDrag('a', [{ id: '1', position: { x: NaN, y: Infinity } }], ['1']);
  assert.deepEqual(store.getState().nodes[0].position, { x: 0, y: 20 });
  assert.equal(store.getState().graphHistory.past.length, 0);
  const before = store.getState().nodes;
  store.getState().commitNodeDrag('a', [{ id: '1', position: { x: 0, y: 20 } }], ['1']);
  assert.equal(store.getState().nodes, before);
});

test('undo and redo geometry preserve results and edits arriving after each snapshot', () => {
  setup();
  store.getState().moveNode(1, 100, 50);
  store.getState().setNodeData(1, { text: 'async result' });
  store.getState().undoGraph();
  assert.equal(store.getState().nodes[0].position.x, 0);
  assert.equal(store.getState().nodes[0].data.text, 'async result');
  store.getState().setNodeData(1, { text: 'edited after undo' });
  store.getState().redoGraph();
  assert.equal(store.getState().nodes[0].position.x, 100);
  assert.equal(store.getState().nodes[0].data.text, 'edited after undo');
});

test('delete undo restores removed data and preserves newer data of surviving nodes', () => {
  setup();
  store.getState().setNodeData(1, { text: 'saved before deletion' });
  store.getState().deleteNode(1);
  store.getState().setNodeData(2, { text: 'peer completed' });
  store.getState().undoGraph();
  assert.deepEqual(store.getState().nodes.map(n => n.data.text), ['saved before deletion', 'peer completed']);
  store.getState().setNodeData(1, { text: 'restored node edited' });
  store.getState().redoGraph();
  assert.deepEqual(store.getState().nodes.map(n => n.id), ['2']);
  store.getState().undoGraph();
  assert.equal(store.getState().nodes[0].data.text, 'restored node edited');
});

test('hidden sheet undo keeps its async data and never touches matching IDs on the visible sheet', () => {
  setup();
  const a = bindPageState('a');
  a().moveNode(1, 100, 50);
  store.getState().createPage('B');
  const id = store.getState().addNode('prompt', 700, 0).id;
  store.getState().setNodeData(id, { text: 'visible B' });
  const visible = store.getState().nodes;
  a().setNodeData(1, { text: 'hidden A result' });
  a().undoGraph();
  assert.equal(store.getState().nodes, visible);
  assert.equal(a().nodes[0].data.text, 'hidden A result');
  assert.equal(a().nodes[0].position.x, 0);
});

test('dynamic video port history changes inputs without reverting the current node prompt', () => {
  setup();
  const id = store.getState().addNode('timeline',0,0).id;
  store.getState().addVideoInput(id);
  store.getState().setNodeData(id,{prompt:'new montage request'});
  store.getState().undoGraph();
  let video=store.getState().nodes.find(n=>Number(n.id)===id);
  assert.deepEqual(video.data.inputs || ['ir'],['ir']);
  assert.equal(video.data.prompt,'new montage request');
  store.getState().redoGraph();
  video=store.getState().nodes.find(n=>Number(n.id)===id);
  assert.deepEqual(video.data.inputs,['ir','page2']);
  assert.equal(video.data.prompt,'new montage request');
});
