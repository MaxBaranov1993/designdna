import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
const ts=createRequire(import.meta.url)('typescript');
const source=readFileSync(new URL('../src/nodes/designSystemStatus.ts',import.meta.url),'utf8');
const ctx={exports:{}};
runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx);
const status=ctx.exports.designSystemIdleStatus;
test('saved DS warnings cannot become generic ready after restart',()=>{
  assert.equal(status({systemId:'kit',pipelineStatus:{review:{status:'warning'}}}).text,'Нужно ревью');
  assert.equal(status({systemId:'kit',summary:{reviewMasters:6}}).text,'UI Kit собран · 6 требуют проверки');
  assert.equal(status({systemId:'kit',summary:{reviewMasters:6}}).kind,null);
  assert.equal(status({systemId:'kit',pipelineStatus:{review:{status:'failed'}}}).text,'Ошибка проверки');
  assert.equal(status({systemId:'kit',pipelineStatus:{review:{status:'cancelled'}}}).text,'Не завершено');
});
test('unreviewed drafts are labelled drafts, not AI success',()=>{
  assert.equal(status({systemId:'kit',pipelineStatus:{review:{status:'skipped'}}}).text,'Черновик');
  assert.equal(status({systemId:'kit',status:'published'}).text,'Опубликовано');
  assert.equal(status({systemId:'kit',sourceUpdate:true}).text,'Source изменён');
  assert.equal(status({}),undefined);
});
test('node shell retains runtime progress and DS exposes full diagnostics on demand',()=>{
  const shell=readFileSync(new URL('../src/nodes/NodeShell.svelte',import.meta.url),'utf8');
  const node=readFileSync(new URL('../src/nodes/DesignSystemNode.svelte',import.meta.url),'utf8');
  assert.match(shell,/!busy && idleStatus/);
  assert.match(node,/idleStatus=\{designSystemIdleStatus\(data\)\}/);
  assert.match(node,/<details class="ds-error nodrag" data-ds-pipeline-stage/);
});
