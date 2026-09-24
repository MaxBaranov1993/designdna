import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

// Same scenario as app/source_page_layout_test.py: the Page node puts captured
// Source sections back where they were on the site.
const { buildSync } = createRequire(import.meta.url)('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'source-layout-'));
const entry = join(dir, 'entry.ts');
writeFileSync(entry, `export { composePage } from ${JSON.stringify(fileURLToPath(new URL('../src/flow/compose.ts', import.meta.url)))};
export { composeSourceInputs } from ${JSON.stringify(fileURLToPath(new URL('../src/flow/sourceComposition.ts', import.meta.url)))};`);
const outfile = join(dir, 'bundle.mjs');
buildSync({ entryPoints: [entry], bundle: true, platform: 'node', format: 'esm', outfile, logLevel: 'silent' });
const { composePage, composeSourceInputs } = await import(pathToFileURL(outfile));
after(() => rmSync(dir, { recursive: true, force: true }));

const SOURCE = 'https://example.test/';
const sourceBlock = (name, x, y, width, height) => ({
  name,
  ir: {
    version: '1.1', tokens: {},
    meta: { name, pageRect: { x, y, width, height, source: SOURCE }, pageBackground: '#ffffff' },
    tree: [{
      id: name, type: 'source-block', variant: 'dom-capture', sourceKey: 'root', props: {},
      style: { background: '#fbf6ea', borderRadius: 12 },
      frame: { width, height, layout: 'free', clip: true, padding: [0, 0, 0, 0] },
      children: [{ type: 'text', text: name, sourceKey: `root/${name}`, frame: { absolute: true, x: 10, y: 10, width: 200, height: 20 } }],
    }],
  },
});
const generated = { name: 'form', ir: { version: '1.1', tokens: {}, meta: { name: 'form' }, tree: [
  { id: 'form', type: 'contact-form', variant: 'default', props: { heading: 'Contact' }, frame: { width: 'fill', height: 'hug' } }] } };

test('captured sections become bands at their page position', () => {
  const page = composePage([sourceBlock('header', 0, 0, 1440, 80), sourceBlock('hero', 130, 80, 1180, 600)], null);
  const [header, hero] = page.tree;
  const box = hero.children[0];
  assert.equal(hero.frame.width, 'fill');
  assert.equal(hero.frame.layout, 'free');
  assert.deepEqual(hero.style, {}, 'bands are transparent');
  assert.equal(page.meta.pageBackground, '#ffffff', 'the page background is painted once on the page root');
  assert.equal(box.sourceKey.endsWith('::box'), true);
  assert.equal(box.role, 'section', 'drawn as the captured box, not a generated card with shadow');
  assert.equal(box.frame.x, 130);
  assert.equal(box.frame.width, 1180);
  assert.equal(box.style.background, '#fbf6ea');
  assert.equal(box.frame.clip, true);
  assert.equal(header.frame.height, 80);
});

test('gaps and overlaps between neighbours are preserved', () => {
  const page = composePage([
    sourceBlock('hero', 130, 80, 1180, 600),
    sourceBlock('features', 130, 700, 1180, 300),
    sourceBlock('media', 0, 990, 1440, 400),
  ], null);
  const [hero, features, media] = page.tree;
  assert.equal(hero.frame.height, 620);
  assert.equal(features.frame.height, 290);
  assert.equal(features.frame.clip, false);
  assert.equal(media.frame.height, 400);
});

test('a generated block between bands flows and breaks the gap chain', () => {
  const page = composePage([sourceBlock('hero', 130, 80, 1180, 600), generated, sourceBlock('footer', 0, 700, 1440, 200)], null);
  const [hero, form, footer] = page.tree;
  assert.equal(form.type, 'contact-form');
  assert.equal(hero.frame.height, 600);
  assert.equal(footer.children[0].frame.x, 0);
});

test('source provenance follows the children inside the band box', () => {
  const block = sourceBlock('hero', 130, 80, 1180, 600);
  const input = { ...block, sourceRegistry: { src: { id: 'src', kind: 'import', label: 'Source' } },
    nodeSources: { root: 'src', 'root/hero': 'src' }, layoutEvidence: [] };
  const { ir, nodeSources } = composeSourceInputs([input]);
  const box = ir.tree[0].children[0];
  const text = box.children[0];
  assert.equal(nodeSources[box.sourceKey], 'src');
  assert.equal(nodeSources[text.sourceKey], 'src');
});

test('a transparent generated section between bands shows the page background', () => {
  const page = composePage([sourceBlock('hero', 130, 80, 1180, 600), generated, sourceBlock('footer', 0, 700, 1440, 200)], null);
  assert.equal(page.meta.pageBackground, '#ffffff');
  assert.ok(!page.tree[1].style?.background, 'the generated section stays transparent over the page background');
  const painted = structuredClone(generated);
  painted.ir.tree[0].style = { background: '#101010' };
  const own = composePage([sourceBlock('hero', 130, 80, 1180, 600), painted], null);
  assert.notEqual(own.tree[1].style.background, '#ffffff', 'an own surface is kept (style DNA may remap it)');
});

test('a generated colour already in the page palette survives page style adaptation', () => {
  const pageTokens = { color: { primary: '#06111f', accent: '#1672ff', background: '#ffffff', text: '#06111f' } };
  const form = { name: 'form', ir: { version: '1.1', tokens: { color: { primary: '#06111f', accent: '#cbff16', background: '#ffffff', text: '#06111f' } },
    meta: { name: 'form' }, tree: [{ id: 'form', type: 'composition', variant: 'contact', props: {}, frame: {},
      children: [{ type: 'badge', text: 'CONTACT', style: { color: '#1672ff', background: '#ffffff00' } }] }] } };
  const page = composePage([sourceBlock('hero', 130, 80, 1180, 600), form], pageTokens);
  assert.equal(page.tree[1].children[0].style.color, '#1672ff');
});

test('a section palette colour is still remapped when it happens to sit near a target colour', () => {
  // Light section on a dark page: #ffffff is near the dark theme's #f8fafc text,
  // but it is the section's own background and must become the page background.
  const dark = { color: { primary: '#ff6b20', background: '#101010', surface: '#1a1a1a', text: '#f8fafc', border: '#333333' } };
  const light = { name: 'light', ir: { version: '1.1', tokens: { color: { primary: '#111111', background: '#ffffff', surface: '#f5f5f7', text: '#111111', border: '#e0e0e0' } },
    meta: { name: 'light' }, tree: [{ id: 'hero', type: 'hero', variant: 'centered', props: {}, frame: {}, style: { background: '#ffffff' },
      children: [{ type: 'text', text: 'Hi', style: { color: '#111111', background: '#f5f5f7' } }] }] } };
  const page = composePage([light], dark);
  assert.equal(page.tree[0].style.background, '#101010');
  assert.equal(page.tree[0].children[0].style.background, '#1a1a1a');
  assert.equal(page.tree[0].children[0].style.color, '#f8fafc');
});
