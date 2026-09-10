import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'image-node-tests-'));
const files = [];
globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
const realTimeout = globalThis.setTimeout;
globalThis.setTimeout = (...args) => { const timer = realTimeout(...args); timer.unref(); return timer; };
async function bundle(file) {
  const output = join(dir, file.split('/').at(-1) + '.mjs'); files.push(output);
  buildSync({ entryPoints: [fileURLToPath(new URL('../src/' + file + '.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile: output, logLevel: 'silent' });
  return import(pathToFileURL(output));
}
const { useFlowStore: store } = await bundle('flow/store');
const { pullInput } = await bundle('flow/dataflow');
const { downloadImage } = await bundle('flow/image-assets');
const { payloadToRf, parseLegacyPayload, buildSavePayload } = await bundle('flow/serialize');
after(() => { for (const file of files) unlinkSync(file); rmdirSync(dir); });
const png = 'data:image/png;base64,AAAA';
const blob = 'a'.repeat(64) + '.png';
function reset() { store.getState().loadGraph({nodes:[],edges:[],nextId:1}); store.setState({ pages:[{id:'A',name:'A',nodes:[],edges:[],nextId:1,view:{x:0,y:0,zoom:1}}],pageRuntimes:{}, nodes: [], edges: [], nextId: 1, activePageId: 'A', statuses: {}, busy: {}, graphHistory: { past: [], future: [] } }); }
const add = type => store.getState().addNode(type, 0, 0).id;
const patch = (id, data) => store.getState().setNodeData(id, data);
const node = id => store.getState().nodes.find(n => Number(n.id) === id);
const connect = (a, ap, b, bp) => store.getState().connect({ node: a, port: ap }, { node: b, port: bp });
function mocks() {
  const calls = [];
  window.designDNA = {
    providers: {
      imageRequest: async request => { calls.push(['image', request]); return { image: png, transparent: true }; },
      cancel: async id => { calls.push(['cancel', id]); },
    },
    blobs: { getMany: async () => ({ [blob]: png }) },
    files: { save: async (...args) => { calls.push(['save', ...args]); } },
  };
  globalThis.fetch = async (path, options) => {
    calls.push([path, JSON.parse(options.body)]);
    const format = path === '/api/image/remove-background' ? 'png' : JSON.parse(options.body).outputFormat;
    return new Response(JSON.stringify({ png: format === 'jpeg' ? 'data:image/jpeg;base64,AAAA' : png, width: 64, height: 64, format, transparent: format === 'png' }), { status: 200 });
  };
  return calls;
}

test('raster generation goes through imageRequest and produces the requested JPEG', async () => {
  reset(); const calls = mocks(); const id = add('image');
  patch(id, { prompt: 'product photo', outputFormat: 'jpeg' });
  await store.getState().runImage(id);
  assert.equal(calls[0][0], 'image');
  assert.equal(calls[1][0], '/api/image/convert');
  assert.equal(calls[1][1].outputFormat, 'jpeg');
  assert.equal(node(id).data.variants[0].format, 'jpeg');
  assert.equal(store.getState().busy[id], false);
});

test('image -> reference -> remove background resolves saved blobs and requires alpha PNG', async () => {
  reset(); const calls = mocks();
  const image = add('image'), ref = add('reference'), cutout = add('removebackground');
  patch(image, { variants: [{ png: 'ddna://blobs/' + blob }], active: 0 });
  assert.ok(connect(image, 'image', ref, 'image'));
  assert.ok(connect(ref, 'image', cutout, 'image'));
  assert.equal(pullInput(store.getState().nodes, store.getState().edges, node(cutout), 'image'), 'ddna://blobs/' + blob);
  await store.getState().runImage(cutout);
  assert.equal(calls[0][1].referenceImage, png);
  assert.equal(calls[0][1].removeBackground, true);
  assert.equal(calls[1][0], '/api/image/remove-background');
  assert.deepEqual(calls[1][1], { image: png, mask: png });
  assert.equal(node(cutout).data.variants.length, 1);
  await downloadImage('ddna://blobs/' + blob, 'cutout.png');
  assert.deepEqual(calls.at(-1), ['save', 'cutout.png', 'AAAA']);
});

test('missing cutout input or unavailable native transport cannot produce false success', async () => {
  reset(); const calls = mocks(); const cutout = add('removebackground');
  await store.getState().runImage(cutout);
  assert.equal(calls.length, 0); assert.equal(store.getState().statuses[cutout].kind, 'err');
  const image = add('image'); patch(image, { prompt: 'test' }); window.designDNA = undefined;
  await store.getState().runImage(image);
  assert.equal(calls.length, 0); assert.equal(store.getState().statuses[image].kind, 'err');
});

test('a delayed image cannot overwrite another page with the same node ID', async () => {
  reset(); mocks(); const id = add('image'); patch(id, { prompt: 'page A' });
  let resolve; window.designDNA.providers.imageRequest = () => new Promise(r => resolve = r);
  const pending = store.getState().runImage(id);
  const other = structuredClone(node(id)); other.data.prompt = 'page B'; other.data.variants = [{ png: 'original-B' }];
  store.getState().createPage('B');
  store.setState({ nodes: [other], busy: {}, statuses: {} });
  resolve({ image: png }); await pending;
  assert.equal(node(id).data.variants[0].png, 'original-B');
  assert.deepEqual(store.getState().statuses, {});
});

test('cancel targets the native request, never restarts the Python worker and never appends output', async () => {
  reset(); const calls = mocks(); const id = add('image'); patch(id, { prompt: 'test' });
  let resolve;
  window.designDNA.providers.imageRequest = request => { calls.push(['image', request]); return new Promise(r => resolve = r); };
  window.designDNA.api = { cancel: () => { throw new Error('Worker restart forbidden'); } };
  const pending = store.getState().runImage(id);
  await store.getState().cancelRun(id);
  resolve({ image: png }); await pending;
  assert.equal(calls.find(c => c[0] === 'cancel')[1], calls[0][1].id);
  assert.equal(node(id).data.variants.length, 0);
  assert.equal(store.getState().busy[id], false);
});

test('changing the wired reference while GPT is running discards the obsolete mask', async () => {
  reset(); const calls = mocks(); const ref = add('reference'), id = add('removebackground');
  patch(ref, { image: png }); connect(ref, 'image', id, 'image');
  let resolve; window.designDNA.providers.imageRequest = () => new Promise(r => resolve = r);
  const pending = store.getState().runImage(id);
  await new Promise(r => setImmediate(r));
  patch(ref, { image: 'data:image/png;base64,BBBB' });
  resolve({ image: png }); await pending;
  assert.equal(node(id).data.variants.length, 0);
  assert.equal(calls.length, 0);
});

test('image variants persist, history stays bounded, and legacy image nodes remain SVG', async () => {
  reset(); mocks(); const id = add('image'); patch(id, { prompt: 'test' });
  for (let i = 0; i < 5; i++) await store.getState().runImage(id);
  assert.equal(node(id).data.variants.length, 4);
  const saved = buildSavePayload(store.getState());
  const restored = payloadToRf(parseLegacyPayload(saved));
  assert.equal(restored.nodes[0].data.engine, 'raster');
  assert.equal(restored.nodes[0].data.variants.length, 4);
  delete saved.nodes[0].data.engine;
  assert.equal(payloadToRf(parseLegacyPayload(saved)).nodes[0].data.engine, 'svg');
});


test('selected raster model is sent to Codex and persists separately from SVG selection', async () => {
  reset(); const calls = mocks(); const id = add('image');
  patch(id, { prompt: 'product', rasterModel: 'gpt-6-astra', model: 'opus' });
  await store.getState().runImage(id);
  assert.equal(calls[0][1].model, 'gpt-6-astra');
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState()))).nodes[0];
  assert.equal(restored.data.rasterModel, 'gpt-6-astra');
  assert.equal(restored.data.model, 'opus');
});

for (const [provider, model] of [['codex', 'gpt-6-astra'], ['claude', 'opus']]) {
  test(`SVG passes selected ${provider} model to the actual chat request`, async () => {
    reset(); mocks(); const id = add('image'); let request;
    patch(id, { prompt: 'icon', engine: 'svg', provider, model });
    window.designDNA.providers.chatRequest = async input => { request = input; return { content: '<svg/>' }; };
    globalThis.fetch = async (path, options) => {
      const body = JSON.parse(options.body);
      assert.equal(body.model, model);
      return new Response(JSON.stringify(body.prepareOnly ? { prompts: [{ messages: [{ role: 'user', content: 'icon' }] }] }
        : { png, svg: '<svg/>', width: 64, height: 64 }), { status: 200 });
    };
    await store.getState().runImage(id);
    assert.equal(request.provider, provider);
    assert.equal(request.model, model);
    assert.equal(node(id).data.variants.length, 1);
  });
}
