"""Negative document bounds must not turn a block crop into a page-origin PNG."""
import io
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

import fidelity_harness
import scraper
from source_capture_pixels import capture_source_png


@pytest.mark.parametrize('prefix', ['', '<b>Output:</b> '])
def test_wrapped_source_text_survives_capture_merge_and_browser_render(prefix):
    compiler = Path(__file__).with_name('source_import_compiler.js').read_text(encoding='utf-8')
    content = 'who to email + how many you can reach.'
    variants, sizes, references = {}, {}, {}
    with sync_playwright() as p:
        browser = scraper.launch_chromium(p)
        try:
            page = browser.new_page(device_scale_factor=1)
            for name, width in [('desktop', 1440), ('mobile', 390)]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.set_content(f'''<style>body{{margin:0}} section{{width:280px;height:130px;background:#fff}}
                  p{{font:16px/24px Arial;margin:0;width:145px;color:#333;{"-webkit-font-smoothing:antialiased;will-change:opacity" if prefix else ""}}}
                  @media(max-width:600px){{p{{width:240px}}}}</style>
                  <section id="step"><p>{prefix}{content}</p></section>''')
                block = {'name': 'step', 'kind': 'section', 'selector': '#step', 'label': 'Step'}
                item = page.evaluate(compiler, [block])[0]
                sizes[name] = {'width': item['root']['width'], 'height': item['root']['height']}
                references[name] = capture_source_png(page, page.locator('#step'), item)
                variants[name] = scraper._captured_ir(block, item)
            merged = scraper._merge_responsive_irs(variants, sizes)
            render_page = browser.new_page(device_scale_factor=1)
            for name, size in sizes.items():
                rendered = fidelity_harness._render_block_png(render_page, merged, name, **size)
                texts = render_page.locator('#preview p').all_text_contents()
                assert ' '.join(' '.join(texts).split()) == ('Output: ' if prefix else '') + content, (name, texts)
                metrics = fidelity_harness._image_metrics(references[name], rendered)
                assert metrics['pixel_similarity'] >= (95 if prefix else 98), (name, metrics)
        finally:
            browser.close()


@pytest.mark.parametrize('left,top', [(-7.5,85), (-7.5,140), (20,-7.5)])
def test_clipped_document_preserves_nodes_gradient_and_pixel_coordinates(left, top):
    compiler = Path(__file__).with_name('source_import_compiler.js').read_text(encoding='utf-8')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1440,'height':900}, device_scale_factor=1)
        page.set_content(f'''<style>
          body{{margin:0;height:2000px;background:#fff}}
          header{{position:fixed;left:0;top:0;width:100%;height:73px;background:#f00}}
          section{{position:absolute;left:{left}px;top:{top}px;width:1400px;height:272px;
            background:linear-gradient(90deg,#800080,#0000ff)}}
          i{{position:absolute;left:0;top:100px;width:12px;height:20px;background:#fff}}
          b{{position:absolute;left:100px;top:220px;width:900px;height:30px;background:#0f0}}
        </style><header></header><section id="block"><i></i><b></b></section>''')
        block={'name':'crop','kind':'section','selector':'#block','label':'Crop'}
        item=page.evaluate(compiler,[block])[0]
        root=item['root']
        assert root['originalBounds']=={'x':left,'y':top,'width':1400,'height':272}
        assert root['visibleCrop']['x']==max(0,-left)
        assert root['visibleCrop']['y']==max(0,-top)
        wrapper=item['nodes'][0]
        assert wrapper['frame']['width']==1400 and wrapper['frame']['height']==272
        assert wrapper['frame']['x']==-root['visibleCrop']['x']
        assert wrapper['frame']['y']==-root['visibleCrop']['y']
        # Both real children survive even when the left one is partly clipped;
        # the full-width gradient layer is retained at its original dimensions.
        assert len(wrapper['children'])==3
        assert wrapper['children'][0]['frame']['width']==1400
        assert any(n['frame']['width']==12 for n in wrapper['children'])
        screenshot=capture_source_png(page,page.locator('#block'),item)
        image=Image.open(io.BytesIO(screenshot)).convert('RGB')
        assert image.size==(root['width'],root['height'])
        assert image.getpixel((120,round(230-root['visibleCrop']['y'])))==(0,255,0)
        assert (255,0,0) not in {color for count,color in image.getcolors(image.width*image.height)}
        ir=scraper._captured_ir(block,item)
        render_page=browser.new_page(device_scale_factor=1)
        render_page.route('https://**/*',lambda route:route.abort())
        render=fidelity_harness._render_block_png(render_page,ir,'desktop',root['width'],root['height'])
        metrics=fidelity_harness._image_metrics(screenshot,render)
        assert metrics['pixel_similarity']>=99, metrics['pixel_similarity']
        browser.close()


def test_explicit_crop_rejects_geometry_drift():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.set_content('<div style="position:absolute;left:0;top:85px;width:100px;height:100px">x</div>')
        item={'root':{'captureRect':{'x':0,'y':85,'width':100,'height':100},
                      'originalBounds':{'x':-7.5,'y':85,'width':100,'height':100}}}
        with pytest.raises(ValueError,match='geometry changed'):
            capture_source_png(page,page.locator('div'),item)
        browser.close()


@pytest.mark.parametrize('namespace', ['', 'panel'])
def test_desktop_only_crop_keeps_responsive_children_visible_and_editable(namespace):
    import copy
    compiler = Path(__file__).with_name('source_import_compiler.js').read_text(encoding='utf-8')
    viewports = {'desktop': {'width': 1440, 'height': 900},
                 'tablet': {'width': 768, 'height': 1024},
                 'mobile': {'width': 390, 'height': 844}}
    variants, references, sizes = {}, {}, {}
    with sync_playwright() as p:
        browser = scraper.launch_chromium(p)
        try:
            page = browser.new_page(device_scale_factor=1)
            for name, size in viewports.items():
                page.set_viewport_size(size)
                page.set_content('''<style>body{margin:0;height:1600px}
                  section{position:absolute;left:-7.5px;top:85px;width:1440px;height:272px;
                    background:linear-gradient(90deg,#800080,#0000ff)}
                  b{position:absolute;left:90px;top:50px;width:150px;height:30px;background:#0f0}
                  @media(max-width:1023px){section{left:0;width:100%;height:200px}b{left:30px}}
                  </style><section id="block"><b></b></section>''')
                block = {'name': 'crop', 'kind': 'section', 'selector': '#block', 'label': 'Crop'}
                item = page.evaluate(compiler, [block])[0]
                sizes[name] = (item['root']['width'], item['root']['height'])
                references[name] = capture_source_png(page, page.locator('#block'), item)
                if namespace:
                    scraper._namespace_block_keys(item, namespace)
                variants[name] = scraper._captured_ir(block, item)
            original = copy.deepcopy(variants)
            block_meta = {name: {'width': width, 'height': height}
                          for name, (width, height) in sizes.items()}
            merged = scraper._merge_responsive_irs(variants, block_meta)
            assert variants == original
            wrapper = merged['tree'][0]['children'][0]
            prefix = namespace + ':' if namespace else ''
            assert wrapper['sourceKey'] == prefix + 'root::original-bounds'
            for name in ('tablet', 'mobile'):
                assert wrapper['responsive'][name]['visible'] is True
                assert wrapper['responsive'][name]['frame']['x'] == 0
            keys = [n['sourceKey'] for n, _ in scraper._walk_source_nodes(merged['tree'])]
            assert len(keys) == len(set(keys)) and prefix + 'root/b:1' in keys
            render_page = browser.new_page(device_scale_factor=1)
            for name, (width, height) in sizes.items():
                rendered = fidelity_harness._render_block_png(render_page, merged, name, width, height)
                metrics = fidelity_harness._image_metrics(references[name], rendered)
                assert metrics['pixel_similarity'] is not None, (name, metrics)
                assert metrics['pixel_similarity'] >= 99, (name, metrics['pixel_similarity'])
        finally:
            browser.close()
