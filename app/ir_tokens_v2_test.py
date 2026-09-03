"""tokens.v2: детерминированный вывод ролей из v1-токенов и валидность по схеме."""
from __future__ import annotations

import copy

import pytest

from ir.migrate import derive_tokens_v2, migrate_ir
from ir.validate import validate_ir


def _v1_tokens(**overrides) -> dict:
    tokens = {
        "mode": "light",
        "color": {"primary": "#0E7A5F", "secondary": "#134E48", "accent": "#E85D26",
                  "background": "#FFFFFF", "surface": "#F6F7F8", "text": "#17201D",
                  "textMuted": "#5D6B66", "border": "#E2E7E5"},
        "font": {"display": {"family": "Manrope", "weight": 800},
                 "body": {"family": "Inter", "weight": 400}, "scale": "default"},
        "radius": {"card": "lg", "button": "full", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "sm",
    }
    tokens.update(overrides)
    return tokens


def _ir(tokens: dict | None = None) -> dict:
    return {
        "version": "1.1",
        "tokens": tokens if tokens is not None else _v1_tokens(),
        "tree": [{"id": "hero-1", "type": "hero", "variant": "centered",
                  "props": {"heading": "Заголовок",
                            "ctaPrimary": {"text": "Начать"}}}],
    }


def test_all_v2_color_roles_are_derived_from_v1() -> None:
    v2 = derive_tokens_v2(_v1_tokens())

    assert set(v2["color"]) == {
        "bg", "bg2", "surface", "surface2", "ink", "ink2", "inkMuted",
        "line", "accent", "accentInk", "accent2",
    }
    # Роли, у которых есть прямой v1-предшественник, переносятся один в один —
    # иначе миграция меняла бы вид уже сохранённых проектов.
    assert v2["color"]["bg"] == "#ffffff"
    assert v2["color"]["surface"] == "#f6f7f8"
    assert v2["color"]["ink"] == "#17201d"
    assert v2["color"]["inkMuted"] == "#5d6b66"
    assert v2["color"]["line"] == "#e2e7e5"
    assert v2["color"]["accent"] == "#0e7a5f"
    assert v2["color"]["accent2"] == "#134e48"
    # Интерполированные роли лежат между своими источниками, а не совпадают с ними.
    assert v2["color"]["bg2"] not in (v2["color"]["bg"], v2["color"]["surface"])
    assert v2["color"]["accentInk"] == "#ffffff"


def test_surface_equal_to_background_is_separated() -> None:
    """`surface == background` — известный дефект извлечения ДС: белое на белом."""
    tokens = _v1_tokens()
    tokens["color"]["surface"] = tokens["color"]["background"]

    v2 = derive_tokens_v2(tokens)

    assert v2["color"]["surface"] != v2["color"]["bg"]


def test_type_scale_follows_base_and_ratio_from_v1_scale() -> None:
    v2 = derive_tokens_v2(_v1_tokens())
    roles = v2["type"]["roles"]
    base, ratio = v2["type"]["base"], v2["type"]["ratio"]

    assert set(roles) == {"display", "h1", "h2", "h3", "lead", "body", "small", "eyebrow"}
    assert base == 16.0
    assert roles["body"]["size"] == base
    assert roles["h1"]["size"] == round(base * ratio ** 3)
    # Монотонная лестница: каждая роль крупнее следующей.
    ladder = [roles[name]["size"] for name in
              ("display", "h1", "h2", "h3", "lead", "body", "small")]
    assert ladder == sorted(ladder, reverse=True)
    # Заголовки берут вес display-шрифта, текст — body.
    assert roles["h1"]["weight"] == 800
    assert roles["body"]["weight"] == 400
    assert roles["eyebrow"]["tracking"] > 0


@pytest.mark.parametrize("scale,expected_base", [("compact", 15.0), ("default", 16.0), ("spacious", 17.0)])
def test_compact_and_spacious_scales_change_the_base(scale: str, expected_base: float) -> None:
    tokens = _v1_tokens()
    tokens["font"]["scale"] = scale

    v2 = derive_tokens_v2(tokens)

    assert v2["type"]["base"] == expected_base


def test_families_carry_a_fallback_stack() -> None:
    v2 = derive_tokens_v2(_v1_tokens())

    assert v2["type"]["families"]["display"]["family"] == "Manrope"
    assert v2["type"]["families"]["display"]["stack"].endswith("sans-serif")
    assert "Manrope" in v2["type"]["families"]["display"]["stack"]


def test_space_radius_shadow_and_motion_ladders() -> None:
    v2 = derive_tokens_v2(_v1_tokens())

    assert v2["space"] == sorted(v2["space"])
    assert v2["space"][0] == 4 and v2["space"][-1] == 160
    assert set(v2["radius"]) == {"sm", "md", "lg", "pill"}
    assert v2["radius"]["sm"] < v2["radius"]["md"] < v2["radius"]["lg"] < v2["radius"]["pill"]
    assert set(v2["shadow"]) == {"sm", "md", "lg"}
    assert v2["motion"]["name"] == "fade-up"
    assert v2["motion"]["durationMs"] > 0


def test_shadow_none_stays_none_across_the_ladder() -> None:
    v2 = derive_tokens_v2(_v1_tokens(shadow="none"))

    assert v2["shadow"] == {"sm": "none", "md": "none", "lg": "none"}


def test_derivation_is_deterministic_and_does_not_mutate_input() -> None:
    tokens = _v1_tokens()
    original = copy.deepcopy(tokens)

    first, second = derive_tokens_v2(tokens), derive_tokens_v2(tokens)

    assert first == second
    assert tokens == original


def test_missing_v1_block_yields_no_v2() -> None:
    assert derive_tokens_v2({}) is None
    assert derive_tokens_v2({"color": {}}) is None
    assert derive_tokens_v2(None) is None


def test_migration_attaches_v2_without_mutating_the_original() -> None:
    ir = _ir()
    original = copy.deepcopy(ir)

    migrated = migrate_ir(ir, recorded_at="1970-01-01T00:00:00+00:00")

    assert ir == original
    assert "v2" not in ir["tokens"]
    assert migrated["tokens"]["v2"] == derive_tokens_v2(_v1_tokens())
    # Повторная миграция уже мигрированного документа даёт те же байты:
    # CAS-гвард живой сессии сравнивает именно их.
    again = migrate_ir(migrated, recorded_at="1970-01-01T00:00:00+00:00")
    assert again == migrated


def test_existing_v2_is_preserved_by_migration() -> None:
    ir = _ir()
    handmade = derive_tokens_v2(_v1_tokens())
    handmade["motion"]["durationMs"] = 120
    ir["tokens"]["v2"] = handmade

    migrated = migrate_ir(ir, recorded_at="1970-01-01T00:00:00+00:00")

    assert migrated["tokens"]["v2"]["motion"]["durationMs"] == 120


def test_migrated_document_validates_against_the_schema() -> None:
    migrated = migrate_ir(_ir(), recorded_at="1970-01-01T00:00:00+00:00")

    assert validate_ir(migrated) == []


def test_v1_only_document_stays_valid() -> None:
    """Обратная совместимость: без tokens.v2 документ по-прежнему валиден."""
    assert validate_ir(_ir()) == []
