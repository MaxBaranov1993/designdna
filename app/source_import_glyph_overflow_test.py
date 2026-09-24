"""Glyphs of a zero-height box and line-height:normal survive Source Import.

Regression from glebkudr.com: the CTA arrow lives in `<span>` with
`height:0; line-height:0` and paints as overflow; the compiler treated the box as
invisible and dropped the arrow. `<pre>` trace rows aligned columns with
runs of spaces that the compiler collapsed. Button labels with `line-height: normal` had no
lineHeight in IR, the renderer inherited 1.6 and pushed the label below its box.
"""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import scraper
from scraper import capture_block_irs

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _walk(node):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _capture(monkeypatch) -> dict:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(FIXTURES)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(scraper, "validate_public_url", lambda _url: None)
    try:
        live = capture_block_irs(
            f"http://127.0.0.1:{server.server_port}/source_import_glyph_overflow.html",
            [{"name": "cta", "label": "CTA", "kind": "cta", "selector": "#cta-section"}], timeout_ms=30000)
    finally:
        server.shutdown()
        server.server_close()
    return live["#cta-section"]["ir"]


def test_zero_height_glyph_box_and_normal_line_height(monkeypatch) -> None:
    ir = _capture(monkeypatch)
    nodes = [node for root in ir["tree"] for node in _walk(root)]
    arrow = next((node for node in nodes if node.get("type") == "text" and node.get("text") == "→"), None)
    assert arrow is not None, "the overflowing arrow glyph is emitted as a text layer"
    assert arrow["frame"]["height"] >= 10 and arrow["frame"]["width"] >= 10, arrow["frame"]
    assert 0.5 <= arrow["style"]["lineHeight"] <= 3, "glyph line height comes from its rect, not the collapsed box"
    label = next(node for node in nodes if node.get("type") == "text" and "Discuss a pilot" in str(node.get("text")))
    line_height = label["style"].get("lineHeight")
    measured = label["frame"]["height"] / label["style"]["fontSize"]
    assert line_height is not None and abs(line_height - measured) < 0.05, (
        f"line-height:normal resolved from font metrics ({line_height}) matches the measured line ({measured:.3f})")


def test_preformatted_text_keeps_column_spacing(monkeypatch) -> None:
    ir = _capture(monkeypatch)
    rows = [node for root in ir["tree"] for node in _walk(root)
            if node.get("type") == "text" and str(node.get("text") or "").startswith("12:41")]
    lines = [line for node in sorted(rows, key=lambda n: n["frame"]["y"]) for line in node["text"].splitlines()]
    assert lines == ["12:41:09  load_context   ok", "12:41:15  plan           ok"]
    assert all(node["style"]["whiteSpace"] == "pre-wrap" for node in rows)


def test_tilted_card_stays_editable_and_keeps_its_rotation(monkeypatch) -> None:
    ir = _capture(monkeypatch)
    nodes = [node for root in ir["tree"] for node in _walk(root)]
    card = next(node for node in nodes if any("AGENT TRACE" in str(child.get("text")) for child in node.get("children") or []))
    assert card["type"] == "card" and card.get("editable") is not False
    assert card["frame"]["transform"].startswith("matrix("), "the rotation is replayed by the renderer"
    assert abs(card["frame"]["width"] - 332) <= 1 and abs(card["frame"]["height"] - 152) <= 1, (
        "geometry is the untransformed box, not the rotated bounding box")


def test_inline_svg_keeps_paint_set_by_css_classes(monkeypatch) -> None:
    from urllib.parse import unquote
    ir = _capture(monkeypatch)
    icons = [node for root in ir["tree"] for node in _walk(root)
             if node.get("type") == "image" and (node.get("sourceMeta") or {}).get("kind") == "svg"]
    assert icons, "the inline svg is captured"
    markup = unquote(icons[0]["src"].split(",", 1)[1])
    assert 'stroke="rgb(10, 103, 255)"' in markup, markup[:300]
