import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import ts from 'typescript';
import { parse } from 'svelte/compiler';

const root = path.resolve(import.meta.dirname, '../..');
const cyrillic = /[А-Яа-яЁё]/;
const keyboardFiles = new Set(['frontend/src/editor/controller.ts', 'frontend/src/engine/geoedit.ts', 'frontend/src/FlowCanvas.svelte']);

test('product chrome, labels and diagnostics stay English without banning multilingual user data', () => {
  const failures = [];
  function check(file, raw) {
    // Preserve Russian keyboard-layout aliases, CSS comments and internal AI instructions.
    if (keyboardFiles.has(file) && /^["'][А-Яа-яЁё]["']$/.test(raw)) return;
    if (!cyrillic.test(raw.replace(/\/\*[\s\S]*?\*\//g, ''))) return;
    failures.push(`${file}: ${raw.slice(0, 120)}`);
  }
  function scan(file) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    if (file.endsWith('.svelte')) {
      const ast = parse(source, { modern: true });
      const seen = new Set();
      function visit(node) {
        if (!node || typeof node !== 'object' || seen.has(node)) return;
        seen.add(node);
        if (node.type === 'Text' || node.type === 'TemplateElement' || (node.type === 'Literal' && typeof node.value === 'string')) check(file, source.slice(node.start, node.end));
        for (const [key, value] of Object.entries(node)) if (!['comments', 'parent', 'loc'].includes(key)) {
          if (Array.isArray(value)) value.forEach(visit); else visit(value);
        }
      }
      visit(ast);
    } else if (file.endsWith('.css')) {
      // CSS-generated text (content: "...") is product chrome too.
      for (const m of source.matchAll(/content\s*:\s*(["'])((?:\.|(?!\1).)*)\1/g)) check(file, m[2]);
    } else {
      const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
      function visit(node) {
        // This existing system-message array is sent to AI, never rendered as UI.
        if (file === 'frontend/src/flow/store.ts' && ts.isVariableDeclaration(node) && node.name.getText(ast) === 'instruction') return;
        if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) check(file, source.slice(node.getStart(ast), node.end));
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
  }
  function walk(dir) {
    for (const entry of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
      const file = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(file);
      else if (/\.(svelte|ts|mjs|js|html|css)$/.test(file) && !file.endsWith('.d.ts')) scan(file);
    }
  }
  walk('frontend/src'); walk('desktop/services'); walk('desktop/lib'); scan('desktop/main.mjs');
  assert.deepEqual(failures, []);
  assert.match(fs.readFileSync(path.join(root, 'frontend/src/app.html'), 'utf8'), /<html lang="en"/);
});
