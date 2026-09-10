import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { mkdtempSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url), { buildSync } = require('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'portable-assets-')), entry = join(dir, 'test.mjs');
buildSync({ entryPoints: [fileURLToPath(new URL('../src/flow/portable-assets.ts', import.meta.url))], bundle: true, format: 'esm', platform: 'node', outfile: entry, logLevel: 'silent' });
const { embedGraphAssets, restoreGraphAssets } = await import(pathToFileURL(entry));
after(() => { unlinkSync(entry); rmdirSync(dir); });
const bytes = Buffer.from([1, 2, 3, 4]), hash = createHash('sha256').update(bytes).digest('hex');
const name = hash + '.png', url = 'data:image/png;base64,' + bytes.toString('base64'), ref = 'ddna://blobs/' + name;
function bridge(objects = {}) {
  const calls = [];
  globalThis.window = { designDNA: { blobs: {
    getMany: async names => Object.fromEntries(names.map(name => [name, objects[name]])),
    put: async (mime, base64) => {
      calls.push([mime, base64]); const sha256 = createHash('sha256').update(Buffer.from(base64, 'base64')).digest('hex');
      const name = sha256 + '.png'; objects[name] = `data:${mime};base64,${base64}`; return { name, sha256 };
    },
  } } };
  return { objects, calls };
}
test('export/import in a fresh blob store preserves exact IR, master hashes and duplicate references', async () => {
  bridge({ [name]: url });
  const graph = { nodes: [{ id: 1, data: { ir: { tree: [{ type: 'image', src: ref, sourceMeta: { componentRef: { masterHash: 'exact' } } }] }, preview: ref } }], edges: [] };
  const before = structuredClone(graph), exported = await embedGraphAssets(graph);
  assert.deepEqual(graph, before);
  assert.deepEqual(exported.nodes, graph.nodes);
  assert.deepEqual(Object.keys(exported.embeddedBlobs.objects), [name]);
  const fresh = bridge();
  const reopened = await restoreGraphAssets(JSON.parse(JSON.stringify(exported)));
  assert.deepEqual(reopened, graph);
  assert.equal(fresh.objects[name], url);
  assert.equal(fresh.calls.length, 1);
});
test('missing/corrupt embedded resources cannot replace the graph or write partial imports', async () => {
  bridge();
  const graph = { nodes: [{ data: { src: ref } }] };
  await assert.rejects(embedGraphAssets(graph), /отсутствует/);
  const fresh = bridge();
  await assert.rejects(restoreGraphAssets({ ...graph, embeddedBlobs: { version: 'design-assets-export/1.0', objects: { [name]: 'data:image/png;base64,AA==' } } }), /повреждён/);
  assert.equal(fresh.calls.length, 0);
  await assert.rejects(restoreGraphAssets(graph), /отсутствует/);
});
test('legacy inline-only graph remains compatible without a desktop bridge', async () => {
  globalThis.window = {};
  const graph = { nodes: [{ data: { src: url } }], edges: [] };
  assert.deepEqual(await embedGraphAssets(graph), graph);
  assert.deepEqual(await restoreGraphAssets(graph), graph);
});
