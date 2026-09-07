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
const { useFlowStore: store } = await import(pathToFileURL(outfile));
after(() => rmSync(dir, { recursive: true, force: true }));
const node = (id, x = 0) => ({ id, type: 'prompt', data: { text: 'draft' }, position: { x, y: 20 }, selected: false });
const setup = () => store.setState({ activePageId: 'a', nodes: [node('1'), node('2', 300)], edges: [], graphHistory: { past: [], future: [] }, statuses: {}, busy: {} });

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
