import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'node-contracts-'));
globalThis.window = { addEventListener() {}, dispatchEvent() {} };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
// Autosave/toast timers are unrelated to these synchronous graph contracts.
const realTimeout = globalThis.setTimeout;
globalThis.setTimeout = (...args) => { const t = realTimeout(...args); t.unref(); return t; };
const bundle = (file) => {
  const out = join(dir, file.split('/').at(-1) + '.mjs');
  buildSync({ entryPoints: [fileURLToPath(new URL('../src/' + file + '.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent' });
  return import(pathToFileURL(out));
};
const { useFlowStore: store, resolveDesignSystemAiProvider } = await bundle('flow/store');
const { NODE_DEFS, portsOfNode, defaultData } = await bundle('flow/ports');
const { parseLegacyPayload, payloadToRf, buildSavePayload, buildPagesProjectPayload, prepareProjectForStorage, compactForStorage } = await bundle('flow/serialize');
const { offloadBlobsInPlace } = await bundle('desktop/blobStore');
const { outValue } = await bundle('flow/dataflow');
after(() => rmSync(dir, { recursive: true, force: true }));
const ir = (text) => ({ version: '1.1', frame: { width: 1440 }, tree: [{ id: 'hero', type: 'hero', variant: 'center', props: { heading: text } }] });
const reset = () => store.setState({ nodes: [], edges: [], nextId: 1, statuses: {}, busy: {}, graphHistory: { past: [], future: [] } });
const add = (type) => store.getState().addNode(type, 0, 0).id;
const patch = (id, data) => store.getState().setNodeData(id, data);
const node = (id) => store.getState().nodes.find(n => Number(n.id) === id);
const connect = (a, ap, b, bp) => store.getState().connect({ node: a, port: ap }, { node: b, port: bp });

const dsFixture = (provider = 'codex') => {
  reset(); const source = add('sourceimport'), ds = add('designsystem');
  patch(source, { aiProvider: provider, blocks: [{ name: 'hero', lit: true, ir: ir('Source') }] });
  connect(source, 'artifact', ds, 'artifact');
  patch(ds, { systemId: 'kit', sourceUpdate: false, autoPublish: false, document: { id: 'kit', name: 'Kit', components: {} } });
  return { source, ds };
};
const preparedDs = (operation, provider, stage = operation) => ({
  prepareId: stage, documentHash: `hash-${stage}`, operation, provider, reasoningEffort: 'high', stage,
  tasks: [{ id: `${stage}-task`, status: 'ready', messages: [{ role: 'user', content: 'server-owned prompt' }] }],
});
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), { status });

test('Page composes all nine Source blocks and persists their port order', () => {
  reset();
  const source = add('sourceimport'), page = add('page');
  const blocks = Array.from({ length: 9 }, (_, i) => ({name: `source-${i}`, lit: true,
    ir: {version:'1.1', tree:[{id:'source',type:'source-block',variant:'dom-capture',sourceKey:'root',
      frame:{width:1440,height:100}, children:[{type:'text',sourceKey:'root/text',text:`Exact ${i}`,
        style:{color:'#9d9aab'},responsive:{mobile:{text:`Mobile ${i}`,frame:{width:200}}}}]}]}}));
  patch(source, {blocks});
  while (node(page).data.inputs.length < 9) store.getState().addPageInput(page);
  const inputs = [...node(page).data.inputs];
  blocks.forEach((b,i) => connect(source,b.name,page,inputs[i]));
  const before = JSON.stringify(node(source).data.blocks);
  store.getState().runPage(page);
  assert.equal(node(page).data.ir.tree.length,9);
  assert.deepEqual(node(page).data.ir.tree.map(s=>s.children[0].text),blocks.map(b=>b.ir.tree[0].children[0].text));
  assert.equal(node(page).data.ir.tree[8].children[0].responsive.mobile.text,'Mobile 8');
  assert.equal(JSON.stringify(node(source).data.blocks),before);
  const saved = buildSavePayload(store.getState());
  const loaded = payloadToRf(parseLegacyPayload(saved));
  assert.deepEqual(loaded.nodes.find(n=>Number(n.id)===page).data.inputs,inputs);
  assert.equal(loaded.edges.filter(e=>Number(e.target)===page).length,9);
  for(let i=0;i<40;i++) store.getState().addPageInput(page);
  assert.equal(node(page).data.inputs.length,32);
  assert.equal(new Set(node(page).data.inputs).size,32);
});

test('legacy UI Kit without Source screenshots stops before AI and explains recovery', async () => {
  const previousFetch = globalThis.fetch;
  try {
    const {ds} = dsFixture();
    patch(ds,{document:{id:'kit',reviewComponents:{header:{sourceRef:{evidenceKey:'capture'}}},
      referenceAssets:{capture:{referencePreviews:{},blockSizes:{desktop:{width:100,height:50}}}}}});
    globalThis.fetch = async () => { throw new Error('Missing evidence must be detected before preparing AI'); };
    assert.equal(await store.getState().runDesignSystemAi(ds,'master-review'),null);
    assert.match(node(ds).data.lastError,/Нет исходных снимков Source/);
    assert.match(node(ds).data.lastError,/Обновите Source Import/);
    assert.equal(node(ds).data.pipelineStatus['master-review'].status,'failed');
    assert.equal(node(ds).data.document.reviewComponents.header.sourceRef.evidenceKey,'capture');
  } finally {globalThis.fetch=previousFetch;}
});

test('autosave isolates live data, stores DS references only and preserves canonical Source IR bytes', async () => {
  const desktop = window.designDNA;
  try {
    const { source, ds } = dsFixture();
    const svg = 'data:image/svg+xml;base64,' + 'A'.repeat(40000);
    const canonical = { ...ir('Canonical'), meta: { fontFaces: [{ url: svg }], preview: svg } };
    canonical.tree[0].props.image = svg;
    const document = { id: 'kit', schemaVersion: 'design-system/1.1', components: { hero: { masterIr: canonical, sourceRef: { masterHash: 'immutable-pin' } } }, styleGuide: { irTokens: { color: { primary: '#123456' } } } };
    patch(source, { blocks: [{ name: 'hero', ir: canonical, lit: true }], image: svg });
    patch(ds, { document, _dsFinishing: 'active-finish', aiProvider: 'inherit', pipelineStatus: { organize: { status: 'success', message: 'ready' } } });
    const originalSource = JSON.stringify(node(source).data), originalDs = JSON.stringify(node(ds).data);
    const storedName = 'a'.repeat(64) + '.svg'; let puts = 0;
    window.designDNA = { blobs: { put: async () => { puts++; return { name: storedName, sha256: 'a'.repeat(64) }; } } };
    const raw = buildPagesProjectPayload(store.getState());
    const saved = compactForStorage(await prepareProjectForStorage(raw));
    const nodes = saved.pages.find(p => p.id === saved.activePageId).graph.nodes;
    const storedDs = nodes.find(n => n.id === ds).data, storedSource = nodes.find(n => n.id === source).data;
    assert.equal(JSON.stringify(node(source).data), originalSource);
    assert.equal(JSON.stringify(node(ds).data), originalDs);
    assert.equal(storedDs._dsFinishing, undefined);
    assert.equal(storedDs.document, null); assert.equal(storedDs.systemId, 'kit');
    assert.equal(storedDs.aiProvider, 'inherit'); assert.equal(storedDs.pipelineStatus.organize.status, 'success');
    assert.deepEqual(storedDs.resolvedTokens, document.styleGuide.irTokens);
    assert.deepEqual(storedSource.blocks[0].ir, canonical);
    assert.equal(storedSource.image, `ddna://blobs/${storedName}`); assert.equal(puts, 1);
    const loaded = payloadToRf(parseLegacyPayload(saved.pages.find(p => p.id === saved.activePageId).graph));
    assert.deepEqual(loaded.nodes.find(n => Number(n.id) === source).data.blocks[0].ir, canonical);
  } finally { window.designDNA = desktop; }
});

test('generic offload never traverses DS documents or canonical IR even for detached/legacy payloads', async () => {
  const desktop = window.designDNA;
  try {
    const svg = 'data:image/svg+xml;base64,' + 'A'.repeat(40000);
    const canonical = { version: '1.1', tokens: {}, tree: [{ props: { image: svg } }] };
    const payload = { document: { schemaVersion: 'design-system/1.1', referenceAssets: { image: svg }, components: { a: { masterIr: canonical } } },
      blocks: [{ ir: canonical, fidelityReport: {provenance:{assets:[{url:svg,ref:svg}], fingerprint:'captured-hash',preview:svg}} }],
      sourceArtifact: {provenance:{preview:svg}}, variants: [canonical], channels: { main: canonical } };
    const before = JSON.stringify(payload); let puts = 0;
    window.designDNA = { blobs: { put: async () => { puts++; throw new Error('canonical offload forbidden'); } } };
    assert.equal(await offloadBlobsInPlace(payload), false);
    assert.equal(JSON.stringify(payload), before); assert.equal(puts, 0);
    assert.equal(JSON.stringify(compactForStorage(payload)), before);
  } finally { window.designDNA = desktop; }
});

test('autosave while desktop AI awaits chat does not invalidate captured Source or DS fingerprints', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    const { source, ds } = dsFixture();
    const svg = 'data:image/svg+xml;base64,' + 'A'.repeat(40000);
    const canonical = { ...ir('Canonical'), meta: { image: svg } };
    patch(source, { blocks: [{ name: 'hero', lit: true, ir: canonical }], image: svg });
    patch(ds, { document: { id: 'kit', schemaVersion: 'design-system/1.1', components: { hero: { masterIr: canonical } } } });
    let finishChat, startedChat; const ready = new Promise(resolve => { startedChat = resolve; }); let applies = 0;
    window.designDNA = {
      blobs: { put: async () => ({ name: 'a'.repeat(64) + '.svg', sha256: 'a'.repeat(64) }) },
      providers: { chatRequest: () => { startedChat(); return new Promise(resolve => { finishChat = resolve; }); } },
    };
    globalThis.fetch = async (url, init) => {
      if (url.endsWith('/prepare')) return jsonResponse(preparedDs('style-review', 'codex'));
      applies++; const body = JSON.parse(init.body);
      assert.equal(body.document.components.hero.masterIr.meta.image, svg);
      return jsonResponse({ document: body.document, results: [], complete: true });
    };
    const running = store.getState().runDesignSystemAi(ds, 'style-review'); await ready;
    await prepareProjectForStorage(buildPagesProjectPayload(store.getState()));
    finishChat({ content: '{}', provider: 'codex' });
    assert.ok(await running); assert.equal(applies, 1); assert.equal(node(ds).data.pipelineStatus['style-review'].status, 'success');
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('DS provider inherits the actual artifact wire, preserves explicit API choices and survives save-load', () => {
  const { source, ds } = dsFixture();
  const stale = add('sourceimport'); patch(stale, { aiProvider: 'openai' }); patch(ds, { sourceNodeId: stale });
  const resolve = () => resolveDesignSystemAiProvider(store.getState().nodes, store.getState().edges, node(ds));
  assert.equal(resolve(), 'codex');
  patch(source, { aiProvider: 'claude' }); assert.equal(resolve(), 'claude');
  for (const provider of ['inherit', 'codex', 'claude', 'openai', 'astra']) {
    patch(ds, { aiProvider: provider, pipelineStatus: { organize: { status: 'failed', message: 'offline', provider: 'codex', updatedAt: 'now' } } });
    assert.equal(resolve(), provider === 'inherit' ? 'claude' : provider);
    const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState()))).nodes.find(n => Number(n.id) === ds);
    assert.equal(restored.data.aiProvider, provider);
    assert.equal(restored.data.pipelineStatus.organize.status, 'failed');
  }
});

test('Source and DS restore interrupted stages without phantom running or fabricated success', () => {
  const { source, ds } = dsFixture();
  for (const id of [source, ds]) patch(id, { pipelineStatus: {
    refine: { status: 'running', provider: 'claude', message: 'pending', updatedAt: 'captured-time' },
    import: { status: 'success', provider: 'codex', message: 'done', updatedAt: 'earlier' },
  } });
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  for (const id of [source, ds]) {
    const data = restored.nodes.find(n => Number(n.id) === id).data;
    assert.equal(data.pipelineStatus.refine.status, 'cancelled');
    assert.equal(data.pipelineStatus.refine.provider, 'claude');
    assert.equal(data.pipelineStatus.refine.updatedAt, 'captured-time');
    assert.equal(data.pipelineStatus.import.status, 'success');
    assert.equal(node(id).data.pipelineStatus.refine.status, 'running');
  }
});

test('project-save echo through DB reload preserves running AI; a different DS hash still invalidates it', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const externalChange of [false, true]) {
      const { ds } = dsFixture();
      const document = { id: 'kit', contentHash: 'sha256:original', components: {} };
      patch(ds, { document, sourceUpdate: false });
      let finishChat, started; const ready = new Promise(resolve => { started = resolve; }); let savedProject, applies = 0;
      window.designDNA = { providers: { chatRequest: () => { started(); return new Promise(resolve => { finishChat = resolve; }); } } };
      globalThis.fetch = async (url, init) => {
        const body = JSON.parse(init.body || '{}');
        if (url.endsWith('/prepare')) return jsonResponse(preparedDs('style-review', 'codex'));
        if (url === '/api/project/save') {
          savedProject = JSON.parse(JSON.stringify(body.project));
          const savedDs = savedProject.pages.find(p => p.id === savedProject.activePageId).graph.nodes.find(n => n.id === ds);
          assert.equal(savedDs.data.document, null); assert.equal(savedDs.data.contentHash, document.contentHash);
          if (externalChange) savedDs.data.contentHash = 'sha256:external';
          assert.equal(await store.getState().replaceProjectFromDb(), true);
          return jsonResponse({ ok: true, revision: 'saved-revision' });
        }
        if (url === '/api/project/load') return jsonResponse({ project: savedProject, revision: 'saved-revision' });
        assert.ok(url.endsWith('/apply')); applies++;
        return jsonResponse({ document: body.document, results: [], complete: true });
      };
      const running = store.getState().runDesignSystemAi(ds, 'style-review'); await ready;
      const status = store.getState().statuses[ds];
      const snapshot = compactForStorage(await prepareProjectForStorage(buildPagesProjectPayload(store.getState())));
      await fetch('/api/project/save', { method: 'POST', body: JSON.stringify({ project: snapshot }) });
      if (!externalChange) {
        assert.equal(node(ds).data.document, document); assert.equal(store.getState().busy[ds], true);
        assert.equal(store.getState().statuses[ds], status); assert.equal(node(ds).data.sourceUpdate, false);
      } else assert.equal(node(ds).data.document, null);
      finishChat({ content: '{}', provider: 'codex' });
      const result = await running;
      assert.equal(!!result, !externalChange); assert.equal(applies, externalChange ? 0 : 1);
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('all DS AI actions route every desktop provider via prepare-chat-apply with immutable selected provider', async () => {
  const originalFetch = globalThis.fetch, originalDesktop = window.designDNA;
  try {
    for (const provider of ['codex', 'claude', 'openai', 'astra']) for (const operation of ['organize', 'style-review', 'master-review']) {
      const { source, ds } = dsFixture(provider); const calls = [], chats = [];
      window.designDNA = { providers: { chatRequest: async request => {
        chats.push(request); patch(source, { aiProvider: provider === 'codex' ? 'claude' : 'codex' }); patch(ds, { aiProvider: 'openai' });
        return { content: '{"answer":true}', provider: ['openai', 'astra'].includes(provider) ? 'codex' : provider,
          transport: { requestedProvider: provider, model: provider === 'astra' ? 'gpt-6-astra' : 'gpt-5.6-sol' } };
      } } };
      globalThis.fetch = async (url, init) => {
        const body = JSON.parse(init.body); calls.push({ url, body });
        if (url.endsWith('/prepare')) return jsonResponse(preparedDs(operation, provider));
        assert.ok(url.endsWith('/apply'), url);
        return jsonResponse({ document: { ...body.document, changed: true }, complete: true, results: [], summary: {} });
      };
      const result = await store.getState().runDesignSystemAi(ds, operation, 'mobile');
      assert.ok(result); assert.equal(chats.length, 1);
      assert.equal(chats[0].provider, provider); assert.equal(chats[0].messages[0].content, 'server-owned prompt');
      if (provider === 'codex') { assert.equal(chats[0].model, null); assert.equal(chats[0].reasoning, undefined); }
      assert.equal(calls[0].body.provider, provider);
      assert.equal(calls[1].body.documentHash, `hash-${operation}`);
      assert.deepEqual(calls[1].body.responses, [{ taskId: `${operation}-task`, output: '{"answer":true}' }]);
      assert.equal(node(ds).data.document.changed, true); assert.equal(node(ds).data.pipelineStatus[operation].provider, provider);
    }
  } finally { globalThis.fetch = originalFetch; window.designDNA = originalDesktop; }
});

test('malformed DS output gets one same-provider/profile correction of only the rejected task', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const provider of ['codex', 'claude']) for (const operation of ['style-review', 'master-review']) for (const validCorrection of [true, false]) {
      const { ds } = dsFixture(provider); const before = structuredClone(node(ds).data.document);
      const preparation = { ...preparedDs(operation, provider), tasks: ['good', 'bad'].map(id => ({ id, status: 'ready', messages: [{ role: 'system', content: 'schema rules' }, { role: 'user', content: id }] })) };
      const chats = [], applies = []; let prepares = 0;
      window.designDNA = { providers: { chatRequest: async request => {
        chats.push(request);
        const correction = request.id.endsWith(':format-correction');
        return { provider, content: correction && validCorrection ? '{"fixed":true}' : request.messages.at(-1).content === 'good' ? '{"good":true}' : '{"broken":true' };
      } } };
      globalThis.fetch = async (url, init) => {
        if (url.endsWith('/prepare')) { prepares++; return jsonResponse(preparation); }
        assert.ok(url.endsWith('/apply')); const body = JSON.parse(init.body); applies.push(body);
        if (applies.length === 1 || !validCorrection) return new Response(JSON.stringify({ detail: {
          code: 'invalid-ai-output', taskId: 'bad', stage: operation, retryable: true, message: 'JSON object missing closing brace', path: 'responses[1].output',
        } }), { status: 422 });
        return jsonResponse({ document: { ...body.document, corrected: true }, results: [], complete: true });
      };
      const result = await store.getState().runDesignSystemAi(ds, operation);
      assert.equal(!!result, validCorrection); assert.equal(prepares, 1); assert.equal(chats.length, 3); assert.equal(applies.length, 2);
      const correction = chats[2]; const original = chats.find(c => c.messages.at(-1).content === 'bad');
      for (const key of ['provider', 'profile', 'model', 'reasoning']) assert.deepEqual(correction[key], original[key]);
      assert.deepEqual(correction.messages.slice(0, 2), original.messages);
      assert.equal(correction.messages[2].content, '{"broken":true');
      assert.match(correction.messages[3].content, /complete corrected JSON/);
      assert.equal(correction.profile, operation === 'master-review' ? 'quality_judge' : 'editor');
      assert.deepEqual(applies[1].responses[0], applies[0].responses[0]);
      for (const key of ['prepareId', 'documentHash', 'document']) assert.deepEqual(applies[1][key], applies[0][key]);
      if (!validCorrection) { assert.deepEqual(node(ds).data.document, before); assert.equal(node(ds).data.pipelineStatus[operation].status, 'failed'); }
      else assert.equal(node(ds).data.document.corrected, true);
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('different malformed tasks each get one correction with a bounded complete-envelope apply loop', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  const { ds } = dsFixture(); const corrected = [], applies = [];
  window.designDNA = { providers: { chatRequest: async request => {
    if (request.id.endsWith(':format-correction')) { corrected.push(request.messages[0].content); return { provider: 'codex', content: '{}' }; }
    return { provider: 'codex', content: '{' };
  } } };
  globalThis.fetch = async (url, init) => {
    if (url.endsWith('/prepare')) return jsonResponse({ ...preparedDs('master-review', 'codex'), tasks: ['a', 'b', 'c', 'd'].map(id => ({ id, status: 'ready', messages: [{ role: 'user', content: id }] })) });
    const body = JSON.parse(init.body); applies.push(body);
    const bad = body.responses.find(r => r.output === '{');
    if (bad) return new Response(JSON.stringify({ detail: { code: 'invalid-ai-output', taskId: bad.taskId,
      stage: 'master-review', retryable: true, message: 'Invalid JSON' } }), { status: 422 });
    return jsonResponse({ document: body.document, complete: true, results: [] });
  };
  try {
    assert.ok(await store.getState().runDesignSystemAi(ds, 'master-review'));
    assert.deepEqual(corrected, ['a', 'b', 'c', 'd']); assert.equal(applies.length, 5);
    assert.ok(applies.every(body => body.responses.length === 4 && body.prepareId === applies[0].prepareId && body.documentHash === applies[0].documentHash));
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('later DS stage failure or cancel retains accepted server document only for still-current inputs', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const change of ['failure', 'invalid-output', 'cancel', 'source', 'document', 'systemId', 'revision']) {
      const { source, ds } = dsFixture(); const before = structuredClone(node(ds).data.document);
      const accepted = { ...before, acceptedStage: 'review' }; const summary = { components: 4 };
      let applies = 0, chats = 0;
      window.designDNA = { providers: { chatRequest: async () => {
        chats++;
        if (chats === 2) {
          if (change === 'cancel') await store.getState().cancelRun(ds);
          if (change === 'source') patch(source, { blocks: [{ name: 'changed', ir: ir('changed') }] });
          if (change === 'document') patch(ds, { document: { ...before, userEdit: true } });
          if (change === 'systemId') patch(ds, { systemId: 'other' });
          if (change === 'revision') patch(ds, { revision: 99 });
          if (change === 'failure') throw new Error('Provider failed in repair');
        }
        return { provider: 'codex', content: '{}' };
      } } };
      globalThis.fetch = async url => {
        if (url.endsWith('/prepare')) return jsonResponse(preparedDs('master-review', 'codex'));
        applies++;
        if (applies > 1) return new Response(JSON.stringify({ detail: { code: 'invalid-ai-output',
          taskId: 'master-review-task', stage: 'master-repair', retryable: true, message: 'Too many repair operations; maximum 12' } }), { status: 422 });
        return jsonResponse({ document: accepted, summary, results: [], complete: false,
          nextPreparation: { ...preparedDs('master-review', 'codex'), prepareId: 'repair-stage', documentHash: 'accepted-hash', stage: 'master-repair' } });
      };
      assert.equal(await store.getState().runDesignSystemAi(ds, 'master-review'), null);
      assert.equal(applies, change === 'invalid-output' ? 3 : 1); assert.equal(chats, change === 'invalid-output' ? 3 : 2);
      if (['failure', 'invalid-output', 'cancel'].includes(change)) {
        assert.deepEqual(node(ds).data.document, accepted); assert.deepEqual(node(ds).data.summary, summary);
        assert.equal(node(ds).data.pipelineStatus['master-review'].status, change === 'cancel' ? 'cancelled' : 'failed');
      } else assert.equal(node(ds).data.document.acceptedStage, undefined);
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('cancellation during DS format correction cancels its chat and never retries apply', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  const { ds } = dsFixture(); const before = structuredClone(node(ds).data.document);
  let started, finish; const correcting = new Promise(resolve => { started = resolve; });
  const canceled = []; let applies = 0;
  window.designDNA = { providers: { cancel: async id => { canceled.push(id); }, chatRequest: request => {
    if (request.id.endsWith(':format-correction')) return new Promise(resolve => { finish = resolve; started(request.id); });
    return Promise.resolve({ provider: 'codex', content: '{"invalid":true' });
  } } };
  globalThis.fetch = async url => {
    if (url.endsWith('/prepare')) return jsonResponse(preparedDs('style-review', 'codex'));
    applies++; return new Response(JSON.stringify({ detail: { code: 'invalid-ai-output', taskId: 'style-review-task', stage: 'style-review', retryable: true, message: 'Invalid JSON' } }), { status: 422 });
  };
  try {
    const running = store.getState().runDesignSystemAi(ds, 'style-review'); const chatId = await correcting;
    await store.getState().cancelRun(ds); finish({ provider: 'codex', content: '{}' });
    assert.equal(await running, null); assert.equal(applies, 1); assert.deepEqual(canceled, [chatId]);
    assert.deepEqual(node(ds).data.document, before); assert.equal(node(ds).data.pipelineStatus['style-review'].status, 'cancelled');
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('DS correction never retries network, stale, pin or unrelated task failures', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const failure of ['network', 'stale', 'pin', 'wrong-task']) {
      const { ds } = dsFixture(); let chats = 0, applies = 0;
      window.designDNA = { providers: { chatRequest: async () => { chats++; return { provider: 'codex', content: '{}' }; } } };
      globalThis.fetch = async url => {
        if (url.endsWith('/prepare')) return jsonResponse(preparedDs('style-review', 'codex'));
        applies++; if (failure === 'network') throw new Error('Network unavailable');
        return new Response(JSON.stringify({ detail: { code: failure === 'wrong-task' ? 'invalid-ai-output' : failure,
          taskId: failure === 'wrong-task' ? 'other-task' : 'style-review-task', stage: 'style-review', retryable: true, message: failure } }), { status: failure === 'stale' ? 409 : 422 });
      };
      assert.equal(await store.getState().runDesignSystemAi(ds, 'style-review'), null); assert.equal(chats, 1); assert.equal(applies, 1);
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('DS API choices retain legacy endpoints; desktop choices cannot silently fall back without a bridge', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    window.designDNA = undefined;
    for (const provider of ['openai', 'astra', 'codex', 'claude']) {
      const { ds } = dsFixture(provider); const calls = [];
      globalThis.fetch = async (url, init) => { const body = JSON.parse(init.body); calls.push({url, body}); return jsonResponse({ document: body.document, summary: {} }); };
      const result = await store.getState().runDesignSystemAi(ds, 'organize');
      if (['codex', 'claude'].includes(provider)) {
        assert.equal(result, null); assert.equal(calls.length, 0); assert.equal(node(ds).data.pipelineStatus.organize.status, 'failed');
      } else { assert.ok(result); assert.equal(calls[0].url, '/api/design-system/organize'); assert.equal(calls[0].body.provider, provider); }
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('DS action hydrates an evicted document after reload before preparing desktop AI', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    const { ds } = dsFixture(); patch(ds, { document: null, revision: 7 }); const calls = [];
    window.designDNA = { providers: { chatRequest: async () => ({ content: '{}', provider: 'codex' }) } };
    globalThis.fetch = async (url, init) => {
      const body = JSON.parse(init.body); calls.push(url);
      if (url.endsWith('/get')) { assert.deepEqual(body, { systemId: 'kit', revision: 7 }); return jsonResponse({ document: { id: 'kit', hydrated: true } }); }
      assert.equal(body.document.hydrated, true);
      if (url.endsWith('/prepare')) return jsonResponse(preparedDs('style-review', 'codex'));
      return jsonResponse({ document: body.document, complete: true, results: [] });
    };
    assert.ok(await store.getState().runDesignSystemAi(ds, 'style-review'));
    assert.deepEqual(calls, ['/api/design-system/get', '/api/design-system/desktop-ai/prepare', '/api/design-system/desktop-ai/apply']);
    assert.equal(node(ds).data.document.hydrated, true);
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('DS stale document, Source changes, deletion and cancellation discard chat before apply/save', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const change of ['document', 'source', 'wire', 'delete', 'cancel']) {
      const { source, ds } = dsFixture(); const calls = []; let finishChat, startedChat;
      const ready = new Promise(resolve => { startedChat = resolve; });
      window.designDNA = { providers: { chatRequest: () => { startedChat(); return new Promise(resolve => { finishChat = resolve; }); }, cancel: async () => ({ cancelled: true }) } };
      globalThis.fetch = async (url) => { calls.push(url); return jsonResponse(preparedDs('organize', 'codex')); };
      const running = store.getState().runDesignSystemAi(ds, 'organize'); await ready;
      if (change === 'document') patch(ds, { document: { id: 'replacement' } });
      if (change === 'source') patch(source, { tokens: { edited: true } });
      if (change === 'wire') store.getState().deleteEdge(store.getState().edges.find(e => Number(e.target) === ds).id);
      if (change === 'delete') store.getState().deleteNode(ds);
      if (change === 'cancel') await store.getState().cancelRun(ds);
      finishChat({ content: '{}', provider: 'codex' });
      assert.equal(await running, null); assert.deepEqual(calls, ['/api/design-system/desktop-ai/prepare'], change);
      if (change === 'document') assert.equal(node(ds).data.document.id, 'replacement');
      if (change !== 'delete') assert.equal(node(ds).data.pipelineStatus.organize.status, 'cancelled');
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('DS cache-miss hydration cannot commit after a systemId or revision-only switch', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const change of [{ systemId: 'other' }, { revision: 9 }]) {
      const { ds } = dsFixture(); patch(ds, { document: null }); let finishLoad; const calls = [];
      globalThis.fetch = url => { calls.push(url); return new Promise(resolve => { finishLoad = resolve; }); };
      const running = store.getState().runDesignSystemAi(ds, 'organize');
      patch(ds, change); finishLoad(jsonResponse({ document: { id: 'kit' } }));
      assert.equal(await running, null); assert.deepEqual(calls, ['/api/design-system/get']);
      assert.equal(node(ds).data.document, null); assert.equal(node(ds).data.pipelineStatus.organize.status, 'cancelled');
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('master tasks run at most two at once, apply deterministic task order and cancel every active chat', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const cancel of [false, true]) {
      const { ds } = dsFixture(); const pending = [], canceled = []; let started; let applied = 0;
      const ready = new Promise(resolve => { started = resolve; });
      window.designDNA = { providers: {
        chatRequest: request => new Promise(resolve => { pending.push({ request, resolve }); if (pending.length === 2) started(); }),
        cancel: async id => { canceled.push(id); return { cancelled: true }; },
      } };
      globalThis.fetch = async (url, init) => {
        if (url.endsWith('/prepare')) return jsonResponse({ ...preparedDs('master-review', 'codex'), tasks: Array.from({ length: 3 }, (_, i) => ({ id: `t${i}`, status: 'ready', messages: [{ role: 'user', content: `prompt${i}` }] })) });
        applied++; const body = JSON.parse(init.body);
        assert.deepEqual(body.responses, [0, 1, 2].map(i => ({ taskId: `t${i}`, output: `output${i}` })));
        return jsonResponse({ document: body.document, results: [], complete: true });
      };
      const running = store.getState().runDesignSystemAi(ds, 'master-review'); await ready;
      assert.equal(pending.length, 2);
      if (cancel) await store.getState().cancelRun(ds);
      pending[1].resolve({ provider: 'codex', content: 'output1' });
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(pending.length, cancel ? 2 : 3, 'a free slot starts the next check without waiting for its slow sibling');
      pending[0].resolve({ provider: 'codex', content: 'output0' });
      if (cancel) {
        assert.equal(await running, null); assert.deepEqual(canceled.sort(), pending.map(p => p.request.id).sort()); assert.equal(applied, 0);
      } else {
        for (let i = 0; i < 15 && pending.length < 3; i++) await Promise.resolve();
        assert.equal(pending.length, 3); pending[2].resolve({ provider: 'codex', content: 'output2' });
        assert.ok(await running); assert.equal(applied, 1);
      }
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('master repair chain applies returned document/hash and only final approval clears rejected quality', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const approved of [true, false]) {
      const { ds } = dsFixture(); patch(ds, { document: { id: 'kit', reviewComponents: { hero: {} } } });
      const calls = []; let round = 0;
      window.designDNA = { providers: { chatRequest: async (request) => {
        assert.equal(request.profile, round === 1 ? 'quality_repair' : 'quality_judge');
        if (round === 1) assert.equal(request.responseFormat, undefined);
        else {
          const schema = request.responseFormat.jsonSchema.schema;
          assert.equal(request.responseFormat.type, 'json_schema');
          assert.equal(schema.additionalProperties, false);
          assert.deepEqual(schema.required, ['approved', 'score', 'summary', 'defects']);
          assert.deepEqual(schema.properties.defects.items.properties.severity.enum, ['minor', 'major', 'critical']);
        }
        return { content: '{}', provider: 'codex' };
      } } };
      globalThis.fetch = async (url, init) => {
        const body = JSON.parse(init.body); calls.push({ url, body });
        if (url.endsWith('/prepare')) return jsonResponse(preparedDs('master-review', 'codex'));
        const kind = ['master-review', 'master-repair', 'master-verify'][round];
        assert.equal(body.documentHash, `hash-${kind}`);
        if (round) assert.equal(body.document.round, round);
        const result = { key: 'hero', kind, ...(round === 1 ? { repaired: false, pendingVerification: true } : { approved: round === 2 && approved, supported: true, summary: 'quality defects' }) };
        round++;
        return jsonResponse({ document: { id: 'kit', round }, results: [result], complete: round === 3,
          nextPreparation: round < 3 ? preparedDs('master-review', 'codex', ['master-repair', 'master-verify'][round - 1]) : null });
      };
      const result = await store.getState().runDesignSystemAi(ds, 'master-review');
      assert.ok(result); assert.equal(round, 3); assert.equal(calls.filter(c => c.url.endsWith('/prepare')).length, 1);
      assert.equal(node(ds).data.pipelineStatus['master-review'].status, approved ? 'success' : 'warning');
      assert.equal(node(ds).data.document.round, 3); assert.equal(result.approved, approved ? 1 : 0);
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('unsupported master evidence still applies empty responses and persists a warning', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    const { ds } = dsFixture(); let chats = 0, applies = 0;
    window.designDNA = { providers: { chatRequest: async () => { chats++; throw new Error('unexpected'); } } };
    globalThis.fetch = async (url, init) => {
      const body = JSON.parse(init.body);
      if (url.endsWith('/prepare')) return jsonResponse({ ...preparedDs('master-review', 'codex'), tasks: [{ id: 'missing', status: 'unsupported', reason: 'missing evidence' }] });
      applies++; assert.deepEqual(body.responses, []);
      return jsonResponse({ document: body.document, results: [{ key: 'hero', kind: 'master-review', supported: false, approved: false }], complete: true });
    };
    assert.ok(await store.getState().runDesignSystemAi(ds, 'master-review'));
    assert.equal(chats, 0); assert.equal(applies, 1); assert.equal(node(ds).data.pipelineStatus['master-review'].status, 'warning');
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('invalid supplied master pins surface one structured input failure before chat or apply', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    const { ds } = dsFixture(); let chats = 0; const calls = [];
    window.designDNA = { providers: { chatRequest: async () => { chats++; throw new Error('unexpected'); } } };
    globalThis.fetch = async url => {
      calls.push(url);
      return jsonResponse({ detail: { code: 'invalid-master-pins', message: 'Invalid immutable Source master pins',
        errors: [{ code: 'master-hash-mismatch', path: 'document.reviewComponents["hero"].sourceRef.masterHash',
          message: 'Observed master differs from its supplied Source hash; restore or rebuild from Source' }] } }, 422);
    };
    assert.equal(await store.getState().runDesignSystemAi(ds, 'master-review'), null);
    assert.equal(chats, 0); assert.deepEqual(calls, ['/api/design-system/desktop-ai/prepare']);
    assert.equal(node(ds).data.pipelineStatus['master-review'].status, 'failed');
    assert.match(node(ds).data.lastError, /restore or rebuild from Source/);
    assert.doesNotMatch(node(ds).data.lastError, /\[object Object\]/);
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('Source AI repair provider failure survives final import and a cached rerun', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    reset(); const source = add('sourceimport'); patch(source, { url: 'https://example.test', mine: true, aiProvider: 'codex' });
    window.designDNA = { providers: { chatRequest: async () => { throw new Error('Codex не подключён'); } } };
    globalThis.fetch = async (url) => {
      if (url === '/api/block-parse') return jsonResponse({ blocks: [{ name: 'hero', selector: 'hero', ir: ir('Captured'), fidelityReport: { gate: { passed: false } } }] });
      assert.equal(url, '/api/block-parse/repair'); return jsonResponse({ tasks: [{ blockIndex: 0, messages: [{ role: 'user', content: 'repair' }] }] });
    };
    await store.getState().runSourceImport(source);
    assert.equal(node(source).data.blocks.length, 1); assert.equal(node(source).data.pipelineStatus.repair.status, 'failed');
    assert.equal(node(source).data.pipelineStatus.fidelity.status, 'warning'); assert.equal(store.getState().statuses[source].kind, 'err');
    assert.match(store.getState().statuses[source].text, /AI-аккаунт/);
    await store.getState().runSourceImport(source);
    assert.equal(store.getState().statuses[source].kind, 'err'); assert.equal(node(source).data.pipelineStatus.repair.status, 'failed');
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});

test('Source repair re-offloads expanded screenshot evidence before committing blocks', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    reset(); const source = add('sourceimport'); patch(source,{url:'https://example.test',mine:true});
    const preview='data:image/png;base64,Y2FwdHVyZQ==';
    const block={name:'header',selector:'header',ir:ir('Captured'),preview,previews:{desktop:preview},fidelityReport:{gate:{passed:false}}};
    let puts=0;
    window.designDNA={blobs:{put:async()=>{puts++;return {name:'a'.repeat(64)+'.png',sha256:'a'.repeat(64)};}},
      providers:{chatRequest:async()=>({content:'{}'})}};
    globalThis.fetch=async (url,init)=>{
      if(url==='/api/block-parse')return jsonResponse({blocks:[structuredClone(block)]});
      assert.equal(url,'/api/block-parse/repair');
      if(JSON.parse(init.body).prepareOnly)return jsonResponse({tasks:[{blockIndex:0,messages:[{role:'user',content:'repair'}]}]});
      return jsonResponse({blocks:[{...block,fidelityReport:{gate:{passed:true}}}],results:[{appliedCount:1}]});
    };
    await store.getState().runSourceImport(source);
    assert.equal(puts,2,'initial capture and the expanded repair result must both be persisted');
    assert.equal(node(source).data.blocks[0].previews.desktop,'ddna://blobs/'+'a'.repeat(64)+'.png');
  } finally {globalThis.fetch=previousFetch;window.designDNA=desktop;}
});

test('source reimport preserves artifact wire and clears editors whose block disappeared', async () => {
  reset(); const source = add('sourceimport'), ds = add('designsystem'), edit = add('edit');
  patch(source, { url: 'https://example.test', mine: true, blocks: [{ name: 'hero', lit: true, ir: ir('Old') }], sourceArtifact: { version: 'source-artifact/1.0' } });
  connect(source, 'artifact', ds, 'artifact'); connect(source, 'hero', edit, 'a');
  assert.ok(node(edit).data.ir);
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ blocks: [{ name: 'footer', ir: ir('New') }], sourceArtifact: { version: 'source-artifact/1.0' } }), { status: 200 });
  try { await store.getState().runSourceImport(source); } finally { globalThis.fetch = previousFetch; }
  assert.ok(store.getState().edges.some(e => Number(e.target) === ds));
  assert.equal(node(edit).data.ir, null);
  assert.equal(node(ds).data.sourceNodeId, source);
});

test('DS catalog creation and rebuild never start AI even with an active provider', async () => {
  reset(); const source = add('sourceimport');
  const sourceIR = ir('Exact Source');
  patch(source, { url: 'https://example.test', blocks: [{ name: 'hero', ir: sourceIR }] });
  const savedFetch = globalThis.fetch, bridge = window.designDNA;
  const originalFinish = store.getState().finishDesignSystem;
  const document = { id: 'instant-kit', name: 'Kit', reviewComponents: { hero: { masterIr: sourceIR } } };
  let requests = 0;
  globalThis.fetch = async url => {
    assert.equal(url, '/api/design-system/build'); requests++;
    return new Response(JSON.stringify({ document, summary: { components: 0, reviewMasters: 1 } }));
  };
  window.designDNA = { providers: { chatRequest: () => assert.fail('No AI during catalog build') } };
  store.setState({ finishDesignSystem: () => assert.fail('No automatic full pipeline') });
  try {
    const ds = await store.getState().createDesignSystemFromSource(source);
    assert.ok(ds); assert.equal(node(ds).data.pipelineStatus.build.status, 'success');
    assert.deepEqual(node(ds).data.document.reviewComponents.hero.masterIr, sourceIR);
    assert.equal(await store.getState().rebuildDesignSystemFromSource(ds), true);
    assert.equal(requests, 2); assert.equal(store.getState().busy[ds], false);
  } finally { globalThis.fetch = savedFetch; window.designDNA = bridge; store.setState({ finishDesignSystem: originalFinish }); }
});

test('review component working copies preserve exact selected variant and fonts without publication or a registry pin', () => {
  reset(); const ds = add('designsystem');
  const master = { ...ir('Default'), meta: { fontFaces: [{ family: 'Source', url: '/fonts/a.woff2' }] } };
  const variant = { ...ir('Actual selected variant'), meta: master.meta };
  const document = { id: 'kit', components: {}, reviewComponents: { card: { origin: 'observed', masterIr: master,
    variants: { alt: { masterIr: variant }, default: { masterRef: 'self' } } } } };
  patch(ds, { systemId: 'kit', document }); const before = JSON.stringify(node(ds).data.document);
  const edit = store.getState().copyDesignSystemComponentToEditor(ds, 'card', 'review', 'alt');
  assert.ok(edit); assert.deepEqual(node(edit).data.ir, variant);
  assert.equal(node(edit).data._dsMaster, undefined);
  assert.equal(JSON.stringify(node(ds).data.document), before);
  assert.equal(store.getState().copyDesignSystemComponentToEditor(ds, 'card', 'review', 'missing'), null);
});

test('failed UI Kit creation keeps the connected node and readable error for retry', async () => {
  reset(); const source = add('sourceimport');
  patch(source, { blocks: [{ ir: ir('Source') }] });
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Captured asset unavailable' }), { status: 422 });
  try {
    assert.equal(await store.getState().createDesignSystemFromSource(source), null);
    const ds = store.getState().nodes.find(n => n.type === 'designsystem');
    assert.ok(ds); assert.equal(ds.data.lastError, 'Captured asset unavailable');
    assert.equal(store.getState().busy[ds.id], false);
    assert.ok(store.getState().edges.some(e => e.target === ds.id));
  } finally { globalThis.fetch = previousFetch; }
});

test('DS build uses the current wire, resets published metadata and ignores viewport-only updates', async () => {
  reset(); const oldSource = add('sourceimport'), source = add('sourceimport'), ds = add('designsystem');
  patch(source, { url: 'https://example.test/new', blocks: [{ name: 'hero', lit: true, ir: ir('New') }] });
  patch(ds, { sourceNodeId: oldSource, revision: 7, contentHash: 'old', defaultSet: true,
    pipelineStatus: { organize: { status: 'failed' }, 'style-review': { status: 'success' }, 'master-review': { status: 'running' }, fidelity: { status: 'warning' } } });
  connect(source, 'artifact', ds, 'artifact');
  assert.equal(node(ds).data.sourceNodeId, source);
  let request;
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    assert.equal(node(ds).data.pipelineStatus.build.status, 'running');
    request = JSON.parse(options.body);
    return new Response(JSON.stringify({ document: { id: 'new-ds', name: 'New', foundations: { primary: '#123456' } }, summary: { components: 1 } }));
  };
  try { assert.equal(await store.getState().rebuildDesignSystemFromSource(ds), true); } finally { globalThis.fetch = previousFetch; }
  assert.equal(String(request.sourceNodeId), String(source));
  assert.equal(node(ds).data.revision, 0); assert.equal(node(ds).data.contentHash, '');
  assert.equal(node(ds).data.defaultSet, false);
  assert.equal(node(ds).data.pipelineStatus.build.status, 'success');
  for (const stage of ['organize', 'style-review', 'master-review']) assert.equal(node(ds).data.pipelineStatus[stage].status, 'skipped');
  assert.equal(node(ds).data.pipelineStatus.fidelity.status, 'warning');
  patch(source, { activeViewport: 'mobile' }); store.getState().propagate(source);
  assert.equal(node(ds).data.sourceUpdate, false);
  const reloaded = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  const reloadedDs = reloaded.nodes.find(n => Number(n.id) === ds);
  assert.equal(reloadedDs.data._sourceFingerprint, node(ds).data._sourceFingerprint);
  assert.equal(reloadedDs.data.sourceUpdate, false);
  assert.equal(reloadedDs.data.document, null);
  assert.equal(reloadedDs.data.pipelineStatus.build.status, 'success');
  patch(source, { tokens: { color: { primary: '#abcdef' } } }); store.getState().propagate(source);
  assert.equal(node(ds).data.sourceUpdate, true);
  store.getState().deleteEdge(store.getState().edges.find(e => Number(e.target) === ds).id);
  assert.equal(node(ds).data.sourceNodeId, null);
  assert.equal(await store.getState().rebuildDesignSystemFromSource(ds), false);
  assert.equal(node(ds).data.pipelineStatus.build.status, 'failed');
});

test('DS build persists actionable structured failures without invalidating the unchanged document AI stages', async () => {
  const { ds } = dsFixture();
  patch(ds, { pipelineStatus: { organize: { status: 'success' } } });
  const before = structuredClone(node(ds).data.document);
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: 'invalid_source', message: 'Reimport Source',
    errors: [{ path: 'blocks.0.ir', message: 'Invalid canonical IR' }] } }), { status: 422 });
  try {
    assert.equal(await store.getState().rebuildDesignSystemFromSource(ds), false);
    assert.equal(node(ds).data.pipelineStatus.build.status, 'failed');
    assert.match(node(ds).data.lastError, /Reimport Source.*Invalid canonical IR.*blocks.0.ir/);
    assert.doesNotMatch(node(ds).data.lastError, /\[object Object\]/);
    assert.equal(node(ds).data.pipelineStatus.organize.status, 'success');
    assert.deepEqual(node(ds).data.document, before);
  } finally { globalThis.fetch = previousFetch; }
});

test('cancelled DS build does not apply its result and persists cancellation', async () => {
  const { ds } = dsFixture();
  const before = structuredClone(node(ds).data.document);
  let finish;
  const previousFetch = globalThis.fetch;
  globalThis.fetch = () => new Promise(resolve => { finish = resolve; });
  try {
    const pending = store.getState().rebuildDesignSystemFromSource(ds);
    await store.getState().cancelRun(ds);
    finish(new Response(JSON.stringify({ document: { id: 'kit', name: 'obsolete' } })));
    assert.equal(await pending, false);
    assert.equal(node(ds).data.pipelineStatus.build.status, 'cancelled');
    assert.equal(store.getState().busy[ds], false);
    assert.deepEqual(node(ds).data.document, before);
  } finally { globalThis.fetch = previousFetch; }
});

test('multi-input DNA editor carries the source viewport into its composed IR', () => {
  reset(); const source = add('sourceimport'), edit = add('edit');
  const captured = (text) => ({ ...ir(text), tree: [{ id: text, type: 'source-block', variant: 'dom-capture', children: [] }] });
  patch(source, { activeViewport: 'mobile', blocks: [
    { name: 'hero', lit: true, ir: captured('hero') }, { name: 'footer', lit: true, ir: captured('footer') },
  ] });
  connect(source, 'hero', edit, 'a'); connect(source, 'footer', edit, 'b');
  assert.equal(node(edit).data.ir.meta.activeViewport, 'mobile');
  assert.equal(node(edit).data.ir.responsive.viewports.mobile.width, 390);
});

test('a delayed DS build cannot overwrite a newly connected source', async () => {
  reset(); const a = add('sourceimport'), b = add('sourceimport'), ds = add('designsystem');
  for (const id of [a, b]) patch(id, { blocks: [{ name: 'hero', lit: true, ir: ir(String(id)) }] });
  connect(a, 'artifact', ds, 'artifact');
  const previousFetch = globalThis.fetch;
  let finish;
  globalThis.fetch = () => new Promise(resolve => { finish = resolve; });
  try {
    const pending = store.getState().rebuildDesignSystemFromSource(ds);
    connect(b, 'artifact', ds, 'artifact');
    finish(new Response(JSON.stringify({ document: { id: 'obsolete', name: 'Old' }, summary: {} })));
    assert.equal(await pending, false);
    assert.equal(node(ds).data.systemId, null);
    assert.equal(node(ds).data.sourceNodeId, b);
    assert.match(node(ds).data.lastError, /Source/);
    assert.equal(node(ds).data.pipelineStatus.build.status, 'cancelled');
  } finally { globalThis.fetch = previousFetch; }
});

test('composing source blocks retains their font definitions after an isolated reload', () => {
  reset(); const source = add('sourceimport'), edit = add('edit');
  const face = { family: 'Source Font', src: 'https://example.test/font.woff2', weight: '400' };
  const captured = (text) => ({ ...ir(text), meta: { fontFaces: [face] } });
  patch(source, { blocks: [{ name: 'hero', lit: true, ir: captured('Hero') }, { name: 'footer', lit: true, ir: captured('Footer') }] });
  connect(source, 'hero', edit, 'a'); connect(source, 'footer', edit, 'b');
  assert.deepEqual(node(edit).data.ir.meta.fontFaces, [face]);
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  assert.deepEqual(restored.nodes.find(n => Number(n.id) === edit).data.ir.meta.fontFaces, [face]);
});

test('published DS tokens survive document-cache eviction and graph save/load', async () => {
  reset(); const ds = add('designsystem');
  const tokens = { color: { primary: '#123456' } };
  const document = { id: 'ds-test', name: 'Kit', revision: 2, styleGuide: { irTokens: tokens } };
  patch(ds, { systemId: document.id, document });
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url) => new Response(JSON.stringify(String(url).includes('/publish')
    ? { document, summary: {} } : { systems: [], defaultSystemRef: null }));
  try { assert.equal(await store.getState().publishDesignSystem(ds), true); } finally { globalThis.fetch = previousFetch; }
  assert.equal(node(ds).data.document, null);
  assert.deepEqual(outValue(node(ds), 'tokens'), tokens);
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  assert.deepEqual(outValue(restored.nodes[0], 'tokens'), tokens);
});

test('all registered node types have unique ports and survive save/load with their defaults', () => {
  reset();
  assert.ok(Object.hasOwn(NODE_DEFS, 'image') && Object.hasOwn(NODE_DEFS, 'removebackground'));
  for (const type of Object.keys(NODE_DEFS)) {
    const id = add(type);
    for (const ports of Object.values(portsOfNode(node(id)))) {
      assert.equal(new Set(ports.map(p => p.name)).size, ports.length, type);
      for (const port of ports) assert.ok(port.kinds.includes(port.kind), type);
    }
  }
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  assert.equal(restored.nodes.length, Object.keys(NODE_DEFS).length);
  for (const n of restored.nodes) assert.deepEqual(n.data, defaultData(n.type), n.type);
});

test('connections reject cycles, wrong kinds and missing ports; one input has one wire', () => {
  reset(); const a = add('edit'), b = add('edit'), prompt = add('prompt'), c = add('edit');
  patch(a, { ir: ir('A') }); patch(c, { ir: ir('C') });
  assert.ok(connect(a, 'ir', b, 'a'));
  assert.equal(connect(b, 'ir', a, 'a'), false);
  assert.equal(connect(prompt, 'out', b, 'a'), false);
  assert.equal(connect(a, 'missing', b, 'a'), false);
  assert.ok(connect(c, 'ir', b, 'a'));
  assert.equal(store.getState().edges.length, 1);
});

test('disconnect and delete clear editor/timeline input and stale video downstream; undo restores', () => {
  reset(); const a = add('generator'), b = add('edit'), c = add('timeline'), d = add('motiondesign');
  patch(a, { variants: [ir('A')], active: 0 });
  connect(a, 'ir', b, 'a'); connect(b, 'ir', c, 'ir'); connect(c, 'video', d, 'video');
  patch(c, { timeline: { composition: {}, layers: [] }, renderJob: { status: 'complete', id: 'render', downloadUrl: '/clip.mp4' } });
  store.getState().propagate(c);
  assert.ok(node(d).data.sourceVideo);
  store.getState().deleteNode(a);
  assert.equal(node(b).data.ir, null); assert.equal(node(c).data.ir, null);
  assert.equal(outValue(node(c), 'video'), null); assert.equal(node(d).data.sourceVideo, null);
  assert.ok(store.getState().undoGraph()); assert.ok(node(b).data.ir);
  const e = store.getState().edges.find(e => Number(e.target) === b);
  store.getState().deleteEdge(e.id); assert.equal(node(b).data.ir, null); assert.equal(node(c).data.ir, null);
});

test('diamond propagation uses both updated branches; unchanged propagation preserves editor revision', () => {
  reset(); const a = add('generator'), b = add('edit'), c = add('edit'), d = add('edit'), e = add('edit');
  patch(a, { variants: [ir('Before')], active: 0 });
  connect(a,'ir',b,'a'); connect(a,'ir',c,'a'); connect(b,'ir',d,'a'); connect(c,'ir',d,'b'); connect(d,'ir',e,'a');
  patch(a, { variants: [ir('After')], active: 0 }); store.getState().propagate(a);
  assert.ok(!JSON.stringify(node(e).data.ir).includes('Before'));
  const revision = store.getState().getNodeIrRevision(e);
  store.getState().propagate(a);
  assert.equal(store.getState().getNodeIrRevision(e), revision);
  assert.ok(store.getState().commitEditorDraft(e, revision, ir('User edit')));
  assert.equal(store.getState().commitEditorDraft(e, revision, ir('Stale edit')), false);
  assert.ok(JSON.stringify(node(e).data.ir).includes('User edit'));
});

test('partial older nodes recover nested defaults; duplicate IDs and bad imported edges cannot corrupt graph', () => {
  const payload = parseLegacyPayload({ nodes: [
    { id: 1, type: 'timeline', data: { settings: { fps: 60 } } },
    { id: 2, type: 'edit', data: {} },
    { id: 3, type: 'edit', data: {} },
  ], edges: [
    { from: { node: 2, port: 'ir' }, to: { node: 3, port: 'a' } },
    { from: { node: 3, port: 'ir' }, to: { node: 2, port: 'a' } },
    { from: { node: 1, port: 'video' }, to: { node: 2, port: 'b' } },
    { from: { node: 2, port: 'missing' }, to: { node: 1, port: 'ir' } },
  ] });
  const loaded = payloadToRf(payload);
  assert.deepEqual(loaded.nodes[0].data.settings, { width: 1920, height: 1080, fps: 60, duration: 8000 });
  assert.deepEqual(loaded.nodes[1].data.inputs, ['a', 'b']);
  assert.equal(loaded.edges.length, 1);
  assert.throws(() => parseLegacyPayload({ nodes: [{id:1,type:'edit'}, {id:1,type:'prompt'}] }), /ID/);
});

test('timeline commits update settings and downstream document, invalidate video and reject stale drafts', () => {
  reset(); const a = add('timeline'), b = add('motiondesign');
  patch(a, { ir: ir('A') }); connect(a,'timeline',b,'timeline');
  const revision = store.getState().getNodeIrRevision(a);
  const doc = { composition: { width:1080,height:1920,fps:60,duration:2000 }, layers:[] };
  patch(a, { renderJob: { status: 'complete', id:'old', downloadUrl:'/old.mp4' } });
  assert.ok(store.getState().commitTimeline(a,null,revision,doc));
  assert.deepEqual(node(b).data.sourceTimeline,doc);
  assert.equal(node(a).data.settings.fps,60);
  assert.equal(outValue(node(a),'video'),null);
  assert.equal(store.getState().commitTimeline(a,null,revision,doc),false);
  patch(a,{ir:ir('B')});
  assert.equal(store.getState().commitTimeline(a,doc,revision,doc),false);
});

const { resizeTimeline, moveTimelineKey, setTimelineKeyValue } = await bundle('editor/timeline-edits');
const { IRHistory } = await bundle('engine/irhistory');
const timeline = () => ({version:'timeline-ir/1.0',composition:{width:1920,height:1080,fps:30,duration:4000},groups:[],layers:[{
  id:'hero',type:'component',ref:'hero',in:0,out:4000,
  transform:{anchor:{x:0,y:0},properties:{opacity:{keyframes:[{t:0,value:0,easing:'linear'},{t:4000,value:1,easing:'linear'}]}}}
}]});

test('duration trim samples the cut point and removes out-of-range keys; expanding restores full-length clip', () => {
  const doc = timeline(); resizeTimeline(doc, 2000);
  assert.equal(doc.layers[0].out,2000);
  assert.deepEqual(doc.layers[0].transform.properties.opacity.keyframes.at(-1),{t:2000,value:0.5,easing:'linear'});
  resizeTimeline(doc,6000); assert.equal(doc.layers[0].out,6000);
  const saved = JSON.stringify(doc); resizeTimeline(doc,NaN); assert.equal(JSON.stringify(doc),saved);
});

test('drag cannot cross or collide with adjacent keys, including fractional frame positions', () => {
  const doc = timeline();
  assert.equal(moveTimelineKey(doc,'hero','opacity',0,4000),3999);
  assert.equal(moveTimelineKey(doc,'hero','opacity',3999,33.333333),33);
  assert.equal(moveTimelineKey(doc,'hero','opacity',33,-500),0);
  assert.equal(moveTimelineKey(doc,'hero','opacity',0,NaN),0);
});

test('DNA history retains redo when a locked/invalid operation is cancelled', () => {
  const history=IRHistory.createHistory({coalesceMs:0}); let doc={text:'before'};
  history.push(()=>doc); doc={text:'after'};
  doc=history.undo(()=>doc); assert.equal(doc.text,'before');
  history.push(()=>doc); history.cancelLast();
  assert.ok(history.canRedo()); doc=history.redo(()=>doc); assert.equal(doc.text,'after');
});

const { compositionFrame } = await bundle('nodes/motion-composition');
test('Motion preview/export share layer values, scene boundaries and empty compositions', () => {
  const layer={id:'title',sceneId:'s1',type:'text',text:'Edited title',props:{p:{keys:[{t:0,v:[0,0]},{t:1000,v:[100,200]}]},s:{keys:[]},r:{keys:[]},o:{keys:[{t:0,v:0},{t:1000,v:1}]}}};
  const data={motion:{scenes:[{id:'s1',interactionSceneId:'i1',start:0,duration:2000,transition:{type:'cut',duration:0,easing:'linear'}},{id:'s2',interactionSceneId:'i2',start:2000,duration:1000,transition:{type:'cut',duration:0,easing:'linear'}}]},sceneSettings:{}};
  const frame=compositionFrame(data,[layer],500)[0];
  assert.equal(frame.layer.text,'Edited title'); assert.deepEqual(frame.values,{p:[50,100],s:1,r:0,o:0.5});
  assert.deepEqual(compositionFrame(data,[layer],2000),[]);
  assert.deepEqual(compositionFrame(data,[],500),[]);
});


test('keyframe numeric values edit animation with opacity/scale bounds', () => {
  const doc=timeline();
  setTimelineKeyValue(doc,'hero','opacity',0,0.7);
  assert.equal(doc.layers[0].transform.properties.opacity.keyframes[0].value,0.7);
  setTimelineKeyValue(doc,'hero','opacity',0,20);
  assert.equal(doc.layers[0].transform.properties.opacity.keyframes[0].value,1);
  setTimelineKeyValue(doc,'hero','opacity',0,NaN);
  assert.equal(doc.layers[0].transform.properties.opacity.keyframes[0].value,1);
});

test('a delayed timeline build cannot restore an obsolete input', async () => {
  reset(); const id=add('timeline'); patch(id,{ir:ir('Before')});
  const originalFetch=globalThis.fetch; let resolve;
  globalThis.fetch=()=>new Promise(r=>resolve=r);
  try {
    const running=store.getState().runTimeline(id);
    patch(id,{ir:ir('After'),timeline:null});
    resolve({ok:true,json:async()=>({timeline:timeline()})});
    await running;
    assert.equal(node(id).data.timeline,null);
    assert.ok(JSON.stringify(node(id).data.ir).includes('After'));
    assert.equal(store.getState().busy[id],false);
  } finally { globalThis.fetch=originalFetch; }
});

test('Motion transitions blend both scenes and live duration settings update the composition', () => {
  const props={p:{keys:[{t:0,v:[50,50]}]},s:{keys:[]},r:{keys:[]},o:{keys:[]}};
  const data={motion:{scenes:[
    {id:'one',interactionSceneId:'a',start:0,duration:1000,transition:{type:'cut',duration:0,easing:'linear'}},
    {id:'two',interactionSceneId:'b',start:1000,duration:1000,transition:{type:'fade',duration:200,easing:'linear'}},
  ]},composition:{width:100,height:100},sceneSettings:{}};
  const layers=[{id:'a',sceneId:'one',props},{id:'b',sceneId:'two',props}];
  assert.deepEqual(compositionFrame(data,layers,1100).map(f=>f.values.o),[0.5,0.5]);
  data.sceneSettings.a={duration:2000};
  assert.deepEqual(compositionFrame(data,layers,1100).map(f=>f.layer.id),['a']);
  assert.deepEqual(compositionFrame(data,layers,2100).map(f=>f.values.o),[0.5,0.5]);
});

test('manual DNA edits survive unrelated wiring and repeated upstream propagation', () => {
  reset(); const a=add('generator'), b=add('edit');
  patch(a,{variants:[ir('Source')],active:0}); connect(a,'ir',b,'a');
  const revision=store.getState().getNodeIrRevision(b);
  assert.ok(store.getState().commitEditorDraft(b,revision,ir('User composition')));
  const c=add('timeline'); connect(a,'ir',c,'ir');
  assert.ok(JSON.stringify(node(b).data.ir).includes('User composition'));
  const saved=payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  store.setState(saved); store.getState().propagate(a);
  assert.ok(JSON.stringify(node(b).data.ir).includes('User composition'));
  patch(a,{variants:[ir('New source')],active:0}); store.getState().propagate(a);
  assert.ok(JSON.stringify(node(b).data.ir).includes('New source'));
});

test('canvas deletion retains refreshed downstream data; removing an editor port is undoable', () => {
  reset(); const a=add('generator'),b=add('edit');
  patch(a,{variants:[ir('Source')],active:0}); connect(a,'ir',b,'a');
  store.getState().removeEditInput(b,'a'); assert.equal(node(b).data.ir,null);
  store.getState().undoGraph(); assert.ok(node(b).data.inputs.includes('a')); assert.ok(node(b).data.ir);
  const oldNodes=store.getState().nodes;
  store.getState().syncFromCanvas(oldNodes.filter(n=>Number(n.id)!==a),[]);
  assert.equal(node(b).data.ir,null);
});

test('run-based nodes report empty/invalid input without leaving a busy state or throwing', async () => {
  const originalFetch=globalThis.fetch;
  globalThis.fetch=async()=>({ok:false,status:422,json:async()=>({error:'Подключите входные данные'})});
  try {
    for (const [type,action] of [
      ['generator','runGenerator'],['mix','runMix'],['page','runPage'],['sourceimport','runSourceImport'],
      ['derive','runDerive'],['reskin','runReskin'],['qualitypass','runQualityPass'],['recorder','runRecorder'],
      ['motion','runMotion'],['timeline','runTimeline'],['motiondesign','planMotionDesign'],['pagebridge','runPageBridge'],
    ]) {
      reset(); const id=add(type);
      await store.getState()[action](id);
      assert.ok(!store.getState().busy[id],type);
      assert.equal(store.getState().statuses[id]?.kind,'err',type);
    }
  } finally { globalThis.fetch=originalFetch; }
});

test('finished Motion/Timeline videos survive save-load; running jobs do not resume as phantom busy jobs', () => {
  reset();
  for (const type of ['motion','timeline']) {
    const id=add(type); patch(id,{renderJob:{id:'a'.repeat(32),status:'complete',downloadUrl:'/saved.mp4'}});
  }
  const loaded=payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  for (const n of loaded.nodes) assert.equal(outValue(n,'video').downloadUrl,'/saved.mp4');
  patch(1,{renderJob:{id:'pending',status:'rendering'}});
  const pending=payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  assert.equal(pending.nodes[0].data.renderJob,null);
});


test('finish DS resumes failed stages and publishes after one complete successful review/repair/verify cycle', async () => {
  const { ds } = dsFixture('openai');
  patch(ds, { autoPublish: true, pipelineStatus: { organize: { status: 'success' }, 'style-review': { status: 'failed' } } });
  const originalRun = store.getState().runDesignSystemAi, originalPublish = store.getState().publishDesignSystem;
  const calls = [];
  store.setState({ runDesignSystemAi: async (id, operation) => {
    calls.push(operation);
    const approved = true;
    patch(id, { pipelineStatus: { ...node(id).data.pipelineStatus, [operation]: { status: approved ? 'success' : 'warning' } },
      summary: { reviewMasters: approved ? 0 : 1 }, document: { id: 'kit', reviewComponents: approved ? {} : { hero: {} } } });
    return { document: node(id).data.document, results: [{ key: 'hero', approved, supported: true }] };
  }, publishDesignSystem: async () => { calls.push('publish'); return true; } });
  try {
    assert.equal(await store.getState().finishDesignSystem(ds), true);
    assert.deepEqual(calls, ['style-review', 'master-review', 'publish']);
    assert.equal(node(ds).data._dsFinishing, null);
  } finally { store.setState({ runDesignSystemAi: originalRun, publishDesignSystem: originalPublish }); }
});

test('finish DS stops on cancellation, missing evidence or bounded failed verification without publication', async () => {
  const originalRun = store.getState().runDesignSystemAi, originalPublish = store.getState().publishDesignSystem;
  try {
    for (const failure of ['cancel', 'unsupported', 'rejected', 'source-change']) {
      const { source, ds } = dsFixture(); let reviews = 0, published = 0;
      patch(ds, { autoPublish: true });
      store.setState({ runDesignSystemAi: async (id, operation) => {
        if (operation === 'master-review') {
          reviews++;
          if (failure === 'cancel') return null;
          if (failure === 'source-change') patch(source, { blocks: [] });
        }
        patch(id, { pipelineStatus: { ...node(id).data.pipelineStatus, [operation]: { status: operation === 'master-review' ? 'warning' : 'success' } } });
        return { document: node(id).data.document, results: [{ key: 'hero', approved: false, supported: failure !== 'unsupported' }] };
      }, publishDesignSystem: async () => { published++; return true; } });
      assert.equal(await store.getState().finishDesignSystem(ds), false, failure);
      assert.equal(reviews, 1, 'never repeat unchanged rejected masters after a completed repair/verify cycle');
      assert.equal(published, 0, failure);
      assert.equal(node(ds).data._dsFinishing, null);
    }
  } finally { store.setState({ runDesignSystemAi: originalRun, publishDesignSystem: originalPublish }); }
});


test('explicit finish rebuilds changed Source then completes review and publication', async () => {
  const { ds } = dsFixture(); patch(ds, { sourceUpdate: true, autoPublish: true });
  const { rebuildDesignSystemFromSource, runDesignSystemAi, publishDesignSystem } = store.getState();
  const calls = [];
  store.setState({
    rebuildDesignSystemFromSource: async id => { calls.push('build'); patch(id, { sourceUpdate: false }); return true; },
    runDesignSystemAi: async (id, operation) => {
      calls.push(operation);
      patch(id, { pipelineStatus: { ...node(id).data.pipelineStatus, [operation]: { status: 'success' } } });
      return { document: node(id).data.document };
    },
    publishDesignSystem: async () => { calls.push('publish'); return true; },
  });
  try {
    assert.equal(await store.getState().finishDesignSystem(ds), true);
    assert.deepEqual(calls, ['build', 'organize', 'style-review', 'master-review', 'publish']);
    patch(ds, { sourceUpdate: true }); calls.length = 0;
    store.setState({ rebuildDesignSystemFromSource: async () => { calls.push('failed-build'); return false; } });
    assert.equal(await store.getState().finishDesignSystem(ds), false);
    assert.deepEqual(calls, ['failed-build']);
  } finally { store.setState({ rebuildDesignSystemFromSource, runDesignSystemAi, publishDesignSystem }); }
});


test('finish DS recovers retryable AI output failure from the saved checkpoint', async () => {
  const { ds } = dsFixture(); const originalRun = store.getState().runDesignSystemAi;
  let reviews = 0;
  store.setState({ runDesignSystemAi: async (id, operation) => {
    if (operation === 'master-review' && ++reviews === 1) {
      patch(id, { _dsAiRetryable: true, pipelineStatus: { ...node(id).data.pipelineStatus, [operation]: { status: 'failed' } } });
      return null;
    }
    patch(id, { _dsAiRetryable: false, pipelineStatus: { ...node(id).data.pipelineStatus, [operation]: { status: 'success' } }, summary: { reviewMasters: 0 } });
    return { document: node(id).data.document };
  } });
  try { assert.equal(await store.getState().finishDesignSystem(ds), true); assert.equal(reviews, 2); }
  finally { store.setState({ runDesignSystemAi: originalRun }); }
});


test('desktop DS retries a transient connection reset once with a new cancellable id', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  const { ds } = dsFixture('openai'); const requests = [];
  window.designDNA = { providers: { chatRequest: async request => {
    requests.push(request);
    if (requests.length === 1) throw new Error('ECONNRESET');
    return { content: '{}', provider: 'codex', transport: { requestedProvider: 'openai' } };
  } } };
  globalThis.fetch = async (url, init) => url.endsWith('/prepare') ? jsonResponse(preparedDs('style-review', 'openai'))
    : jsonResponse({ document: JSON.parse(init.body).document, complete: true });
  try {
    assert.ok(await store.getState().runDesignSystemAi(ds, 'style-review'));
    assert.equal(requests.length, 2); assert.notEqual(requests[0].id, requests[1].id);
    assert.equal(requests[0].model, requests[1].model); assert.deepEqual(requests[0].messages, requests[1].messages);
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});


test('desktop DS bounds transient retries and never retries authentication failures', async () => {
  const previousFetch = globalThis.fetch, desktop = window.designDNA;
  try {
    for (const [message, expected] of [['Codex generator timed out', 1], ['ECONNRESET', 2], ['OpenAI API key missing', 1]]) {
      const { ds } = dsFixture('openai'); let calls = 0, applies = 0;
      window.designDNA = { providers: { chatRequest: async () => { calls++; throw new Error(message); } } };
      globalThis.fetch = async url => { if (url.endsWith('/prepare')) return jsonResponse(preparedDs('style-review', 'openai')); applies++; throw new Error('must not apply'); };
      assert.equal(await store.getState().runDesignSystemAi(ds, 'style-review'), null);
      assert.equal(calls, expected); assert.equal(applies, 0);
    }
  } finally { globalThis.fetch = previousFetch; window.designDNA = desktop; }
});


test('UI Kit handoff wires the exact draft and survives saving without replacing other generators', () => {
  const { ds } = dsFixture('claude');
  patch(ds, { status: 'draft', revision: 0 });
  const otherDs = add('designsystem'); patch(otherDs, { systemId: 'kit' });
  const unrelated = add('generator'); patch(unrelated, { prompt: 'Keep my work', provider: 'openai' });
  connect(otherDs, 'system', unrelated, 'designSystem');
  const picker = JSON.stringify(store.getState().designSystemPicker);
  const document = JSON.stringify(node(ds).data.document);
  const target = store.getState().sendDesignSystemToGenerator(ds);
  assert.ok(target && target !== unrelated);
  assert.equal(node(target).selected, true);
  assert.equal(node(target).data.provider, 'claude');
  const edge = store.getState().edges.find(e => e.target === String(target) && e.targetHandle === 'designSystem');
  assert.equal(edge.source, String(ds)); assert.equal(edge.sourceHandle, 'system');
  const ref = outValue(node(ds), 'system');
  assert.equal(ref.status, 'draft'); assert.equal(ref.nodeId, ds); assert.equal(ref.systemId, 'kit');
  assert.equal(store.getState().sendDesignSystemToGenerator(ds), target, 'repeat focuses the already connected generator');
  assert.equal(store.getState().nodes.filter(n => n.type === 'generator').length, 2);
  assert.equal(node(unrelated).data.prompt, 'Keep my work');
  assert.equal(JSON.stringify(store.getState().designSystemPicker), picker);
  assert.equal(JSON.stringify(node(ds).data.document), document);
  assert.ok(!store.getState().busy[target], 'handoff never starts generation');
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  assert.ok(restored.edges.some(e => e.source === String(ds) && e.target === String(target) && e.targetHandle === 'designSystem'));
  assert.equal(store.getState().sendDesignSystemToGenerator(999999), null);
});


test('handoff focus waits for node measurement and ignores a stale page', async () => {
  const { setReactFlowInstance, focusFlowNode } = await bundle('flow/graphdev');
  const calls = []; let measurements = 0;
  const savedTimeout = globalThis.setTimeout; globalThis.setTimeout = realTimeout;
  setReactFlowInstance({
    getNodes: () => [{ id: 'target', measured: ++measurements > 1 ? { width: 322, height: 440 } : {} }],
    fitView: options => { calls.push(options); },
  });
  try {
    assert.equal(await focusFlowNode('target', () => true), true);
    assert.equal(measurements, 2);
    assert.deepEqual(calls[0].nodes, [{ id: 'target' }]);
    assert.equal(calls[0].maxZoom, 1);
    assert.equal(await focusFlowNode('target', () => false), false);
    assert.equal(calls.length, 1, 'stale focus cannot move another page');
  } finally { setReactFlowInstance(null); globalThis.setTimeout = savedTimeout; }
});
