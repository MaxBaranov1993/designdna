import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
const ts = createRequire(import.meta.url)('typescript');
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
function functions(source, names) {
  const ast = ts.createSourceFile('test.ts', source, ts.ScriptTarget.Latest, true);
  const found = new Map();
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) found.set(node.name.text, node.getText(ast));
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.equal(found.size, names.length);
  return ts.transpileModule([...found.values()].join('\n'), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
}
const clone = value => JSON.parse(JSON.stringify(value));

test('responsive Source style save preserves every sibling and strips only renderer metadata', () => {
  const source = read('../src/editor/controller.ts');
  const names = ['deepClone','sourceNodeMap','syncSharedStructure','syncActiveIR','copyWithoutRenderMetadata'];
  const original = {responsive:{viewports:{desktop:{width:600,height:72},mobile:{width:390,height:72}}},
    tree:[{type:'card',sourceKey:'root',frame:{width:600,height:72},children:[
      {type:'text',sourceKey:'label',text:'https://',style:{borderWidth:0,borderRadius:0},responsive:{mobile:{visible:false}}},
      {type:'input',sourceKey:'input',children:[{type:'text',sourceKey:'value',text:'yourcompany.com'}]},
    ]}]};
  const state = {ir:clone(original),activeIR:clone(original),viewport:'desktop'};
  state.ir.tree[0].children[0].__path = 'children.0';
  state.activeIR.tree[0].children[0].__path = 'children.0';
  state.activeIR.tree[0].children[0].style.background = '#123abc';
  const ctx = {state,manualSourceKey:0};
  runInNewContext(functions(read('../src/engine/responsiveContent.ts').replace('export function', 'function'),['syncResponsiveContent']),ctx);
  runInNewContext(functions(source,names)+'\nsyncActiveIR(); result=copyWithoutRenderMetadata(state.ir);',ctx);
  const expected=clone(original);
  expected.tree[0].children[0].style.background='#123abc';
  assert.deepEqual(clone(ctx.result),expected);
  assert.equal(state.ir.tree[0].children[0].__path,'children.0','save cleaning must not mutate the live editor');
});

test('text background edits retain measured borders, shadow, fill and untouched sibling', () => {
  const node={type:'text',fill:'#fff',style:{borderWidth:0,borderRadius:0,borderColor:'#333',boxShadow:'none'}};
  const sibling={type:'text',text:'untouched',style:{color:'#123'}};
  const before=clone(sibling);
  const ctx={selections:[{ref:'selected'}],styleSessionUntil:0,onCommit(){},refuseLocked:()=>false,
    irNodeAt:()=>node,onMutated(){},node};
  runInNewContext(functions(read('../src/engine/geoedit.ts'),['setNodeStyle'])+"\nsetNodeStyle({background:'#123abc'});",ctx);
  assert.deepEqual(clone(node),{type:'text',fill:'#fff',style:{borderWidth:0,borderRadius:0,borderColor:'#333',boxShadow:'none',background:'#123abc'}});
  assert.deepEqual(sibling,before);
});

test('Source fidelity display supports measured percentages and legacy fractions without false zero', () => {
  const source=read('../src/editor/SourceArtifactPanel.svelte');
  const snippet=source.slice(source.indexOf('const percent ='),source.indexOf('const dimension ='));
  const js=ts.transpileModule(snippet,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const ctx={}; runInNewContext(js+'\nformat=percent;',ctx);
  for(const [input,expected] of [[96.55,'97%'],[0.9655,'97%'],[null,'—'],[undefined,'—'],['','—'],[0,'0%'],[NaN,'—'],[101,'—']])
    assert.equal(ctx.format(input),expected);
});
