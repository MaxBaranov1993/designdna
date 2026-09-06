"""Packaged Electron regression; run only with an isolated --user-data-dir.

DESIGNDNA_CDP points at the QA instance. Fixtures use the real local DS API,
but AI review is disabled to avoid provider calls during deterministic QA.
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from ui_source_import_editor_test import SOURCE_IR


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(os.environ['DESIGNDNA_CDP'])
        page = next(pg for c in browser.contexts for pg in c.pages if pg.url.startswith('file:'))
        page.reload()
        page.wait_for_function('window.GraphDev && window.__flowStore && window.designDNA')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.evaluate(r"""() => {
          const original = window.fetch;
          window.fetch = (url, options) => /design-system\/(style-review|master-review)/.test(String(url))
            ? Promise.resolve(new Response(JSON.stringify({error:'AI disabled in QA'}), {status:503}))
            : original(url, options);
        }""")
        ids = page.evaluate("""ir => {
          const g = window.GraphDev;
          g.createPage('Source + DS regression');
          const source = g.add('sourceimport', 30, 30).id;
          const ds = g.add('designsystem', 460, 30).id;
          const edit = g.add('edit', 30, 680).id;
          g.patchData(source, {url:'https://example.test/qa', activeViewport:'mobile', tokens:ir.tokens,
            blocks:[{name:'Header', lit:true, ir}, {name:'Footer',lit:true,ir}]});
          g.connect(source,'artifact',ds,'artifact');
          g.connect(source,'Header',edit,'a'); g.connect(source,'Footer',edit,'b');
          return {source,ds,edit};
        }""", SOURCE_IR)
        page.locator(f'.n-edit[data-id="{ids["edit"]}"]').wait_for(state='visible')
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        page.evaluate('window.GraphDev.fit()')
        page.wait_for_timeout(350)  # fitView's configured 250 ms animation
        build = page.locator(f'.n-designsystem[data-id="{ids["ds"]}"] [data-ds-action="build"]')
        assert build.is_enabled()
        build.click()
        page.wait_for_function('id => !!window.GraphDev.node(id).data.systemId', arg=ids['ds'], timeout=90000)
        ds = page.evaluate('id => window.GraphDev.node(id).data', ids['ds'])
        assert ds['revision'] == 0 and ds['status'] == 'draft'
        assert ds['sourceNodeId'] == ids['source'] and not ds['sourceUpdate']
        page.locator(f'.n-designsystem[data-id="{ids["ds"]}"] [data-ds-action="open"]').click()
        page.locator('[data-ds-editor]').wait_for(state='visible')
        assert page.locator('[data-ds-editor]').inner_text().strip()
        # Closing via its own action preserves the normal component lifecycle.
        page.locator('[data-ds-editor] [data-ds-action="close"]').click()
        page.locator('[data-ds-editor]').wait_for(state='detached')
        page.evaluate('window.GraphDev.fit()')
        page.locator(f'.n-edit[data-id="{ids["edit"]}"] .f-open-editor').click()
        page.locator('.dna-editor').wait_for(state='visible')
        page.wait_for_function("document.querySelector('.fe-canvas-inner [data-ir-path]')")
        assert page.evaluate('window.DNAEditor.getIR().meta.activeViewport') == 'mobile'
        count = page.locator('.fe-canvas-inner [data-ir-path]').count()
        assert count >= 8, count
        text = page.locator('.fe-canvas-inner [data-ir-path="a/root/div:1::text0"]')
        box = text.bounding_box()
        # GeoEdit intentionally owns pointer input through its canvas overlay.
        page.mouse.dblclick(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        editable = page.locator('.fe-canvas-inner [contenteditable="true"]')
        editable.wait_for(state='visible')
        editable.fill('Edited in QA')
        editable.press('Enter')
        assert page.locator('.fe-canvas-inner [data-ir-path="b/root/div:1::text0"]').inner_text() == 'Market'
        page.locator('.dna-editor [data-act="save"]').click()
        page.wait_for_function("id => JSON.stringify(window.GraphDev.node(id).data.ir).includes('Edited in QA')", arg=ids['edit'])
        engine = page.evaluate('window.designDNA.engine.status()')
        assert all(w['status'] in ('ready', 'busy') and not w.get('lastError') for w in engine['workers'].values()), engine
        shot = Path(__file__).resolve().parents[1] / 'results' / 'source-ds-editor-qa.png'
        page.screenshot(path=str(shot))
        assert not errors, errors
        print(json.dumps({'builtSystem':ds['systemId'], 'editorLayers':count, 'viewport':'mobile',
                          'engine':engine, 'errors':errors, 'screenshot':str(shot)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
