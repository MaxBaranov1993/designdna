import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const { buildSync } = createRequire(import.meta.url)('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'desktop-fetch-cancel-'));
const outfile = join(dir,'bridge.mjs');
buildSync({entryPoints:[fileURLToPath(new URL('../src/desktop/bridge.ts',import.meta.url))],bundle:true,format:'esm',platform:'node',outfile,logLevel:'silent'});
const {installDesktopFetchBridge}=await import(pathToFileURL(outfile));
after(()=>rmSync(dir,{recursive:true,force:true}));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('AbortSignal addresses exactly one IPC request and suppresses its late response', async () => {
  const requests=[], cancels=[];
  globalThis.window={fetch:globalThis.fetch,designDNA:{api:{
    request: payload=>new Promise(resolve=>requests.push({payload,resolve})),
    cancel:async (_scope,id)=>cancels.push(id),
  }}};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{sendBeacon:()=>true}});
  installDesktopFetchBridge();
  const controller=new AbortController();
  const a=window.fetch('/api/generate',{method:'POST',body:'{}',signal:controller.signal});
  const b=window.fetch('/api/generate',{method:'POST',body:'{}'});
  await tick();assert.equal(requests.length,2);
  assert.notEqual(requests[0].payload.requestId,requests[1].payload.requestId);
  const cancelled=assert.rejects(a,{name:'AbortError'});controller.abort();await cancelled;
  assert.deepEqual(cancels,[requests[0].payload.requestId]);
  const result={status:200,headers:{},body:'{"ok":true}',encoding:'utf8'};
  requests[1].resolve(result);assert.deepEqual(await (await b).json(),{ok:true});
  requests[0].resolve(result);await tick();
  const already=new AbortController();already.abort();
  await assert.rejects(window.fetch('/api/config',{signal:already.signal}),{name:'AbortError'});
  assert.equal(requests.length,2,'pre-aborted requests are not dispatched');
});

test('Request init overrides the original signal and cancellation after completion sends nothing',async()=>{
  const requests=[],cancels=[];
  globalThis.window={fetch:globalThis.fetch,designDNA:{api:{request:async p=>{requests.push(p);return {status:200,headers:{},body:'{}',encoding:'utf8'};},cancel:async(_,id)=>cancels.push(id)}}};
  installDesktopFetchBridge();
  const old=new AbortController();old.abort();const current=new AbortController();
  const input=new Request('http://designdna.local/api/config',{signal:old.signal});
  assert.equal((await window.fetch(input,{signal:current.signal})).status,200);
  current.abort();await tick();assert.equal(cancels.length,0);assert.equal(requests.length,1);
});
