"""Headless regressions for source screenshot contamination by sticky headers."""
import io

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

from source_capture_viewport import prepare_capture_viewport


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def source_html(position='sticky'):
    return f'''<style>
      * {{box-sizing:border-box}} html {{scroll-behavior:smooth}}
      body {{margin:0;background:#fff}}
      header {{position:{position};top:0;left:0;width:100%;height:110px;
        background:#ee2222;z-index:100}}
      main {{padding-top:300px;height:2400px}}
      #block {{height:196px;position:relative}}
      article {{position:absolute;inset:0;background:#6622ee}}
    </style><header><span>Source header</span></header>
    <main><section id="block"><article></article></section></main>'''


@pytest.mark.parametrize('position', ['fixed', 'sticky'])
@pytest.mark.parametrize('width', [390, 768, 1440])
def test_reference_and_backdrop_share_unoccluded_geometry(browser, position, width):
    page = browser.new_page(viewport={'width': width, 'height': 844}, device_scale_factor=1)
    try:
        page.set_content(source_html(position))
        block = page.locator('#block')
        # Reproduce the original pipeline's signed offset: target moves UP.
        block.evaluate("el => window.scrollTo({top:el.offsetTop,behavior:'instant'})")
        page.evaluate("window.scrollBy({top:126,behavior:'instant'})")
        contaminated = Image.open(io.BytesIO(block.screenshot()))
        assert contaminated.getpixel((width // 2, 10))[:3] == (238, 34, 34)
        before_style = page.locator('header').get_attribute('style')
        result = prepare_capture_viewport(page, block)
        assert result['clear'] and result['fullyVisible'], result
        assert result['top'] >= 110
        geometry = block.bounding_box()
        # Exercise the exact later backdrop -> reference locator screenshot
        # sequence. Neither should change the placement the compiler measured.
        block.locator('article').evaluate("el => el.style.visibility='hidden'")
        backdrop = Image.open(io.BytesIO(block.screenshot()))
        block.locator('article').evaluate("el => el.style.removeProperty('visibility')")
        reference = Image.open(io.BytesIO(block.screenshot()))
        assert block.bounding_box() == geometry
        assert backdrop.getpixel((width // 2, 10))[:3] == (255, 255, 255)
        assert reference.getpixel((width // 2, 10))[:3] == (102, 34, 238)
        assert page.locator('header').get_attribute('style') == before_style
        assert page.locator('header').evaluate("el => getComputedStyle(el).visibility") == 'visible'
        assert page.viewport_size == {'width': width, 'height': 844}
    finally:
        page.close()


def test_captured_header_and_sticky_ancestors_are_not_external_chrome(browser):
    page = browser.new_page(viewport={'width': 768, 'height': 844})
    try:
        page.set_content(source_html())
        header = page.locator('header')
        assert prepare_capture_viewport(page, header)['clear']
        assert prepare_capture_viewport(page, header.locator('span'))['clear']
        assert page.evaluate('scrollY') == 0
        # Already clear content is not gratuitously scrolled.
        block = page.locator('#block')
        before = block.bounding_box()
        assert prepare_capture_viewport(page, block)['clear']
        assert block.bounding_box() == before
    finally:
        page.close()


def test_unavoidable_overlap_is_reported_without_hiding_source(browser):
    page = browser.new_page(viewport={'width': 768, 'height': 844})
    try:
        page.set_content(source_html('fixed'))
        page.locator('#block').evaluate("el => el.style.cssText='position:fixed;top:0;width:100%'")
        result = prepare_capture_viewport(page, page.locator('#block'))
        assert not result['clear']
        assert page.locator('header').is_visible()
    finally:
        page.close()


def test_tall_target_reports_nonfitting_geometry_and_keeps_layout(browser):
    page = browser.new_page(viewport={'width': 768, 'height': 844})
    try:
        page.set_content(source_html())
        block = page.locator('#block')
        block.evaluate("el => {el.style.height='1100px';window.scrollTo({top:el.offsetTop,behavior:'instant'})}")
        result = prepare_capture_viewport(page, block)
        assert result['clear'], result
        assert not result['fullyVisible'], result
        assert block.bounding_box()['height'] == 1100
        assert page.viewport_size == {'width': 768, 'height': 844}
        assert page.locator('header').is_visible()
    finally:
        page.close()


def test_stacked_top_bars_clear_the_lowest_edge(browser):
    page = browser.new_page(viewport={'width': 768, 'height': 844})
    try:
        page.set_content(source_html('fixed') +
                         '<aside style="position:fixed;top:110px;left:0;width:100%;height:40px;z-index:101;background:red">Toolbar</aside>')
        block = page.locator('#block')
        block.evaluate("el => window.scrollTo({top:el.offsetTop,behavior:'instant'})")
        result = prepare_capture_viewport(page, block)
        assert result['clear'] and result['fullyVisible'], result
        assert result['obstructionBottom'] == 150
        assert block.bounding_box()['y'] >= 150
    finally:
        page.close()


@pytest.mark.parametrize('bottom_gap', [0, 20])
def test_bottom_navigation_and_floating_button_do_not_cover_capture(browser, bottom_gap):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    try:
        page.set_content(source_html('fixed') + f'''
          <nav style="position:fixed;bottom:{bottom_gap}px;left:0;width:100%;height:64px;z-index:100;background:#ff0000">Navigation</nav>
          <button style="position:fixed;bottom:84px;right:4px;width:48px;height:48px;z-index:101;background:#ff0000">Up</button>
        ''')
        block = page.locator('#block')
        # Initial scroll-into-view can leave a fully visible block at the bottom
        # of the viewport, where fixed site navigation still obscures it.
        block.evaluate("el => {el.style.marginTop='500px';window.scrollTo({top:el.offsetTop - 644,behavior:'instant'})}")
        placement = prepare_capture_viewport(page, block)
        assert placement['clear'] and placement['fullyVisible'], placement
        assert block.bounding_box()['y'] >= 110
        assert block.bounding_box()['y'] + block.bounding_box()['height'] <= 712
        assert page.locator('nav').is_visible()
        assert page.locator('button').is_visible()
        before = block.bounding_box()
        shot = Image.open(io.BytesIO(block.screenshot())).convert('RGB')
        assert (255, 0, 0) not in shot.getdata()
        assert block.bounding_box() == before
    finally:
        page.close()


@pytest.mark.parametrize('corrected', [False, True])
def test_capture_pipeline_reference_matches_editable_render(tmp_path, monkeypatch, corrected):
    """Exercise the production hook, compiler, backdrop and renderer together."""
    import fidelity_harness
    import scraper
    import source_capture_viewport

    if not corrected:
        def old_signed_adjustment(page, locator):
            page.evaluate("window.scrollBy({top:126,behavior:'instant'})")
            return {'clear': True, 'fullyVisible': True}
        monkeypatch.setattr(source_capture_viewport, 'prepare_capture_viewport', old_signed_adjustment)

    monkeypatch.setenv('DESIGNDNA_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(scraper, 'validate_public_url', lambda url: None)
    html = source_html() + '<style>main{padding-top:0}</style>'

    def local_page(browser, viewport):
        context = browser.new_context(viewport=viewport, device_scale_factor=1)
        context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
        return context, context.new_page()

    monkeypatch.setattr(scraper, '_guarded_browser_page', local_page)
    captured = scraper.capture_block_irs(
        'https://source.test/',
        [{'name': 'cards', 'kind': 'section', 'label': 'Cards', 'selector': '#block'}],
        viewports=[{'name': 'tablet', 'width': 768, 'height': 844}],
    )
    report = fidelity_harness.evaluate_captures(captured, artifacts_dir=tmp_path / 'fidelity')['#block']
    assert not report['raster_fallback'], report
    similarity = report['viewports']['tablet']['pixel_similarity']
    print({'corrected': corrected, 'pixel_similarity': similarity, 'gate': report['gate']})
    if corrected:
        assert report['gate']['passed'], report['gate']
        assert similarity >= 99
    else:
        assert not report['gate']['passed'], report['gate']
        assert similarity < 85
