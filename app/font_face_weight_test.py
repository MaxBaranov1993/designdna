"""meta.fontFaces weights: a variable range survives request sanitizing.

Regression (glebkudr.com, 2026-09-23): the Quality Pass sanitizer collapsed
"100 900" to "100", and the generated section rendered every heading at the
thinnest instance of the variable font.
"""
from __future__ import annotations

from api.common import sanitize_font_face_weights
from ir.validate import validate_ir


def _doc(weight: str) -> dict:
    return {"version": "1.1", "meta": {"name": "x", "fontFaces": [
        {"family": "commissioner", "weight": weight, "style": "normal", "url": "/fonts/a3f9a71f0111d2b2.woff2"}]},
        "tokens": {}, "tree": []}


def test_variable_range_is_kept() -> None:
    assert sanitize_font_face_weights(_doc("100 900"))["meta"]["fontFaces"][0]["weight"] == "100 900"


def test_off_grid_values_are_rounded_to_a_valid_range() -> None:
    doc = sanitize_font_face_weights(_doc("350 850"))
    assert doc["meta"]["fontFaces"][0]["weight"] == "400 800"
    assert not [e for e in validate_ir(doc) if "fontFaces" in str(e)]
    assert sanitize_font_face_weights(_doc("380"))["meta"]["fontFaces"][0]["weight"] == "400"
