"""sanitize_generated_ir: выдуманные src у картинок → заглушка с imagePrompt."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ir import sanitize_generated_ir


def _ir(children: list, props: dict | None = None) -> dict:
    return {"version": "1.1", "tree": [{"type": "hero", "props": props or {}, "children": children}]}


def test_invented_http_src_becomes_placeholder():
    out = sanitize_generated_ir(_ir([{"type": "image", "src": "https://images.example.com/hero.jpg", "alt": "Панель"}]))
    img = out["tree"][0]["children"][0]
    assert "src" not in img
    assert img["imagePrompt"] == "Панель"
    assert img["alt"] == "Панель"


def test_relative_src_dropped_but_prompt_kept():
    out = sanitize_generated_ir(_ir([{"type": "image", "src": "/assets/hero.png", "imagePrompt": "Дашборд в тёмной теме"}]))
    img = out["tree"][0]["children"][0]
    assert "src" not in img
    assert img["imagePrompt"] == "Дашборд в тёмной теме"


def test_embedded_and_internal_sources_survive():
    data_url = "data:image/png;base64,iVBORw0KGgo="
    out = sanitize_generated_ir(_ir([
        {"type": "image", "src": data_url},
        {"type": "image", "src": "ddna://blobs/hero.png"},
    ]))
    kids = out["tree"][0]["children"]
    assert kids[0]["src"] == data_url
    assert kids[1]["src"] == "ddna://blobs/hero.png"


def test_hero_media_prop_is_sanitized_and_non_images_untouched():
    out = sanitize_generated_ir(_ir(
        [{"type": "button", "src": "https://not-an-image", "text": "Купить"}],
        props={"media": {"src": "https://cdn.example.com/x.jpg", "alt": "Превью"}},
    ))
    section = out["tree"][0]
    assert "src" not in section["props"]["media"]
    assert section["props"]["media"]["imagePrompt"] == "Превью"
    # не-image узлы не трогаем: src у кнопки — не наша забота, схема скажет сама
    assert section["children"][0]["src"] == "https://not-an-image"
