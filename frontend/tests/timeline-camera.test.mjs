import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const { buildSync } = createRequire(import.meta.url)('esbuild');
const dir = mkdtempSync(join(tmpdir(), 'timeline-camera-'));
const outfile = join(dir, 'timeline.mjs');
buildSync({ entryPoints: [fileURLToPath(new URL('../src/engine/timeline.ts', import.meta.url))], bundle: true, platform: 'node', format: 'esm', outfile, logLevel: 'silent' });
const { TimelineEngine, applySolvedToDom, applyCameraToDom, CAMERA_LAYER_ID, easingProgress } = await import(pathToFileURL(outfile));
after(() => rmSync(dir, { recursive: true, force: true }));

/* Minimal DOM stand-in: enough for querySelector/closest/style. */
function element(attrs = {}, children = []) {
  const el = { style: {}, attrs, children, parent: null };
  for (const child of children) child.parent = el;
  el.getAttribute = (name) => (name in attrs ? attrs[name] : null);
  el.matches = (selector) => selector === '[data-timeline-camera]' ? 'data-timeline-camera' in attrs
    : selector === '[data-timeline-layer]' ? 'data-timeline-layer' in attrs : false;
  el.closest = (selector) => { let node = el; while (node) { if (node.matches(selector)) return node; node = node.parent; } return null; };
  const all = (node, selector, out) => { for (const child of node.children) { if (child.matches(selector)) out.push(child); all(child, selector, out); } return out; };
  el.querySelectorAll = (selector) => all(el, selector, []);
  el.querySelector = (selector) => all(el, selector, [])[0] || null;
  return el;
}

const doc = {
  composition: { width: 1920, height: 1080, fps: 30, duration: 4000, background: '#000', aspect: '16:9' },
  groups: [],
  layers: [
    { id: 'layer-hero', type: 'component', ref: 'hero', in: 0, out: 4000, transform: { anchor: { x: 0.5, y: 0.5 }, properties: {
      opacity: { keyframes: [{ t: 0, value: 0, easing: 'cubic-bezier', bezier: [0.16, 1, 0.3, 1] }, { t: 800, value: 1 }] },
      blur: { keyframes: [{ t: 0, value: 14, easing: 'linear' }, { t: 1000, value: 0 }] },
      clip: { keyframes: [{ t: 0, value: 100, easing: 'linear' }, { t: 1000, value: 0 }] } } } },
    { id: CAMERA_LAYER_ID, type: 'camera', in: 0, out: 4000, transform: { anchor: { x: 0.5, y: 0.5 }, properties: {
      scale: { keyframes: [{ t: 0, value: 1, easing: 'cubic-bezier', bezier: [0.4, 0, 0.1, 1] }, { t: 4000, value: 1.08 }] },
      y: { keyframes: [{ t: 1000, value: 0, easing: 'linear' }, { t: 3000, value: -400 }] } } } },
  ],
};

test('camera layer transforms the wrapper, not the section layers', () => {
  const engine = new TimelineEngine(doc);
  const hero = element({ 'data-timeline-layer': 'layer-hero' });
  const host = element({}, [hero]);
  const camera = element({ 'data-timeline-camera': '' }, [host]);
  applySolvedToDom(host, engine.seek(2000));
  assert.match(camera.style.transform, /translate3d\(0\.000px, -200\.000px, 0\)/);
  assert.match(camera.style.transform, /scale\(1\.0[0-9]+\)/);
  assert.equal(camera.style.transformOrigin, '50% 50%');
  assert.match(hero.style.transform, /scale\(1\.000000\)/, 'section keeps its own transform');
  assert.equal(hero.style.opacity, '1.0000');
  assert.equal(hero.style.filter, '', 'blur is sharp after its track ends');
  applySolvedToDom(host, engine.seek(500));
  assert.equal(hero.style.filter, 'blur(7.000px)');
  assert.equal(hero.style.clipPath, 'inset(0 0 50.000% 0)');
  applySolvedToDom(host, engine.seek(2000));
  assert.equal(hero.style.clipPath, '', 'mask fully open after its track ends');
});

test('camera wrapper inside the root is found too and cleared without a camera layer', () => {
  const engine = new TimelineEngine(doc);
  const camera = element({ 'data-timeline-camera': '' });
  const host = element({}, [camera]);
  applyCameraToDom(host, engine.seek(4000));
  assert.match(camera.style.transform, /scale\(1\.080000\)/);
  const plain = new TimelineEngine({ ...doc, layers: doc.layers.filter((l) => l.id !== CAMERA_LAYER_ID) });
  applyCameraToDom(host, plain.seek(4000));
  assert.equal(camera.style.transform, '');
});

test('cinematic curves settle without overshoot except back-out', () => {
  assert.ok(easingProgress('cubic-bezier', [0.16, 1, 0.3, 1], 0.5) > 0.9, 'expo-out reaches most of the way early');
  assert.ok(easingProgress('cubic-bezier', [0.34, 1.56, 0.64, 1], 0.6) > 1, 'back-out overshoots');
  assert.equal(easingProgress('cubic-bezier', [0.4, 0, 0.1, 1], 1), 1);
});
