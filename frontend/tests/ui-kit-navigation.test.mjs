import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../../app/design_system/styleguide.py', import.meta.url), 'utf8');
const start = source.indexOf("  document.addEventListener('click', function(event){");
const end = source.indexOf('\n})();', start);
assert.ok(start > 0 && end > start);
const handlerSource = source.slice(start, end);

for (const modified of [false, true]) test(`UI Kit fragment keeps blob document alive (modified=${modified})`, () => {
  let click, prevented = false, scrolled = false;
  const section = {scrollIntoView(options) { assert.equal(options.block, 'start'); scrolled = true; }};
  const link = {getAttribute() {return '#rules';}};
  const document = {addEventListener(name, handler) {assert.equal(name, 'click'); click = handler;},
    getElementById(id) {assert.equal(id, 'rules'); return section;}};
  runInNewContext(handlerSource, {document});
  click({target:{closest(selector) {return selector.startsWith('nav.toc') ? link : null;}},
    ctrlKey:modified, preventDefault() {prevented = true;}});
  assert.equal(prevented, !modified);
  assert.equal(scrolled, !modified);
});

test('UI Kit does not hijack missing targets or unrelated links', () => {
  let click;
  const document = {addEventListener(_name, handler) {click = handler;}, getElementById() {return null;}};
  runInNewContext(handlerSource, {document});
  for (const link of [null, {getAttribute() {return '#unknown';}}])
    click({target:{closest(selector) {return selector.startsWith('nav.toc') ? link : null;}},
      preventDefault() {assert.fail('must not intercept unrelated navigation');}});
});
