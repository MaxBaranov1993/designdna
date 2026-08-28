"""Шрифты источника доезжают от блока до превью компонента.

Регрессия: @font-face рендерер берёт ТОЛЬКО из ir.meta.fontFaces. Мастер
компонента вырезается из дерева блока, а meta оставалась у блока — поэтому
каждое превью в UI Kit рисовалось системным шрифтом вместо шрифта сайта.
"""
from __future__ import annotations

from design_system import builder
from design_system.document import preview_ir_for_master

FACES = [
    {"family": "Bricolage Grotesque", "weight": "400 800", "style": "normal",
     "url": "/fonts/4db0462067345fe6.woff2"},
    {"family": "Hanken Grotesk", "weight": "400", "style": "normal",
     "url": "/fonts/6748e3a477b39cc0.woff2"},
]


def _block() -> dict:
    card = {
        "type": "card", "sourceKey": "card-1",
        "style": {"background": "#101014", "borderRadius": 12,
                  "fontFamily": "Bricolage Grotesque"},
        "frame": {"width": 240, "height": 180},
        "sourceMeta": {"componentBoundary": True, "componentRole": "article",
                       "componentLabel": "Product card", "repeatGroup": "cards"},
        "children": [
            {"type": "image", "sourceKey": "card-1-img"},
            {"type": "heading", "text": "Card", "sourceKey": "card-1-h",
             "style": {"fontFamily": "Bricolage Grotesque"}},
        ],
    }
    return {
        "name": "grid", "label": "Grid", "kind": "product-grid",
        "selector": "body > section",
        "ir": {
            "version": "1.1",
            "tokens": {"color": {"primary": "#7018e6"}},
            "meta": {"fontFaces": FACES},
            "tree": [{"type": "source-block", "sourceKey": "root",
                      "frame": {"width": 1200, "height": 400},
                      "children": [card, {**card, "sourceKey": "card-2"},
                                   {**card, "sourceKey": "card-3"}]}],
        },
        "fidelityReport": {"components": {}},
        "sizes": {"desktop": {"width": 1200, "height": 400}},
    }


def _document() -> dict:
    block = _block()
    pack = builder.build_source_pack(
        {"blocks": [block], "tokens": {}, "url": "https://example.com"}, source_node_id=7)
    pack["_raw_blocks"] = [block]
    return builder.build_draft(pack, name="UI Kit · fonts")


def test_component_masters_carry_the_captured_font_faces():
    doc = _document()
    pools = [doc.get("components") or {}, doc.get("reviewComponents") or {},
             doc.get("suggestions") or {}]
    masters = [component for pool in pools for component in pool.values()
               if isinstance(component, dict) and isinstance(component.get("masterIr"), dict)]
    assert masters, "черновик обязан содержать хотя бы один exact master"
    for component in masters:
        faces = (component["masterIr"].get("meta") or {}).get("fontFaces")
        assert faces, f"{component.get('componentKey')} потерял fontFaces"
        assert {face["family"] for face in faces} == {"Bricolage Grotesque", "Hanken Grotesk"}


def test_preview_wrapper_keeps_font_faces():
    master = {"version": "1.1", "tokens": {}, "meta": {"fontFaces": FACES},
              "tree": [{"type": "card", "frame": {"width": 240, "height": 180}, "children": []}]}
    preview = preview_ir_for_master(master)
    faces = (preview.get("meta") or {}).get("fontFaces")
    assert faces == FACES, "обёртка превью не должна терять meta.fontFaces"


def test_master_without_fonts_stays_clean():
    master = {"version": "1.1", "tokens": {},
              "tree": [{"type": "card", "frame": {"width": 10, "height": 10}, "children": []}]}
    preview = preview_ir_for_master(master)
    assert "meta" not in preview or not preview["meta"]
