"""meta.fontFaces: лимит схемы совпадает с лимитом захвата (scraper._resolve_font_faces = 48).

Регрессия slsbmb (2026-09-04): захват отдавал 16 faces, схема допускала 12 —
7 из 9 блоков Source Import падали на `meta/fontFaces ... is too long` ещё до
fidelity-гейта, и ДС оставалась без наблюдённых мастеров.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ir.validate import validate_ir  # noqa: E402

TOKENS = {
    "mode": "dark",
    "color": {"primary": "#5b6cff", "background": "#0a0a0e", "surface": "#0a0a0e",
              "text": "#f2f0ea", "textMuted": "#9d9aab", "border": "#1b1b1f"},
    "font": {"display": {"family": "Bricolage Grotesque", "weight": 700},
             "body": {"family": "Hanken Grotesk", "weight": 400}, "scale": "default"},
    "radius": {"card": "md", "button": "md", "input": "md"},
    "spacing": {"section": "md", "container": "default"},
    "shadow": "none",
}


def _face(i: int) -> dict:
    return {"family": "Hanken Grotesk" if i % 2 else "Bricolage Grotesque",
            "weight": str(100 + (i % 9) * 100), "style": "normal" if i % 3 else "italic",
            "url": f"/fonts/{i:032x}.woff2"}


def _ir(face_count: int) -> dict:
    return {"version": "1.1", "tokens": TOKENS,
            "meta": {"name": "Импорт: pricing", "fontFaces": [_face(i) for i in range(face_count)]},
            "tree": [{"id": "s", "type": "composition", "children": []}]}


def _font_errors(ir: dict) -> list:
    return [e for e in validate_ir(ir) if "fontFaces" in str(e.path)]


def test_capture_with_sixteen_faces_passes_schema():
    assert _font_errors(_ir(16)) == []


def test_schema_limit_matches_scraper_limit():
    import scraper
    limit = getattr(scraper, "MAX_FONT_FACES", 48)
    assert _font_errors(_ir(limit)) == []
    assert _font_errors(_ir(limit + 1)), "лимит схемы должен совпадать с лимитом захвата"
