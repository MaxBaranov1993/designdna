"""Каталог по уровням атомарного дизайна.

UI kit читается сверху вниз: неделимые элементы → их сочетания → собранные
блоки. Без этой оси каталог — плоская свалка, где кнопка лежит рядом с целой
секцией и непонятно, с чего начинать.
"""
from __future__ import annotations

from design_system.organizer import ATOMIC_LEVELS, atomic_level, deterministic_catalog


def _component(key: str, role: str, category: str, variants: int = 1) -> dict:
    return {
        "componentKey": key, "canonicalRole": role, "category": category,
        "name": key.replace("-", " ").title(), "origin": "observed", "status": "verified",
        "masterIr": {"tree": [{"type": "card"}]},
        "variants": {f"v{index}": {} for index in range(variants)},
        "states": {},
    }


def _document() -> dict:
    return {
        "id": "ds-atomic",
        "components": {
            "button": _component("button", "button", "actions", variants=3),
            "search-field": _component("search-field", "search-field", "forms"),
            "service-card": _component("service-card", "service-card", "surfaces", variants=2),
            "footer-navigation": _component("footer-navigation", "footer-navigation", "navigation"),
        },
    }


def test_roles_map_to_the_three_atomic_levels():
    assert atomic_level({"canonicalRole": "button"}) == "atoms"
    assert atomic_level({"canonicalRole": "search-field"}) == "molecules"
    assert atomic_level({"canonicalRole": "service-card"}) == "organisms"


def test_unknown_roles_fall_back_by_category_then_to_organisms():
    # Категория — вторая подсказка после роли.
    assert atomic_level({"canonicalRole": "unheard-of", "category": "actions"}) == "atoms"
    # Ничего не известно: показываем как сборный блок, а не выдаём за примитив.
    assert atomic_level({"canonicalRole": "unheard-of", "category": "unheard-of"}) == "organisms"
    assert atomic_level({}) == "organisms"


def test_catalog_exposes_levels_in_reading_order():
    catalog = deterministic_catalog(_document())
    keys = [level["key"] for level in catalog["levels"]]
    assert keys == [key for key, _, _ in ATOMIC_LEVELS if key in keys]
    assert keys[0] == "atoms", "кит читается от простого к составному"
    by_level = {level["key"]: level["componentKeys"] for level in catalog["levels"]}
    assert by_level["atoms"] == ["button"]
    assert by_level["molecules"] == ["search-field"]
    assert set(by_level["organisms"]) == {"service-card", "footer-navigation"}


def test_every_component_lands_in_exactly_one_level():
    catalog = deterministic_catalog(_document())
    placed = [key for level in catalog["levels"] for key in level["componentKeys"]]
    assert sorted(placed) == sorted(catalog["componentMeta"])
    assert len(placed) == len(set(placed)), "компонент не должен попадать в два уровня"


def test_meta_carries_variant_and_state_counts_for_the_card():
    meta = deterministic_catalog(_document())["componentMeta"]
    assert meta["button"]["variantCount"] == 3
    assert meta["service-card"]["variantCount"] == 2
    assert meta["button"]["stateCount"] == 0
    assert meta["button"]["atomicLevel"] == "atoms"


def test_sections_and_levels_are_independent_axes():
    """Секция отвечает «где искать», уровень — «насколько сложен»."""
    catalog = deterministic_catalog(_document())
    sections = {key for section in catalog["sections"] for key in section["componentKeys"]}
    levels = {key for level in catalog["levels"] for key in level["componentKeys"]}
    assert sections == levels
