import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url), { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'assembly-scene-')), entry = join(dir, 'test.mjs');
buildSync({ stdin: { contents: `export * from './src/editor/assembly-scene'; export {TimelineEngine} from './src/engine/timeline';`,
  resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts' }, bundle: true, format: 'esm', platform: 'node', outfile: entry, logLevel: 'silent' });
const { assembleLayers, TimelineEngine } = await import(pathToFileURL(entry));
after(() => { unlinkSync(entry); rmdirSync(dir); });

test('assembly animates independent leaves, retaining Source hashes, existing tracks and locked parts', () => {
  const ir = { tree: [{ type: 'composition', sourceKey: 'canonical', children: [{ type: 'text', text: 'Живой текст' }, { type: 'image', src: 'ddna://blobs/exact.png' }] }] };
  const make = (id, target) => ({ id, storyTarget: target, type: 'component', pageId: 'page', in: 0, out: 6000, transform: { anchor: { x: .5, y: .5 }, properties: {} } });
  const doc = { version: '1.0', composition: { duration: 6000 }, source: { designIrHash: 'canonical', layerManifestHash: 'manifest' },
    groups: [], layers: [make('root', 's0'), make('text', 's0.children.0'), make('image', 's0.children.1'), { ...make('locked', 's1'), locked: true }],
    story: { initialPageId: 'page', pages: [{ id: 'page', ir }], actions: [] } };
  const before = structuredClone(doc);
  assert.equal(assembleLayers(doc), 2);
  assert.deepEqual(doc.source, before.source);
  assert.deepEqual(doc.story, before.story);
  assert.deepEqual(doc.layers[0], before.layers[0]);
  assert.deepEqual(doc.layers[3], before.layers[3]);
  const solver = new TimelineEngine(doc);
  assert.equal(solver.seek(0).text.opacity, 0);
  assert.equal(solver.seek(2000).image.opacity, 1);
  assert.equal(solver.seek(2000).image.y, 0);
  const after = structuredClone(doc);
  assert.throws(() => assembleLayers(doc), /Нет свободных/);
  assert.deepEqual(doc, after);
});
