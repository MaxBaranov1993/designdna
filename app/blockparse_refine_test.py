"""AI-уточнение разбора Source: границы того, что модели разрешено менять.

Уточнение работает поверх уже измеренного захвата, поэтому единственная
гарантия, которая здесь важна: модель не может тронуть геометрию, стиль или
структуру IR — только подписи и роль блока. Иначе через этот маршрут можно
было бы обойти fidelity-гейт.
"""
from __future__ import annotations

import copy

import blockparse


def _block() -> dict:
    return {
        "name": "product-grid",
        "label": "Section",
        "kind": "section",
        "selector": "body > section",
        "ir": {
            "tree": [{
                "type": "source-block",
                "sourceKey": "root",
                "frame": {"width": 1200, "height": 400},
                "children": [{
                    "type": "card",
                    "sourceKey": "card-1",
                    "style": {"background": "#ffffff"},
                    "frame": {"width": 230, "height": 286},
                    "sourceMeta": {"componentBoundary": True, "componentRole": "article",
                                   "componentLabel": "article: image + text"},
                }],
            }],
        },
    }


def test_renames_apply_to_blocks_and_components():
    blocks, applied = blockparse.apply_refinements([_block()], [
        {"op": "rename-block", "block": "product-grid", "label": "Каталог товаров"},
        {"op": "set-block-role", "block": "product-grid", "role": "product-grid"},
        {"op": "rename-component", "block": "product-grid", "sourceKey": "card-1",
         "label": "Product card"},
    ])
    assert blocks[0]["label"] == "Каталог товаров"
    assert blocks[0]["kind"] == "product-grid"
    node = blocks[0]["ir"]["tree"][0]["children"][0]
    assert node["sourceMeta"]["componentLabel"] == "Product card"
    assert len(applied) == 3


def test_geometry_and_style_survive_refinement():
    original = _block()
    before = copy.deepcopy(original["ir"])
    blocks, _ = blockparse.apply_refinements([original], [
        {"op": "rename-component", "block": "product-grid", "sourceKey": "card-1", "label": "Card"},
    ])
    node = blocks[0]["ir"]["tree"][0]["children"][0]
    reference = before["tree"][0]["children"][0]
    assert node["frame"] == reference["frame"]
    assert node["style"] == reference["style"]
    assert node["type"] == reference["type"]


def test_unknown_operations_and_targets_are_ignored():
    blocks, applied = blockparse.apply_refinements([_block()], [
        {"op": "delete-block", "block": "product-grid"},
        {"op": "set-frame", "block": "product-grid", "frame": {"width": 1}},
        {"op": "rename-block", "block": "does-not-exist", "label": "X"},
        {"op": "rename-component", "block": "product-grid", "sourceKey": "missing", "label": "X"},
        {"op": "set-block-role", "block": "product-grid", "role": "not-a-role"},
        "not-an-object",
    ])
    assert applied == []
    assert blocks[0]["label"] == "Section"
    assert blocks[0]["kind"] == "section"


def test_empty_labels_are_rejected():
    blocks, applied = blockparse.apply_refinements([_block()], [
        {"op": "rename-block", "block": "product-grid", "label": "   "},
        {"op": "rename-component", "block": "product-grid", "sourceKey": "card-1", "label": ""},
    ])
    assert applied == []
    assert blocks[0]["label"] == "Section"


def test_ambiguities_report_what_heuristics_could_not_decide():
    block = _block()
    items = blockparse.collect_ambiguities([block])
    kinds = {item["type"] for item in items}
    # kind == "section" — роль не определена; componentLabel вида "role: ..." —
    # имя выведено из формы содержимого, а не из разметки.
    assert "block-role" in kinds
    assert "unnamed-components" in kinds
    unnamed = next(item for item in items if item["type"] == "unnamed-components")
    assert unnamed["sourceKeys"] == ["card-1"]


def test_named_component_with_resolved_role_is_not_ambiguous():
    block = _block()
    block["kind"] = "product-grid"
    node = block["ir"]["tree"][0]["children"][0]
    node["sourceMeta"]["componentLabel"] = "Product card"
    assert blockparse.collect_ambiguities([block]) == []


def test_truncation_is_reported_instead_of_silently_dropped():
    block = _block()
    block["truncatedAfter"] = 5
    items = blockparse.collect_ambiguities([block])
    truncated = next(item for item in items if item["type"] == "truncated")
    assert truncated["dropped"] == 5
