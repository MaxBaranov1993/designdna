import assert from 'node:assert/strict';
import { test as nodeTest, after } from 'node:test';
const test = (name, run) => nodeTest(name, { timeout: 10000 }, run);
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
  buildSync({ stdin: { contents: `export * from ${JSON.stringify(fileURLToPath(new URL('../src/flow/store.ts', import.meta.url)))}; export {commitNodeText} from ${JSON.stringify(fileURLToPath(new URL('../src/flow/textcommit.ts', import.meta.url)))};`, resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts' }, bundle: true, format: 'esm', platform: 'node', outfile: output, logLevel: 'silent' });
  return import(pathToFileURL(output));
}
const { useFlowStore: store, commitNodeText, captureNodeUpload } = await bundle('flow/store');
after(() => { for (const file of files) unlinkSync(file); rmdirSync(dir); });
const resultIr = {version: '1.1', tree: [{type:'composition', children:[{type:'text',text:'Current result'}]}]};
const response = value => new Response(JSON.stringify(value), {status: 200});
function reset() {
 window.designDNA = undefined;
 store.getState().loadGraph({ nodes:[], edges:[], nextId:1 });
 store.setState({pages:[{id:'A',name:'A',nodes:[],edges:[],nextId:1,view:{x:0,y:0,zoom:1}}],pageRuntimes:{},activePageId:'A',statuses:{},statusLog:{},busy:{},designSystemPicker:null});
}
const add = type => store.getState().addNode(type,0,0).id;
const patch = (id,data) => store.getState().setNodeData(id,data);
const node = id => store.getState().nodes.find(n=>Number(n.id)===id);
const tick = () => new Promise(resolve=>setImmediate(resolve));

test('Design System import publishes only review-free documents with autoPublish enabled', async () => {
 for (const scenario of [
  {reviewMasters:0, autoPublish:true, expected:'published'},
  {reviewMasters:1, autoPublish:true, expected:'draft'},
  {reviewMasters:0, autoPublish:false, expected:'draft'},
 ]) {
  reset();
  const id = add('designsystem');
  patch(id, {autoPublish:scenario.autoPublish});
  const document = {id:'import-test', name:'Tokens', components:{}, tokens:{color:{primary:'#123456'}}};
  let publishes = 0;
  globalThis.fetch = async path => {
   if (path === '/api/design-system/import') return response({document, format:'w3c', summary:{components:0, reviewMasters:scenario.reviewMasters}});
   if (path === '/api/design-system/publish') {
    publishes++;
    return response({document:{...document, revision:1, contentHash:'published-hash'}, summary:{components:0}});
   }
   if (path === '/api/design-system/list') return response({systems:[]});
   throw new Error(`Unexpected request: ${path}`);
  };
  assert.equal(await store.getState().importDesignSystemDocument(id, {color:{primary:'#123456'}}, 'tokens.json'), true);
  assert.equal(node(id).data.status, scenario.expected);
  assert.equal(publishes, scenario.expected === 'published' ? 1 : 0);
 }
});

function setup() {
 reset(); const prompt=add('prompt'), id=add('generator');
 patch(prompt,{text:'Marketplace header'}); patch(id,{count:1,provider:'claude'});
 store.getState().connect({node:prompt,port:'out'},{node:id,port:'prompt'});
 return {prompt,id};
}

test('generator resumes draft review before publishing and preserves the specific failure', async () => {
 const finish = store.getState().finishDesignSystem;
 const publish = store.getState().publishDesignSystem;
 try {
  for (const approved of [false, true]) {
   const {id} = setup(); const calls = mock(); const ds = add('designsystem');
   patch(ds, {systemId:'kit', status:'draft', summary:{reviewMasters:43}, lastError:'old publication error'});
   store.getState().connect({node:ds,port:'system'},{node:id,port:'designSystem'});
   const stages = [];
   store.setState({finishDesignSystem:async dsId => {
    assert.equal(dsId,ds); stages.push('review');
    patch(ds,{lastError:approved?'':'Missing desktop screenshot; refresh Source'});
    return approved;
   },publishDesignSystem:async () => {
    stages.push('publish'); patch(ds,{status:'published',revision:1,contentHash:'pin'}); return true;
   }});
   await store.getState().runGenerator(id);
   assert.deepEqual(stages,approved?['review','publish']:['review']);
   if (!approved) {
    assert.match(store.getState().statuses[id].text,/Missing desktop screenshot/);
    assert.equal(calls.length,0);
   } else assert.equal(node(id).data.variants.length,1,'generation continues after successful review and publication');
  }
 } finally {store.setState({finishDesignSystem:finish,publishDesignSystem:publish});}
});
function mock() {
 const calls=[];
 window.designDNA={providers:{chatRequest:async request=>{calls.push(['chat',request]); return {content:'{}'};},cancel:async id=>calls.push(['cancel',id])}};
 globalThis.fetch=async (path,options)=>{
  const body=JSON.parse(options.body); calls.push([path,body]);
  if(path==='/api/generate') return response(body.prepareOnly?{preparedContextId:'receipt',prompts:[{messages:[{role:'user',content:body.brief}]}]}:{variants:[structuredClone(resultIr)]});
  if(path==='/api/quality-pass/codex-step') return response({ir:structuredClone(resultIr),scorecard:{overall:91,issues:[{problem:'Current comment'}]},passed:true});
  return response({});
 };
 return calls;
}

test('current prompt and receipt reach finalize; prior review is cleared before the new run',async()=>{
 const {id}=setup(); const calls=mock();
 patch(id,{qualityReviews:[{score:0,reasons:['Old pipes comment']}],variants:[{tree:[]}]});
 const task=store.getState().runGenerator(id);
 assert.deepEqual(node(id).data.qualityReviews,[]);
 await task;
 assert.equal(calls.find(c=>c[0]==='chat')[1].messages[0].content,'Marketplace header');
 assert.equal(calls.filter(c=>c[0]==='/api/generate').at(-1)[1].preparedContextId,'receipt');
 assert.equal(node(id).data.generationContext.brief,'Marketplace header');
 assert.deepEqual(node(id).data.qualityReviews[0].reasons,['Current comment']);
});

test('generation finishes in its original sheet, including after returning before completion',async()=>{
 for(const returnToA of [false,true]) {
  const {id}=setup(); mock(); let resolve;
  window.designDNA.providers.chatRequest=()=>new Promise(r=>resolve=r);
  const pending=store.getState().runGenerator(id); await tick();
  store.getState().createPage('B'); const b=store.getState().activePageId;
  add('prompt'); const other=add('generator'); patch(other,{ownPrompt:'Sheet B',variants:[{tag:'B'}]});
  if(returnToA) store.getState().switchPage('A');
  resolve({content:'{}'}); await pending;
  if(returnToA) {
   assert.equal(node(id).data.variants.length,1);
   assert.equal(store.getState().busy[id],false);
   store.getState().switchPage(b);
  } else assert.equal(store.getState().statuses[id],undefined);
  assert.equal(node(other).data.variants[0].tag,'B');
  store.getState().switchPage('A');
  assert.equal(node(id).data.variants.length,1);
  assert.equal(store.getState().busy[id],false);
  assert.equal(store.getState().statuses[id].kind,'ok');
 }
});

test('changed wired prompt prevents finalization and QP for the previous prompt',async()=>{
 const {id,prompt}=setup(); const calls=mock(); let resolve;
 window.designDNA.providers.chatRequest=()=>new Promise(r=>resolve=r);
 const pending=store.getState().runGenerator(id); await tick();
 patch(prompt,{text:'Different task'}); resolve({content:'{}'}); await pending;
 assert.equal(node(id).data.variants.length,0);
 assert.match(store.getState().statuses[id].text,/Входные данные изменились/);
 assert.equal(calls.filter(c=>c[0]==='/api/generate').length,1);
});

test('cancel during judge interrupts that request and cannot start repair',async()=>{
 const {id}=setup(); const calls=mock(); let resolve;
 const base=globalThis.fetch;
 globalThis.fetch=async(path,options)=>path==='/api/quality-pass/codex-step'?response({pending:{stage:'judge',profile:'quality_judge',messages:[]}}):base(path,options);
 window.designDNA.providers.chatRequest=async request=>{
  calls.push(['chat',request]); if(request.profile==='quality_judge')return new Promise(r=>resolve=r);
  return {content:'{}'};
 };
 const pending=store.getState().runGenerator(id); await tick();
 assert.ok(resolve); await store.getState().cancelRun(id); resolve({content:'{}'}); await pending;
 assert.equal(calls.filter(c=>c[0]==='chat').length,2);
 assert.ok(calls.some(c=>c[0]==='cancel'&&c[1]===calls.filter(c=>c[0]==='chat').at(-1)[1].id));
 assert.deepEqual(node(id).data.qualityReviews,[]);
});

test('delayed Mix result and runtime journal stay in their sheet',async()=>{
 reset(); const a=add('generator'), b=add('generator'), id=add('mix');
 patch(a,{variants:[resultIr]}); patch(b,{variants:[resultIr]}); patch(id,{variants:1});
 store.getState().connect({node:a,port:'ir'},{node:id,port:'a'});
 store.getState().connect({node:b,port:'ir'},{node:id,port:'b'});
 let resolve; globalThis.fetch=(path)=>path.includes('/api/runs/')?Promise.resolve(response({})):new Promise(r=>resolve=r);
 const pending=store.getState().runMix(id);
 store.getState().createPage('B');
 assert.deepEqual(store.getState().statusLog,{});
 resolve(response({ir:resultIr})); await pending;
 assert.equal(store.getState().nodes.length,0); assert.deepEqual(store.getState().statuses,{});
});

test('pending text is flushed into original sheet before switching with duplicate node ids',()=>{
 reset(); const id=add('prompt');
 commitNodeText('prompt:'+id+':text',()=>patch(id,{text:'Final keystroke'}),10000);
 store.getState().createPage('B'); const other=add('prompt'); patch(other,{text:'Sheet B'});
 assert.equal(store.getState().pages.find(p=>p.id==='A').nodes[0].data.text,'Final keystroke');
 assert.equal(node(other).data.text,'Sheet B');
});

test('stale canvas snapshot cannot move or remove nodes on another sheet',()=>{
 reset(); add('prompt'); const original=store.getState().nodes;
 store.getState().createPage('B'); const id=add('generator');
 store.getState().syncFromCanvas(original,[],'A');
 assert.equal(node(id).type,'generator');
});


for (const type of ['derive', 'reskin', 'qualitypass']) {
 test(`late ${type} response cannot modify an identically numbered node on another sheet`,async()=>{
  reset(); const source=add('generator'), id=add(type); patch(source,{variants:[resultIr]});
  if(type==='derive') patch(id,{prompt:'Header',count:1});
  else store.getState().connect({node:source,port:'ir'},{node:id,port:'ir'});
  let resolve; globalThis.fetch=(path)=>path.includes('/api/runs/')?Promise.resolve(response({})):new Promise(r=>resolve=r);
  const method={derive:'runDerive',reskin:'runReskin',qualitypass:'runQualityPass'}[type];
  const task=store.getState()[method](id); assert.ok(resolve,'operation started');
  store.getState().createPage('B'); add('prompt'); const other=add(type); patch(other,{prompt:'Sheet B'});
  const before=structuredClone(node(other).data);
  resolve(response({variants:[resultIr],ir:resultIr})); await task;
  assert.deepEqual(node(other).data,before); assert.deepEqual(store.getState().statuses,{});
 });
}

test('deleting and recreating a node with the same id rejects its old generation',async()=>{
 const {id}=setup(); mock(); let resolve;
 window.designDNA.providers.chatRequest=()=>new Promise(r=>resolve=r);
 const task=store.getState().runGenerator(id); await tick();
 store.getState().deleteNode(id); store.setState({nextId:id}); const other=add('generator');
 patch(other,{ownPrompt:'Replacement'}); resolve({content:'{}'}); await task;
 assert.equal(node(other).data.ownPrompt,'Replacement'); assert.equal(node(other).data.variants.length,0);
});

for (const type of ['mix', 'derive', 'reskin', 'qualitypass', 'recorder']) {
 test(`changed ${type} inputs discard the old response on the same sheet`,async()=>{
  reset(); const a=add('generator'), b=add('generator'), id=add(type);
  patch(a,{variants:[resultIr]}); patch(b,{variants:[resultIr]});
  if(type==='mix') {
   patch(id,{variants:1});
   store.getState().connect({node:a,port:'ir'},{node:id,port:'a'});
   store.getState().connect({node:b,port:'ir'},{node:id,port:'b'});
  } else if(type==='derive') patch(id,{prompt:'Original brief',count:1});
  else store.getState().connect({node:a,port:'ir'},{node:id,port:'ir'});
  let resolve; globalThis.fetch=(path)=>path.includes('/api/runs/')?Promise.resolve(response({})):new Promise(r=>resolve=r);
  const method={mix:'runMix',derive:'runDerive',reskin:'runReskin',qualitypass:'runQualityPass',recorder:'runRecorder'}[type];
  const task=store.getState()[method](id); assert.ok(resolve);
  if(type==='derive') patch(id,{prompt:'Changed brief'});
  else patch(a,{variants:[{...resultIr,meta:{revision:'changed'}}]});
  const before=structuredClone(node(id).data);
  resolve(response({variants:[resultIr],ir:resultIr,interaction:{version:'interaction-ir/1.0',events:[]}})); await task;
  assert.deepEqual(node(id).data,before); assert.equal(store.getState().busy[id],false);
 });
}

test('file uploads keep their original node and newest selection across async reads',()=>{
 reset(); const id=add('reference');
 const first=captureNodeUpload(id), newest=captureNodeUpload(id);
 assert.equal(newest({image:'new.png',fileName:'new.png'}),true);
 assert.equal(first({image:'old.png'}),false); assert.equal(node(id).data.image,'new.png');
 const pending=captureNodeUpload(id);
 store.getState().createPage('B'); const other=add('reference');
 assert.equal(pending({image:'original-sheet.png'}),true); assert.equal(node(other).data.image,null);
 const b=store.getState().activePageId;
 store.getState().switchPage('A'); assert.equal(node(id).data.image,'original-sheet.png');
 store.getState().switchPage(b);
 const removed=captureNodeUpload(other); store.getState().deleteNode(other);
 store.setState({nextId:other}); add('reference');
 assert.equal(removed({image:'deleted.png'}),false); assert.equal(node(other).data.image,null);
});

test('Motion Design planning continues on its own sheet after navigation',async()=>{
 reset(); const id=add('motiondesign');patch(id,{prompt:'Camera move',planner:'claude'});
 let resolve,submitted=0;
 window.designDNA={providers:{chatRequest:()=>new Promise(r=>resolve=r)}};
 globalThis.fetch=async path=>{ if(path.includes('/submit')) submitted++; return response({configured:false}); };
 const pending=store.getState().runMotionDesign(id,true);assert.ok(resolve);
 store.getState().createPage('B');resolve({content:'Camera move'});
 await assert.doesNotReject(pending);assert.equal(submitted,0);
 store.getState().switchPage('A'); assert.equal(node(id).data.plannedPrompt,'Camera move');
});

test('two generators with identical IDs finish out of order in the background and keep both results', async () => {
 const {id} = setup(); mock(); const answers = new Map();
 window.designDNA.providers.chatRequest = request => new Promise(resolve => answers.set(request.messages[0].content, resolve));
 const base = globalThis.fetch;
 globalThis.fetch = async (path, options) => {
  const body = JSON.parse(options.body || '{}');
  if (path === '/api/generate' && !body.prepareOnly) return response({variants:[{...resultIr,tag:body.brief}]});
  if (path === '/api/quality-pass/codex-step') return response({ir:body.ir,passed:true});
  return base(path, options);
 };
 const a = store.getState().runGenerator(id); await tick();
 store.getState().setView({x:123,y:456,zoom:0.75});
 store.getState().createPage('B'); const pageB = store.getState().activePageId;
 add('prompt'); const other = add('generator'); assert.equal(other,id);
 patch(other,{ownPrompt:'B task',count:1});
 const b = store.getState().runGenerator(other); await tick();
 store.getState().createPage('C');
 answers.get('B task')({content:'{}'}); await b;
 assert.equal(store.getState().nodes.length,0);
 answers.get('Marketplace header')({content:'{}'}); await a;
 assert.deepEqual(store.getState().busy,{});
 store.getState().switchPage(pageB);
 assert.equal(node(id).data.variants[0].tag,'B task'); assert.equal(store.getState().busy[id],false);
 store.getState().switchPage('A');
 assert.equal(node(id).data.variants[0].tag,'Marketplace header');
 assert.deepEqual(store.getState().view,{x:123,y:456,zoom:0.75});
 assert.equal(store.getState().busy[id],false);
});

test('cancelling one sheet and deleting an idle sheet leave the other generator running', async () => {
 const {id}=setup(); const calls=mock(); const answers=[];
 window.designDNA.providers.chatRequest=request=>new Promise(resolve=>answers.push({request,resolve}));
 const a=store.getState().runGenerator(id);await tick();
 store.getState().createPage('B'); const pageB=store.getState().activePageId;
 add('prompt');add('generator');patch(id,{ownPrompt:'B task',count:1});
 const b=store.getState().runGenerator(id);await tick();
 store.getState().createPage('temporary');const pageC=store.getState().activePageId;
 store.getState().switchPage(pageB);store.getState().deletePage(pageC);
 assert.equal(store.getState().busy[id],true);
 await store.getState().cancelRun(id);
 assert.deepEqual(calls.filter(c=>c[0]==='cancel').map(c=>c[1]),[answers[1].request.id]);
 answers[1].resolve({content:'{}'});await b;
 store.getState().switchPage('A');assert.equal(store.getState().busy[id],true);
 answers[0].resolve({content:'{}'});await a;
 assert.equal(node(id).data.variants.length,1);assert.equal(store.getState().statuses[id].kind,'ok');
 store.getState().switchPage(pageB);assert.equal(node(id).data.variants.length,0);
});

test('Source Import completes on the hidden sheet and never modifies a same-numbered Source', async () => {
 reset();const id=add('sourceimport');patch(id,{url:'https://example.com/a',mine:true,aiRefine:false,autoFidelityRepair:false});
 let resolve;
 globalThis.fetch=()=>new Promise(r=>resolve=r);
 const a=store.getState().runSourceImport(id);
 store.getState().createPage('B');add('sourceimport');patch(id,{url:'https://example.com/b'});
 resolve(response({blocks:[{name:'header',selector:'header',ir:resultIr,lit:true}],tokens:{},url:'https://example.com/a'}));
 await a; assert.equal(node(id).data.blocks.length,0);assert.equal(node(id).data.url,'https://example.com/b');
 store.getState().switchPage('A');assert.equal(node(id).data.blocks.length,1);assert.equal(store.getState().busy[id],false);
});

test('undoing creation cancels that node and redo cannot revive its stale response',async()=>{
 reset();mock();const id=add('generator');patch(id,{ownPrompt:'Undo test',count:1});
 let resolve;window.designDNA.providers.chatRequest=()=>new Promise(r=>resolve=r);
 const task=store.getState().runGenerator(id);await tick();
 assert.equal(store.getState().undoGraph(),true);assert.equal(node(id),undefined);
 assert.equal(store.getState().redoGraph(),true);
 resolve({content:'{}'});await task;
 assert.equal(node(id).data.variants.length,0);assert.equal(store.getState().busy[id],false);
});

test('quality pass repeats repair rounds until the server accepts the result',async()=>{
 const {id}=setup(); const calls=mock();
 const base=globalThis.fetch;
 globalThis.fetch=async(path,options)=>{
  if(path!=='/api/quality-pass/codex-step') return base(path,options);
  const outputs=JSON.parse(options.body).outputs||{};
  calls.push(['qp',structuredClone(outputs)]);
  if(!outputs.judge) return response({pending:{stage:'judge',profile:'quality_judge',messages:[]}});
  const repairs=outputs.repairs||[], rejudges=outputs.rejudges||[];
  if(repairs.length===rejudges.length&&repairs.length<2) return response({pending:{stage:'repair',profile:'quality_repair',round:repairs.length+1,messages:[]}});
  if(rejudges.length<repairs.length) return response({pending:{stage:'rejudge',profile:'quality_judge',round:repairs.length,messages:[]}});
  return response({ir:structuredClone(resultIr),scorecard:{score:84,issues:[]},passed:true,repair:{applied:true,rounds:[{score:70},{score:84}]}});
 };
 window.designDNA.providers.chatRequest=async request=>{calls.push(['chat',request]); return {content:`answer:${request.profile}`};};
 await store.getState().runGenerator(id);
 const profiles=calls.filter(c=>c[0]==='chat').map(c=>c[1].profile);
 assert.deepEqual(profiles.filter(Boolean),['quality_judge','quality_repair','quality_judge','quality_repair','quality_judge']);
 const last=calls.filter(c=>c[0]==='qp').at(-1)[1];
 assert.equal(last.repairs.length,2); assert.equal(last.rejudges.length,2);
 assert.equal(node(id).data.qualityScores[0],84);
 assert.equal(store.getState().statuses[id].kind,'ok');
});

test('unfixed remarks end as a warning with the result kept, not an error',async()=>{
 const {id}=setup(); mock();
 const base=globalThis.fetch;
 globalThis.fetch=async(path,options)=>path==='/api/quality-pass/codex-step'
  ?response({ir:structuredClone(resultIr),scorecard:{score:61,issues:[{problem:'Кнопка сливается с фоном'}]},passed:false,repair:{applied:true,rounds:[{score:55},{score:61}]}})
  :base(path,options);
 await store.getState().runGenerator(id);
 assert.equal(node(id).data.variants.length,1);
 assert.equal(store.getState().statuses[id].kind,'warn');
 assert.match(store.getState().statuses[id].text,/Готово с замечаниями.*Кнопка сливается/);
});
