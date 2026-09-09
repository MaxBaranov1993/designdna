import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
const ts = createRequire(import.meta.url)('typescript');
const ctx = {exports:{}};
runInNewContext(ts.transpileModule(readFileSync(new URL('../src/flow/desktop-ai-queue.ts',import.meta.url),'utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,ctx);
const run = ctx.exports.runDesktopAiQueue;
const tick = () => new Promise(resolve=>setImmediate(resolve));

test('21 checks refill slots, keep concurrency bounded and execute each task exactly once', async () => {
  const pending = new Map(), started=[], finished=[];
  let active=0,maxActive=0;
  const result=run(Array.from({length:21},(_,i)=>i),2,async (item,index)=>{
    assert.equal(item,index);started.push(item);maxActive=Math.max(maxActive,++active);
    await new Promise(resolve=>pending.set(item,resolve));
    active--;finished.push(item);
  });
  assert.deepEqual(started,[0,1]);
  for(let i=1;i<21;i++) {
    pending.get(i)();await tick();
    if(i<20)assert.equal(started.at(-1),i+1,'task 0 must not block the other slot');
  }
  assert.equal(active,1);pending.get(0)();await result;
  assert.equal(maxActive,2);assert.equal(new Set(finished).size,21);
});

test('failure stops queued work even when the in-flight sibling completes later',async()=>{
  let fail,complete;
  const started=[];
  const result=run([0,1,2,3],2,item=>{started.push(item);return new Promise((resolve,reject)=>{
    if(item===0)fail=reject;else complete=resolve;
  });});
  const rejected=assert.rejects(result,/provider unavailable/);
  fail(new Error('provider unavailable'));await rejected;
  complete();await tick();assert.deepEqual(started,[0,1]);
});
