"""Cross-origin font files must remain bound to their CSS declarations."""
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scraper


def test_cross_origin_fonts_use_declarations_and_fail_closed():
    compiler = Path(__file__).with_name('source_import_compiler.js').read_text(encoding='utf-8')
    with sync_playwright() as playwright:
        browser = scraper.launch_chromium(playwright)
        try:
            page = browser.new_page()

            def route(request):
                if request.request.url == 'https://fixture.test/':
                    request.fulfill(content_type='text/html', body=(
                        '<link rel="stylesheet" href="https://cdn.test/fonts.css">'
                        '<div id="sample">Hello</div>'
                    ))
                elif request.request.url == 'https://cdn.test/fonts.css':
                    request.fulfill(content_type='text/css',
                                    headers={'Access-Control-Allow-Origin': '*'}, body=(
                        '@font-face{font-family:TextFont;font-weight:400;src:url(text.woff2)}'
                        '@font-face{font-family:IconFont;font-weight:900;src:url(icons.woff2)}'
                    ))
                else:
                    request.abort()

            page.route('**/*', route)
            page.goto('https://fixture.test/')
            result = page.evaluate(compiler, [{'selector': '#sample'}])
            faces = {face['family']: face['urls'] for face in result[0]['fontFaces']}
            assert faces == {
                'TextFont': ['https://cdn.test/text.woff2'],
                'IconFont': ['https://cdn.test/icons.woff2'],
            }
            # Denied CSS has no proven mapping; timing cannot establish one.
            page.route('https://cdn.test/fonts.css', lambda request: request.abort())
            result = page.evaluate(compiler, [{'selector': '#sample'}])
            assert result[0]['fontFaces'] == []
        finally:
            browser.close()
