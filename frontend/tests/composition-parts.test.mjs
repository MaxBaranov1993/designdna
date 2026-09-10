import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url), { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'composition-parts-')), entry = join(dir, 'test.mjs');
buildSync({ entryPoints: [fileURLToPath(new URL('../src/engine/composition-parts.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile: entry, logLevel: 'silent' });
const { compositionParts } = await import(pathToFileURL(entry));
after(() => { unlinkSync(entry); rmdirSync(dir); });

test('canonical master retains structure, hashes, resources and text during inventory', () => {
  const ir = { tree: [{ type: 'source-block', sourceKey: 'exact', _dsMaster: { hash: 'exact' },
    style: { background: '#fff', backgroundImage: 'url("ddna://blobs/background.png")' }, children: [
      { type: 'text', text: 'Точная цена: 1490 ₽', sourceKey: 'price' },
      { type: 'image', src: 'ddna://blobs/image.png' },
      { type: 'icon', props: { name: 'arrow' } },
    ] }] };
  const before = JSON.stringify(ir);
  const { parts } = compositionParts(ir);
  assert.equal(JSON.stringify(ir), before);
  assert(parts.every(part => part.protected));
  assert.deepEqual(parts.filter(part => part.kind === 'pixels').map(part => part.image), ['ddna://blobs/background.png', 'ddna://blobs/image.png']);
  assert.equal(parts.find(part => part.sourceKey === 'price').label, 'Точная цена: 1490 ₽');
  assert(parts.some(part => part.group === 'decoration'));
});
test('semantic media, missing image and unlocked native text remain distinct', () => {
  const { parts } = compositionParts({ tree: [{ type: 'hero', props: { heading: 'Заголовок', media: { src: 'sample.png' } }, children: [{ type: 'image', imagePrompt: 'Object' }] }] });
  assert.equal(parts.filter(part => part.kind === 'pixels').length, 2);
  assert.equal(parts.filter(part => part.kind === 'text').length, 1);
  assert(parts.every(part => !part.protected));
  assert.equal(compositionParts(null).parts.length, 0);
  const gradient = { tree: [{ type: 'frame', style: { backgroundImage: 'linear-gradient(red, blue)' } }] };
  assert(compositionParts(gradient).parts.some(part => part.group === 'background' && !part.image));
});
