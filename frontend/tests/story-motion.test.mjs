import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
const {buildSync}=createRequire(import.meta.url)('esbuild');
const dir=mkdtempSync(join(tmpdir(),'story-motion-'));
const outfile=join(dir,'motion.mjs');
buildSync({entryPoints:[fileURLToPath(new URL('../src/engine/story-motion.ts',import.meta.url))],bundle:true,platform:'node',format:'esm',outfile,logLevel:'silent'});
const {motionEase,softenStory}=await import(pathToFileURL(outfile));
after(()=>rmSync(dir,{recursive:true,force:true}));
test('motion starts and stops at rest, stays monotone and reaches exact destinations',()=>{
  const h=.0001;
  assert.ok(motionEase(h)/h < .00001);
  assert.ok((1-motionEase(1-h))/h < .00001);
  for(const mode of ['soft','ease-in','ease-out','linear']) {
    assert.equal(motionEase(0,mode),0);assert.equal(motionEase(1,mode),1);
    let before=0;
    for(let i=0;i<=1000;i++){const v=motionEase(i/1000,mode);assert.ok(v>=before-1e-12&&v<=1);before=v;}
  }
  assert.ok(motionEase(.2)<.1);assert.ok(motionEase(.8)>.9);
});
test('softening preserves content and long manual timings; repeated use does not slow it again',()=>{
  const story={pages:[{id:'ir',name:'Form',ir:{tree:[]}}],initialPageId:'ir',actions:[
    {id:'a',type:'move',pageId:'ir',target:'s0',duration:300},
    {id:'b',type:'type',pageId:'ir',target:'s0.children.0',text:'Ручной текст',duration:5000},
    {id:'c',type:'navigate',pageId:'ir',toPageId:'done',transition:'cut',duration:500}]};
  const before=structuredClone(story),soft=softenStory(story);
  assert.deepEqual(story,before);assert.deepEqual(soft.pages,story.pages);
  assert.equal(soft.actions[1].duration,5000);assert.equal(soft.actions[1].text,'Ручной текст');
  assert.equal(soft.actions[0].duration,900);assert.equal(soft.actions[2].transition,'motion');
  assert.deepEqual(softenStory(soft),soft);
  assert.deepEqual(soft.actions.map(a=>a.id),story.actions.map(a=>a.id));
});
