import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
const ts = createRequire(import.meta.url)('typescript');
const context = { exports: {} };
const file = p => readFileSync(new URL(p, import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(file('../src/editor/ui-kit-model.ts'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, context);
const { kitColors, kitFonts, kitConcept, capturedFontUrl } = context.exports;
const plain = v => JSON.parse(JSON.stringify(v));

test('kit presentation preserves distinct color roles, exact values and captured font faces', () => {
  const faces = [{ family: 'Source Sans', url: '/fonts/abc.woff2', weight: '400', unicodeRange: 'U+0-FF' }];
  const component = { masterIr: { meta: { fontFaces: faces } }, variants: {
    another: { masterIr: { meta: { fontFaces: [...faces, { ...faces[0], weight: '700' }] } } },
  } };
  const doc = { foundations: { colors: { semantic: { primary: '#AABBCC', secondary: '#AABBCC', border: '#aabbcd' } },
    typography: { families: ['Source Sans'], body: { family: 'Source Sans' } } } };
  const before = JSON.stringify({ doc, component });
  assert.equal(kitColors(doc).length, 3, 'equal colors can have different semantic roles');
  assert.equal(kitColors(doc)[0].value, '#AABBCC');
  const fonts = kitFonts(doc, [{ key: 'card', pool: 'review', component }]);
  assert.equal(fonts[0].faces.length, 2);
  assert.equal(fonts[0].role, 'Основной текст');
  assert.equal(JSON.stringify({ doc, component }), before);
});

test('missing conceptual evidence stays empty and external fonts are not guessed or downloaded', () => {
  assert.deepEqual(plain(kitConcept({})), { summary: '', traits: [], doRules: [], dontRules: [], hasAnalysis: false });
  assert.equal(capturedFontUrl('/fonts/a.woff2', true), 'ddna://fonts/a.woff2');
  for (const url of ['https://fonts.example/a.woff2', 'file:///private.ttf', '/fonts/../../private.ttf', 'javascript:bad()']) {
    assert.equal(capturedFontUrl(url, true), null);
  }
});

test('catalog preview preserves source fonts, tokens and responsive child geometry without mutating the master', () => {
  const ctx = {exports:{}};
  runInNewContext(ts.transpileModule(file('../src/engine/componentMaster.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, ctx);
  const master = { version: '1.1', meta: { fontFaces: [{ family: 'Exact Face', url: '/fonts/abc.woff2' }] },
    tokens: { font: 'Exact Face' }, tree: [{ type: 'card', frame: { x: 30, y: 20, width: 400, height: 200 },
      responsive: { mobile: { frame: { x: 4, y: 10, width: 300, height: 250 } } },
      children: [{ type: 'text', frame: { x: 12, y: 18 }, text: 'Source' }] }] };
  const before = JSON.stringify(master), rendered = plain(ctx.exports.componentMasterPreview(master));
  assert.deepEqual(rendered.meta, master.meta);
  assert.deepEqual(rendered.tokens, master.tokens);
  assert.deepEqual(rendered.tree[0].children[0].children, master.tree[0].children);
  assert.equal(rendered.tree[0].children[0].responsive.mobile.frame.x, 0);
  assert.equal(rendered.tree[0].responsive.mobile.frame.width, 300);
  assert.equal(rendered.responsive.viewports.mobile.width, 300);
  assert.equal(JSON.stringify(master), before);
});


test('preview and working copy choose the exact master and fail closed for a missing variant', () => {
  const ctx = { exports: {} };
  runInNewContext(ts.transpileModule(file('../src/engine/componentMaster.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, ctx);
  const resolve = ctx.exports.selectedComponentMaster;
  const masterIr = { tree: [{ text: 'Source' }] }, templateIr = { tree: [{ text: 'Different template' }] };
  const variantIr = { tree: [{ text: 'Exact mobile' }] };
  const component = { origin: 'observed', masterIr, templateIr, variants: {
    default: { masterRef: 'self' }, mobile: { masterIr: variantIr }, unresolved: { masterRef: 'missing' },
  } };
  assert.equal(resolve(component), masterIr);
  assert.equal(resolve(component, 'mobile'), variantIr);
  assert.equal(resolve(component, 'missing'), null);
  assert.equal(resolve(component, 'unresolved'), null);
  assert.equal(resolve({ origin: 'observed', templateIr }), null);
  assert.equal(resolve({ origin: 'suggested', templateIr }), templateIr);
});
