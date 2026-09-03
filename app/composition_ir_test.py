"""Блок `composition`, примитив `frame`, meta.direction и эталоны из app/exemplars."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from ir import format_errors, sanitize_generated_ir, validate_ir  # noqa: E402


EXEMPLARS = sorted((APP / "exemplars").glob("*.json"))

TOKENS = {
    "mode": "light",
    "color": {"primary": "#0F5C4A", "background": "#F3F5F2", "surface": "#FFFFFF",
              "text": "#14181A", "textMuted": "#55635F", "border": "#D8DED8"},
    "font": {"display": {"family": "Space Grotesk", "weight": 700},
             "body": {"family": "Inter", "weight": 400}, "scale": "default"},
    "radius": {"card": "md", "button": "sm", "input": "sm"},
    "spacing": {"section": "lg", "container": "default"},
    "shadow": "none",
}


def _document(section: dict, meta: dict | None = None) -> dict:
    doc = {"version": "1.1", "tokens": TOKENS, "tree": [section]}
    if meta is not None:
        doc["meta"] = meta
    return doc


def _errors(doc: dict) -> list[str]:
    return format_errors(validate_ir(doc))


def test_composition_section_with_frame_tree_is_valid():
    section = {
        "id": "manifest", "type": "composition", "variant": "offset-diptych",
        "props": {"background": "surface", "density": "airy", "heading": "Как мы работаем"},
        "children": [{
            "type": "frame",
            "frame": {"layout": "auto", "direction": "row", "gap": 64, "align": "start"},
            "children": [
                {"type": "frame",
                 "frame": {"layout": "auto", "direction": "column", "gap": 16, "width": 420},
                 "children": [{"type": "heading", "level": 2, "text": "Тезис"},
                              {"type": "text", "text": "Пояснение"},
                              {"type": "divider"}]},
                {"type": "image", "alt": "Цех", "imagePrompt": "Цех в холодном свете"},
            ],
        }],
    }
    assert _errors(_document(section)) == []


def test_composition_accepts_free_canvas_children():
    section = {
        "id": "canvas", "type": "composition", "variant": "poster-free",
        "props": {"background": "none"},
        "frame": {"width": "fill", "height": 480, "layout": "free"},
        "children": [{"type": "frame", "frame": {"x": 80, "y": 40, "width": 320, "height": 200},
                      "children": [{"type": "text", "text": "Слой"}]}],
    }
    assert _errors(_document(section)) == []


def test_composition_props_are_closed_and_token_only():
    base = {"id": "manifest", "type": "composition", "variant": "x", "children": []}
    assert _errors(_document({**base, "props": {"background": "#ff0000"}})), "сырой hex должен отвергаться"
    assert _errors(_document({**base, "props": {"tagline": "нет такого поля"}})), "props закрыт"
    assert _errors(_document({**base, "props": {"density": "loose"}})), "density — закрытый enum"


def test_meta_direction_contract():
    section = {"id": "s", "type": "composition", "variant": "x", "props": {}, "children": []}
    direction = {"name": "Каталог-витрина",
                 "motivation": "покупатель приходит за товаром",
                 "tradeoff": "бренд звучит тише"}
    assert _errors(_document(section, {"direction": direction})) == []
    for missing in ("name", "motivation", "tradeoff"):
        partial = {k: v for k, v in direction.items() if k != missing}
        assert _errors(_document(section, {"direction": partial})), f"{missing} обязателен"


def test_sanitize_keeps_meta_direction():
    """meta режется белым списком — направление варианта должно его пережить."""
    direction = {"name": "Диспетчерская", "motivation": "мотив", "tradeoff": "цена"}
    section = {"id": "s", "type": "composition", "variant": "x", "props": {}, "children": []}
    out = sanitize_generated_ir(_document(section, {"direction": direction, "выдумка": 1}))
    assert out["meta"] == {"direction": direction}


@pytest.mark.parametrize("path", EXEMPLARS, ids=lambda p: p.stem)
def test_exemplar_is_valid_ir(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert _errors(doc) == []


@pytest.mark.parametrize("path", EXEMPLARS, ids=lambda p: p.stem)
def test_exemplar_survives_sanitize_unchanged(path: Path):
    """Эталон — уже чистый IR: sanitize не должен ничего в нём чинить."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert sanitize_generated_ir(doc) == doc


@pytest.mark.parametrize("path", EXEMPLARS, ids=lambda p: p.stem)
def test_exemplar_carries_direction_composition_and_art_direction(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    direction = doc["meta"]["direction"]
    assert set(direction) == {"name", "motivation", "tradeoff"}

    sections = doc["tree"]
    assert any(s["type"] == "composition" for s in sections), "эталон без свободной композиции"

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get("children") or [])

    images = [n for n in walk(sections) if n.get("type") == "image"]
    images += [s["props"]["media"] for s in sections if isinstance(s.get("props"), dict)
               and isinstance(s["props"].get("media"), dict)]
    assert images, "эталон без изображений не показывает арт-дирекцию"
    for image in images:
        assert len(image.get("imagePrompt", "")) >= 60, image
        assert "src" not in image, "у эталона не бывает выдуманного src"


def test_exemplars_cover_the_new_variants():
    """Новые варианты живут не только в BLOCKS.md, но и в эталонах."""
    used = {
        (section["type"], section["variant"])
        for path in EXEMPLARS
        for section in json.loads(path.read_text(encoding="utf-8"))["tree"]
    }
    for pair in [("hero", "numbered"), ("hero", "poster"), ("hero", "editorial-stack"),
                 ("feature-grid", "list-rail"), ("feature-grid", "bento-asym"),
                 ("feature-grid", "two-col-manifest")]:
        assert pair in used, f"вариант {pair} не показан ни в одном эталоне"
