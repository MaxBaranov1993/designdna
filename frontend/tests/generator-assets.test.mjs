import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'generator-assets-'));
const entry = join(dir, 'test.mjs');
buildSync({ stdin: { contents: `export * from './src/flow/generator-assets'; export * from './src/flow/generator-visual'; export * from './src/flow/generator-inputs'; export * from './src/flow/serialize'; export * from './src/flow/result-assets'; export {useFlowStore} from './src/flow/store';`,
  resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts' }, bundle: true, format: 'esm', platform: 'node', outfile: entry, logLevel: 'silent' });
globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
const timer = globalThis.setTimeout;
globalThis.setTimeout = (...args) => { const result = timer(...args); result.unref(); return result; };
const { executeAssetPlan, assetRunPatch, settleInterruptedAssets, effectiveAssetProvider, payloadToRf, parseLegacyPayload, buildSavePayload, useFlowStore: store,
  generatorVisualReference, generatorInputKey, createVisualConcept, conceptRunPatch, fillResultAssets, undoResultAssets, resultAssetsAreCurrent } = await import(pathToFileURL(entry));
after(() => { unlinkSync(entry); rmdirSync(dir); });
const image = 'data:image/png;base64,AAAA';
const result = index => ({ src: 'ddna://blobs/' + String(index + 1).repeat(64) + '.png', sha256: String(index + 1).repeat(64), width: 96, height: 64, format: 'png', transparent: false });
const variants = () => [{ tree: [{ type: 'composition', children: [
  { type: 'text', text: 'Точный текст 1490 ₽' }, ...[0, 1, 2].map(i => ({ type: 'image', imagePrompt: 'Subject ' + i })),
] }] }];
const run = () => ({ id: 'run', inputKey: 'input', pageId: 'A', startedAt: 1, provider: 'codex', status: 'running', events: [],
  plan: { schemaVersion: 'design-assets/1.0', inputHash: 'hash', context: {}, slots: [0, 1, 2].map(i => ({
    id: String(i), variant: 0, path: ['tree', 0, 'children', i + 1], targetHash: 'target', subject: 'Subject ' + i,
    prompt: 'Subject ' + i, width: 1024, height: 1024, requiresAlpha: false, attempts: 0, status: 'planned',
  })) } });
const response = value => new Response(JSON.stringify(value), { status: 200 });

test('Derive, Mix and Reskin image operations preserve peers, respect mask, and safely undo', async () => {
  for (const type of ['derive', 'mix', 'reskin']) {
    store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
    const id = store.getState().addNode(type, 0, 0).id;
    const initial = variants();
    store.getState().setNodeData(id, type === 'derive' ? { variants: initial } : { ir: initial[0], mask: { images: false } });
    if (type === 'derive') {
      const source = store.getState().addNode('edit', 400, 0).id;
      const reference = variants()[0]; reference.tree[0].children[1].src = image;
      store.getState().setNodeData(source, { ir: reference });
      store.getState().connect({ node: source, port: 'ir' }, { node: id, port: 'reference' });
    }
    const calls = setup(new Set(['Subject 1']));
    const oldFetch = globalThis.fetch;
    globalThis.fetch = async (path, options) => {
      if (path.endsWith('/prepare')) { calls.push(['plan', JSON.parse(options.body)]); return response(run().plan); }
      return oldFetch(path, options);
    };
    if (type === 'reskin') {
      await fillResultAssets(id);
      assert.equal(calls.length, 0);
      store.getState().setNodeData(id, { mask: { images: true } });
    }
    await fillResultAssets(id);
    const data = store.getState().nodes[0].data;
    assert.equal(data.assetRuns.at(-1).status, 'partial');
    assert.equal(resultAssetsAreCurrent({ type, data }), true);
    if (type === 'derive') {
      const origin = calls.find(call => call[0] === 'plan')[1].context.referenceSource;
      assert.equal(origin.nodeId, String(store.getState().nodes[1].id));
      assert.equal(origin.port, 'reference'); assert.equal(origin.sourcePort, 'ir');
    }
    assert.equal(data.assetVersions.at(-1).after[0].tree[0].children[0].text, initial[0].tree[0].children[0].text);
    undoResultAssets(id);
    const restored = store.getState().nodes[0].data;
    assert.deepEqual(type === 'derive' ? restored.variants : [restored.ir], initial);
    assert.equal(restored.assetVersions.length, 0);
    assert.equal(restored.assetRuns.length, 1); // audit history remains after undo
    assert.equal(resultAssetsAreCurrent({ type, data: restored }), false);
  }
});

test('result image operation discards a late provider result after changing the graph', async () => {
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  const id = store.getState().addNode('derive', 0, 0).id;
  store.getState().setNodeData(id, { variants: variants() });
  setup();
  let resolve, started;
  const waiting = new Promise(r => started = r);
  window.designDNA.providers.imageRequest = () => { started(); return new Promise(r => resolve = r); };
  globalThis.fetch = async path => { assert(path.endsWith('/prepare')); return response(run().plan); };
  const pending = fillResultAssets(id);
  await waiting;
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  const other = store.getState().addNode('derive', 0, 0).id;
  store.getState().setNodeData(other, { variants: variants() });
  resolve({ image }); await pending;
  assert.equal(store.getState().nodes[0].data.assetRuns, undefined);
  assert.deepEqual(store.getState().nodes[0].data.variants, variants());
});

test('cancelling node images targets their provider and does not restart the shared worker', async () => {
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  const id = store.getState().addNode('derive', 0, 0).id;
  store.getState().setNodeData(id, { variants: variants() });
  const calls = setup(); let resolve, started;
  const waiting = new Promise(r => started = r);
  window.designDNA.api = { cancel: async () => assert.fail('shared worker restarted') };
  window.designDNA.providers.imageRequest = () => { started(); return new Promise(r => resolve = r); };
  globalThis.fetch = async path => { assert(path.endsWith('/prepare')); return response(run().plan); };
  const pending = fillResultAssets(id);
  await waiting; await store.getState().cancelRun(id);
  assert(calls.some(call => call[0] === 'cancel'));
  resolve({ image }); await pending;
  assert.deepEqual(store.getState().nodes[0].data.variants, variants());
  assert.equal(store.getState().nodes[0].data.assetRuns.at(-1).status, 'cancelled');
  assert.equal(store.getState().busy[id], false);
});
function setup(failed = new Set()) {
  const calls = [];
  window.designDNA = { providers: { imageRequest: async request => {
    calls.push(['image', request]); if (failed.has(request.prompt)) throw new Error('Temporary image failure'); return { image };
  }, cancel: async id => calls.push(['cancel', id]) } };
  globalThis.fetch = async (path, options) => {
    const body = JSON.parse(options.body); calls.push([path, body]);
    if (path.endsWith('/apply')) {
      const output = structuredClone(body.ir), index = Number(body.slot.id);
      output.tree[0].children[index + 1].src = result(index).src;
      return response({ ir: output, result: result(index) });
    }
    if (path.endsWith('/reconcile')) return response({ ir: body.ir, missing: [] });
    throw new Error('Unexpected request: ' + path);
  };
  return calls;
}
function options(onChange = () => {}) { return { signal: new AbortController().signal, scope: { check() {} }, onStage() {}, onChange }; }

test('failed slot preserves successful peers and retry only calls the missing image', async () => {
  const failed = new Set(['Subject 1']), calls = setup(failed), snapshots = [];
  const original = variants();
  const first = await executeAssetPlan(original, run(), options((ir, state) => snapshots.push(structuredClone({ ir, state }))));
  assert.equal(first.run.status, 'partial');
  assert.deepEqual(first.run.plan.slots.map(slot => slot.status), ['complete', 'failed', 'complete']);
  assert.equal(first.variants[0].tree[0].children[0].text, 'Точный текст 1490 ₽');
  assert.equal(original[0].tree[0].children[1].src, undefined);
  assert.ok(snapshots.some(item => item.state.plan.slots[0].status === 'complete' && item.state.plan.slots[2].status === 'planned'));
  failed.clear(); calls.length = 0;
  const second = await executeAssetPlan(first.variants, first.run, options());
  assert.equal(second.run.status, 'complete');
  assert.deepEqual(calls.filter(call => call[0] === 'image').map(call => call[1].prompt), ['Subject 1']);
  assert.equal(second.variants[0].tree[0].children[1].src, first.variants[0].tree[0].children[1].src);
});

test('cancel addresses the active provider request and never applies its late result', async () => {
  const calls = setup(); let resolve;
  window.designDNA.providers.imageRequest = request => { calls.push(['image', request]); return new Promise(r => resolve = r); };
  const controller = new AbortController(), snapshots = [];
  const pending = executeAssetPlan(variants(), run(), { ...options((_, state) => snapshots.push(state)), signal: controller.signal });
  controller.abort(); resolve({ image });
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(calls.find(call => call[0] === 'cancel')[1], calls.find(call => call[0] === 'image')[1].id);
  assert.equal(calls.filter(call => call[0].endsWith('/apply')).length, 0);
  const saved = settleInterruptedAssets([snapshots.at(-1)]);
  assert.equal(saved[0].status, 'cancelled');
  assert.equal(saved[0].plan.slots[0].status, 'failed');
});

test('a changed sheet or edited variant prevents a delayed asset from reaching apply', async () => {
  const calls = setup(); let resolve, owned = true;
  window.designDNA.providers.imageRequest = () => new Promise(r => resolve = r);
  const pending = executeAssetPlan(variants(), run(), { ...options(), scope: { check() { if (!owned) throw new DOMException('Stale', 'AbortError'); } } });
  owned = false; resolve({ image });
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(calls.length, 0);
});

test('Claude does not silently call Codex; the separate explicit image route works', async () => {
  assert.equal(effectiveAssetProvider('auto', 'claude'), 'off');
  assert.equal(effectiveAssetProvider('codex', 'claude'), 'codex');
  assert.equal(effectiveAssetProvider('off', 'codex'), 'off');
  const calls = setup(), input = run(); input.provider = 'off';
  const output = await executeAssetPlan(variants(), input, options());
  assert.equal(output.run.status, 'partial');
  assert.equal(calls.length, 0);
});

test('plans and delivered image identities survive actual project serialization', async () => {
  setup();
  const output = await executeAssetPlan(variants(), run(), options());
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  const id = store.getState().addNode('generator', 0, 0).id;
  store.getState().setNodeData(id, { variants: output.variants, assetRuns: assetRunPatch([], output.run), assetMode: 'codex' });
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState()))).nodes[0].data;
  assert.deepEqual(restored.assetRuns, [output.run]);
  assert.deepEqual(restored.variants, output.variants);
  assert.equal(restored.assetMode, 'codex');
  const interrupted = run(); interrupted.plan.slots[0].status = 'running';
  store.getState().setNodeData(id, { assetRuns: [interrupted] });
  const reopened = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState()))).nodes[0].data;
  assert.equal(reopened.assetRuns[0].status, 'cancelled');
  assert.equal(reopened.assetRuns[0].plan.slots[0].status, 'failed');
});

test('generator saves assets before Quality Pass and offers a persisted per-slot retry', async () => {
  const failures = new Set(['Subject 1']), calls = setup(failures);
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  store.setState({ activePageId: 'A', pages:[{id:'A',name:'A',nodes:[],edges:[],view:{x:0,y:0,zoom:1},nextId:1}],pageRuntimes:{}, busy: {}, designSystemPicker: null });
  const id = store.getState().addNode('generator', 0, 0).id;
  store.getState().setNodeData(id, { ownPrompt: 'Kitchen', count: 1, provider: 'codex' });
  window.designDNA.providers.chatRequest = async () => ({ content: '{}' });
  const underlying = globalThis.fetch;
  globalThis.fetch = async (path, opts) => {
    const body = JSON.parse(opts.body);
    if (path === '/api/generate') return response(body.prepareOnly ? { preparedContextId: 'prepared', prompts: [{ messages: [] }] } : { variants: variants() });
    if (path.endsWith('/assets/prepare')) return response(run().plan);
    if (path === '/api/quality-pass/codex-step') {
      assert.ok(body.ir.tree[0].children[1].src);
      return response({ ir: body.ir, scorecard: { score: 92, issues: [] }, passed: true, acceptance: { status: 'verified' } });
    }
    return underlying(path, opts);
  };
  await store.getState().runGenerator(id);
  const data = store.getState().nodes.find(node => Number(node.id) === id).data;
  assert.equal(data.assetRuns.at(-1).status, 'partial', JSON.stringify({ status: store.getState().statuses[id], calls: calls.map(call => call[0]) }));
  assert.equal(data.qualityReviews[0].passed, false);
  assert.equal(calls.filter(call => call[0] === 'image').length, 3);
  assert.equal(store.getState().busy[id], false);
  failures.clear();
  store.getState().setNodeData(id, { assetMode: 'codex' });
  await store.getState().retryGeneratorAssets(id, '1');
  const retried = store.getState().nodes.find(node => Number(node.id) === id).data;
  assert.equal(retried.assetRuns.at(-1).status, 'complete', JSON.stringify(store.getState().statuses[id]));
  assert.equal(retried.assetRuns[0].status, 'partial');
  assert.equal(retried.qualityReviews[0].passed, true);
  assert.equal(calls.filter(call => call[0] === 'image').length, 4);
});

test('reference image role and notes participate in generation input identity', () => {
  const reference = { id: '1', type: 'reference', data: { image, role: 'composition', brief: 'Use grouping', fileName: 'layout.png' } };
  const generator = { id: '2', type: 'generator', data: { ownPrompt: 'Settings', provider: 'claude' } };
  const nodes = [reference, generator], edges = [{ id: 'e', source: '1', sourceHandle: 'image', target: '2', targetHandle: 'reference' }];
  assert.deepEqual(generatorVisualReference(nodes, edges, generator), { image, role: 'composition', origin: 'layout.png', notes: 'Use grouping' });
  const before = generatorInputKey(nodes, edges, generator, null);
  reference.data.role = 'reproduce';
  assert.notEqual(generatorInputKey(nodes, edges, generator, null), before);
  generator.data.referenceRole = 'style';
  assert.equal(generatorVisualReference(nodes, edges, generator).role, 'style');
  edges[0].sourceHandle = 'style';
  assert.equal(generatorVisualReference(nodes, edges, generator), undefined);
});

test('series resolves persisted first asset as a visual anchor and keeps variant boundaries', async () => {
  const calls = setup(), input = run();
  window.designDNA.blobs = { getMany: async names => Object.fromEntries(names.map(name => [name, image])) };
  input.plan.context.coherentSeries = true;
  input.plan.slots[2].variant = 1;
  const output = await executeAssetPlan([...variants(), ...variants()], input, options());
  assert.equal(output.run.status, 'complete');
  const requests = calls.filter(call => call[0] === 'image').map(call => call[1]);
  assert.deepEqual(requests.map(request => request.referenceImage), [undefined, image, undefined]);
  assert.equal(output.run.plan.slots[1].referenceAssetId, '0');
  assert.equal(output.run.plan.slots[2].referenceAssetId, undefined);
});

test('concept is separate from final IR, persists, and never switches a disabled provider', async () => {
  const calls = setup(), snapshots = [];
  const initial = { id: 'concept', inputKey: 'key', startedAt: 1, conceptOnly: true, provider: 'codex', status: 'running' };
  globalThis.fetch = async (path, opts) => {
    calls.push([path, JSON.parse(opts.body)]);
    return response(path.endsWith('/prepare') ? { prompt: 'Composition study' } : { result: result(7), conceptOnly: true });
  };
  const completed = await createVisualConcept(initial, { brief: 'Settings form' }, {
    signal: new AbortController().signal, check() {}, onChange: run => snapshots.push(run), reference: { image, role: 'style', origin: 'upload' },
  });
  assert.equal(completed.status, 'complete');
  assert.equal(completed.result.src, result(7).src);
  assert.equal(calls.find(call => call[0] === 'image')[1].referenceImage, image);
  assert.equal(completed.ir, undefined);
  assert.ok(snapshots.some(run => run.status === 'running' && run.prompt));
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  const id = store.getState().addNode('generator', 0, 0).id;
  store.getState().setNodeData(id, { conceptRuns: conceptRunPatch([initial], completed) });
  const reopened = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState()))).nodes[0].data;
  assert.deepEqual(reopened.conceptRuns, [completed]);
  calls.length = 0;
  const failed = await createVisualConcept({ ...initial, provider: 'off' }, { brief: 'Settings' }, {
    signal: new AbortController().signal, check() {}, onChange() {},
  });
  assert.equal(failed.status, 'failed');
  assert.equal(calls.length, 0);
});

test('cancelled concept cannot store a late image or survive hydration as running', async () => {
  const calls = setup(), controller = new AbortController(); let resolve;
  const initial = { id: 'cancel-concept', inputKey: 'key', startedAt: 1, conceptOnly: true, provider: 'codex', status: 'running' };
  globalThis.fetch = async () => response({ prompt: 'Concept' });
  window.designDNA.providers.imageRequest = () => new Promise(done => { resolve = done; });
  const pending = createVisualConcept(initial, { brief: 'Settings' }, { signal: controller.signal, check() {}, onChange() {} });
  while (!resolve) await new Promise(done => setImmediate(done));
  controller.abort(); resolve({ image });
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(calls.find(call => call[0] === 'cancel')[1], 'concept-cancel-concept');
  const id = Number(store.getState().nodes[0].id);
  store.getState().setNodeData(id, { conceptRuns: [initial] });
  const reopened = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState()))).nodes[0].data;
  assert.equal(reopened.conceptRuns[0].status, 'cancelled');
});

test('retry from a previous generation cannot touch a new layout with the same prompt', async () => {
  const calls = setup();
  store.getState().loadGraph({ nodes: [], edges: [], nextId: 1 });
  const id = store.getState().addNode('generator', 0, 0).id;
  const previous = run(); previous.generationStartedAt = 1;
  store.getState().setNodeData(id, { ownPrompt: 'Same prompt', variants: variants(), assetRuns: [previous],
    generationContext: { inputKey: 'same', baseInputKey: 'same', pageId: store.getState().activePageId, startedAt: 2, brief: 'Same prompt' } });
  await store.getState().retryGeneratorAssets(id);
  assert.equal(calls.length, 0);
  assert.equal(store.getState().nodes[0].data.assetRuns.length, 1);
});
