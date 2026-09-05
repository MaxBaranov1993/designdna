import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
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
  buildSync({ entryPoints: [new URL('../src/' + file + '.ts', import.meta.url).pathname], bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent' });
  return import(pathToFileURL(out));
};
const { useFlowStore: store } = await bundle('flow/store');
const { NODE_DEFS, portsOfNode, defaultData } = await bundle('flow/ports');
const { parseLegacyPayload, payloadToRf, buildSavePayload } = await bundle('flow/serialize');
const { outValue } = await bundle('flow/dataflow');
after(() => rmSync(dir, { recursive: true, force: true }));
const ir = (text) => ({ version: '1.1', frame: { width: 1440 }, tree: [{ id: 'hero', type: 'hero', variant: 'center', props: { heading: text } }] });
const reset = () => store.setState({ nodes: [], edges: [], nextId: 1, statuses: {}, busy: {}, graphHistory: { past: [], future: [] } });
const add = (type) => store.getState().addNode(type, 0, 0).id;
const patch = (id, data) => store.getState().setNodeData(id, data);
const node = (id) => store.getState().nodes.find(n => Number(n.id) === id);
const connect = (a, ap, b, bp) => store.getState().connect({ node: a, port: ap }, { node: b, port: bp });

test('all 17 node types have unique ports and survive save/load with their defaults', () => {
  reset();
  assert.equal(Object.keys(NODE_DEFS).length, 17);
  for (const type of Object.keys(NODE_DEFS)) {
    const id = add(type);
    for (const ports of Object.values(portsOfNode(node(id)))) {
      assert.equal(new Set(ports.map(p => p.name)).size, ports.length, type);
      for (const port of ports) assert.ok(port.kinds.includes(port.kind), type);
    }
  }
  const restored = payloadToRf(parseLegacyPayload(buildSavePayload(store.getState())));
  assert.equal(restored.nodes.length, 17);
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
