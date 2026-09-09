"""Review compares the candidate in Source context without hiding candidate defects."""
import copy
import io
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

import scraper
import fidelity_harness as fh
from design_system import document as dsdoc, master_review as review


def test_review_context_preserves_neighbor_glow_but_renders_changed_master():
    compiler = Path(__file__).with_name("source_import_compiler.js").read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = scraper.launch_chromium(p)
        try:
            page = browser.new_page(viewport={"width": 400, "height": 300}, device_scale_factor=1)
            page.set_content('''<style>body{margin:0}section{width:240px;height:100px;position:relative;background:#101012}
              article{position:absolute;left:0;top:0;width:150px;height:100px;background:#101012}
              .glow{position:absolute;left:155px;top:25px;width:45px;height:45px;background:#ff8020;filter:blur(25px)}
              </style><section id="source"><article></article><div class="glow"></div></section>''')
            definition = {"name": "source", "selector": "#source", "kind": "section"}
            item = page.evaluate(compiler, [definition])[0]
            ir = scraper._captured_ir(definition, item)
            source = page.locator("#source").screenshot(type="png")
            master = next(n for n, _ in scraper._walk_source_nodes(ir["tree"]) if n.get("sourceKey") == "root/article:1")
            bounds = {"x": 0, "y": 0, "width": 150, "height": 100}
            ir["responsive"] = {"viewports": {"desktop": {"width": 240, "height": 100}}}
            comp = {"masterIr": {**copy.deepcopy(ir), "tree": [copy.deepcopy(master)]},
                    "sourceRef": {"sourceKey": "root/article:1", "evidenceKey": "proof", "boundsByViewport": {"desktop": bounds}}}
            doc = {"referenceAssets": {"proof": {"sourceIr": ir, "sourceIrHash": dsdoc.content_hash(ir)}}}
            before = copy.deepcopy((doc, comp))
            render_page = browser.new_page(device_scale_factor=1)
            candidate = review.with_source_context(doc, comp)
            png = review.render_master_png(render_page, candidate, "desktop")
            reference = fh._crop_png(source, bounds, {"width": 240, "height": 100})
            assert fh._image_metrics(reference, png)["pixel_similarity"] >= 98
            changed = copy.deepcopy(comp)
            changed["masterIr"]["tree"][0].setdefault("style", {})["background"] = "#ff0000"
            bad = review.render_master_png(render_page, review.with_source_context(doc, changed), "desktop")
            assert fh._image_metrics(reference, bad)["pixel_similarity"] < 80
            resized = copy.deepcopy(comp)
            resized["masterIr"]["tree"][0]["frame"]["width"] = 100
            small = review.render_master_png(render_page, review.with_source_context(doc, resized), "desktop")
            assert Image.open(io.BytesIO(small)).size[0] == 100
            assert (doc, comp) == before
            doc["referenceAssets"]["proof"]["sourceIr"]["tree"][0]["children"] = []
            with pytest.raises(ValueError, match="hash mismatch"):
                review.with_source_context(doc, comp)
        finally:
            browser.close()
