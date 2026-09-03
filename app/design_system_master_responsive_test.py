"""Превью мастера ДС уважает per-viewport override'ы: клоны других вьюпортов
(visible:false) не рисуются поверх видимого текста, артборд превью — размером
с компонент, а не 1440×900 страницы."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_system import document as dsdoc
from ir import format_errors, validate_ir


def _master(with_root_marker: bool) -> dict:
    row = {
        "type": "frame", "sourceKey": "row", "sourceMeta": {"kind": "dom", "componentBoundary": True},
        "frame": {"x": 120, "y": 300, "width": 420, "height": 96, "layout": "free"},
        "responsive": {"mobile": {"frame": {"x": 16, "y": 200, "width": 358, "height": 140}}},
        "children": [
            {"type": "text", "text": "CAMPAIGN SENDS / DAY", "frame": {"x": 0, "y": 0, "width": 200, "height": 20},
             "responsive": {"mobile": {"visible": False}}},
            {"type": "text", "text": "112 mailboxes · 28 domains", "frame": {"x": 0, "y": 8, "width": 300, "height": 20},
             "responsive": {"desktop": {"visible": False}, "tablet": {"visible": False}}},
            {"type": "text", "text": "40 mailboxes · 10 domains", "frame": {"x": 0, "y": 60, "width": 300, "height": 20}},
        ],
    }
    from design_system.builder import _tokens_for_ir, normalize_dna
    master = {"version": "1.1", "tokens": _tokens_for_ir(normalize_dna({})), "tree": [row]}
    if with_root_marker:
        master["responsive"] = {"viewports": {
            "desktop": {"width": 1440, "height": 900}, "tablet": {"width": 768, "height": 1024},
            "mobile": {"width": 390, "height": 844}}}
    return master


def test_preview_carries_component_sized_viewports_and_validates():
    for marker in (True, False):
        preview = dsdoc.preview_ir_for_master(_master(marker))
        assert format_errors(validate_ir(preview)) == [], marker
        viewports = preview["responsive"]["viewports"]
        assert viewports["desktop"] == {"width": 420, "height": 96}
        assert viewports["mobile"] == {"width": 358, "height": 140}
        assert preview["tree"][0]["frame"]["width"] == 420


def test_preview_without_overrides_has_no_marker():
    master = {"version": "1.1", "tokens": {}, "tree": [{
        "type": "frame", "frame": {"x": 5, "y": 5, "width": 100, "height": 40, "layout": "free"},
        "children": [{"type": "text", "text": "plain"}]}]}
    assert "responsive" not in dsdoc.preview_ir_for_master(master)


def test_rendered_preview_hides_other_viewport_clones():
    """Реальный engine.js: на desktop мобильный клон строки не рендерится."""
    import ir_render
    from playwright.sync_api import sync_playwright

    if not ir_render.RENDERER_JS.is_file():
        return
    preview = dsdoc.preview_ir_for_master(_master(False))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.set_content("<div id='host'></div>")
            page.add_script_tag(path=str(ir_render.RENDERER_JS))
            texts = page.evaluate(
                """(ir) => { const host = document.querySelector('#host');
                  window.IRRenderer.renderIR(host, ir, {fit: false, viewport: 'desktop', offline: true});
                  return { text: host.innerText, w: host.querySelector('[data-design-width]').dataset.designWidth }; }""",
                preview)
            assert "40 mailboxes" in texts["text"] and "CAMPAIGN SENDS" in texts["text"]
            assert "112 mailboxes" not in texts["text"], texts
            assert texts["w"] == "420", texts
            mobile = page.evaluate(
                """(ir) => { const host = document.querySelector('#host');
                  window.IRRenderer.renderIR(host, ir, {fit: false, viewport: 'mobile', offline: true});
                  return host.innerText; }""", preview)
            assert "112 mailboxes" in mobile and "CAMPAIGN SENDS" not in mobile, mobile
        finally:
            browser.close()
