import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url), { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'diagram-')), entry = join(dir, 'test.mjs');
buildSync({ entryPoints: [fileURLToPath(new URL('../src/editor/diagram.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile: entry, logLevel: 'silent' });
const { diagramSection } = await import(pathToFileURL(entry));
after(() => { unlinkSync(entry); rmdirSync(dir); });

test('process diagram preserves tokens/source, uses editable primitives and keeps long labels inside its canvas', () => {
  for (const width of [320, 390, 880, 1280]) {
    const ir = {frame: {width}, tokens: {color: {primary: '#D44820', text: '#112233', surface: '#F3F4F5'}}, tree: [{sourceMeta: {componentRef: {masterHash: 'exact'}}}]};
    const before = structuredClone(ir), labels = ['Получение данных', 'Обработка подробного описания '.repeat(3), 'Проверка результата'];
    const section = diagramSection(ir, 'Подробная схема процесса '.repeat(6), labels);
    assert.deepEqual(ir, before);
    const texts = [];
    const walk = node => { assert.ok(['composition','heading','text','frame','rect'].includes(node.type)); if(node.text) texts.push(node.text); for(const child of node.children || []) { assert.ok(child.frame.x >= 0 && child.frame.y >= 0); assert.ok(child.frame.x + child.frame.width <= node.frame.width + 1); assert.ok(child.frame.y + child.frame.height <= node.frame.height + 1); walk(child); } };
    walk(section);
    labels.forEach(label => assert.ok(texts.includes(label.trim())));
    assert.equal(texts.filter(text => ['→','↓'].includes(text)).length, 2);
    assert.equal(section.children[1].children[0].style.borderColor, '#D44820');
  }
});

test('invalid process input is rejected before any insertion', () => {
  assert.throws(() => diagramSection({}, 'Test', ['Only one']), /2 до 6/);
  assert.throws(() => diagramSection({}, 'Test', Array(7).fill('A')), /2 до 6/);
});
