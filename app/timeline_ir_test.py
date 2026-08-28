"""Контракт Timeline IR: схема, детерминированное извлечение слоёв, change-sets."""
from __future__ import annotations

import copy

import pytest

from ir import (
    build_timeline,
    build_timeline_change_set,
    apply_timeline_change_set,
    revert_timeline_change_set,
    extract_timeline_layers,
    validate_timeline,
    validate_timeline_change_set,
    timeline_preset_operations,
    content_hash,
)
from ir.timeline import TimelineIR, PRESET_NAMES


def design_ir_fixture() -> dict:
    return {
        "version": "1.1",
        "frame": {"width": 1440},
        "tokens": {
            "mode": "light",
            "color": {"primary": "#3366ff", "background": "#ffffff", "surface": "#f5f6f8",
                      "text": "#101318", "textMuted": "#5c6470", "border": "#e3e6ea"},
            "font": {"display": {"family": "Inter", "weight": 700},
                     "body": {"family": "Inter", "weight": 400}, "scale": "default"},
            "radius": {"card": "lg", "button": "md", "input": "md"},
            "spacing": {"section": "lg", "container": "default"},
            "shadow": "sm",
        },
        "tree": [
            {
                "id": "hero-1",
                "sourceKey": "src-hero-1",
                "type": "hero",
                "variant": "center",
                "props": {"heading": "Продукт", "subheading": "Описание"},
                "children": [
                    {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button",
                     "text": "Начать"},
                    {"id": "hero-img", "sourceKey": "src-hero-img", "type": "image",
                     "src": "hero.png"},
                ],
            },
            {
                "id": "features-1",
                "type": "feature-grid",
                "variant": "cards",
                "props": {"title": "Возможности"},
                "children": [
                    {"id": "card-1", "type": "card", "title": "Быстро"},
                    {"id": "card-locked", "type": "image", "editable": False,
                     "lockedReason": "raster-fallback"},
                ],
            },
        ],
    }


def test_build_produces_valid_timeline() -> None:
    document = build_timeline(design_ir_fixture(), {"duration": 8000})
    assert validate_timeline(document) == []
    assert document["version"] == "timeline-ir/1.0"
    assert document["composition"]["duration"] == 8000
    assert document["composition"]["aspect"] == "16:9"
    assert document["source"]["designIrHash"] == content_hash(design_ir_fixture())


def test_layer_groups_cover_sections_and_children() -> None:
    document = build_timeline(design_ir_fixture())
    groups = {g["id"] for g in document["groups"]}
    assert groups == {"grp-hero-1", "grp-features-1"}
    layers = {layer["id"]: layer for layer in document["layers"]}
    assert "layer-hero-1" in layers
    assert layers["layer-hero-1"]["ref"] == "src-hero-1"
    assert layers["layer-hero-1"]["parent"] == "grp-hero-1"
    child_layers = [layer for layer in document["layers"] if layer["parent"] == "grp-hero-1"]
    # секция + два её ребёнка
    assert len(child_layers) == 3
    assert all(layer["out"] == document["composition"]["duration"] for layer in document["layers"])


def test_locked_elements_become_locked_layers() -> None:
    document = build_timeline(design_ir_fixture())
    locked = [layer for layer in document["layers"] if layer.get("locked")]
    assert len(locked) == 1
    assert locked[0]["ref"] == "card-locked"


def test_extraction_is_deterministic() -> None:
    first = extract_timeline_layers(design_ir_fixture())
    second = extract_timeline_layers(design_ir_fixture())
    assert first["manifestHash"] == second["manifestHash"]
    changed = design_ir_fixture()
    changed["tree"][0]["children"].append({"id": "extra", "type": "badge"})
    third = extract_timeline_layers(changed)
    assert third["manifestHash"] != first["manifestHash"]


def test_validate_catches_structural_errors() -> None:
    document = build_timeline(design_ir_fixture())
    broken = copy.deepcopy(document)
    broken["layers"][0]["in"] = broken["layers"][0]["out"]
    errors = validate_timeline(broken)
    assert any("in must be less than out" in error for error in errors)

    broken = copy.deepcopy(document)
    broken["layers"][0]["parent"] = "grp-unknown"
    errors = validate_timeline(broken)
    assert any("parent: group does not exist" in error for error in errors)

    broken = copy.deepcopy(document)
    broken["layers"][0]["transform"]["properties"]["opacity"] = {
        "keyframes": [{"t": 500, "value": 1.5}]}
    errors = validate_timeline(broken)
    assert any("opacity" in error and "[0, 1]" in error for error in errors)

    broken = copy.deepcopy(document)
    broken["layers"][0]["transform"]["properties"]["x"] = {
        "keyframes": [{"t": 100, "value": 0}, {"t": 100, "value": 10}]}
    errors = validate_timeline(broken)
    assert any("strictly ascending" in error for error in errors)

    broken = copy.deepcopy(document)
    broken["layers"][0]["transform"]["properties"]["x"] = {
        "keyframes": [{"t": 100, "value": 0, "easing": "cubic-bezier"}]}
    errors = validate_timeline(broken)
    assert any("cubic-bezier requires bezier handle" in error for error in errors)


def test_change_set_apply_and_revert_roundtrip() -> None:
    document = build_timeline(design_ir_fixture(), {"duration": 8000})
    operations = timeline_preset_operations("fade-in-up", ["layer-hero-1"], {"start": 0, "duration": 600})
    change_set = build_timeline_change_set(document, "интро героя", operations)
    assert validate_timeline_change_set(change_set) == []
    forward_ids = {op["id"] for op in change_set["operations"]}
    assert all(inv["inverseOf"] in forward_ids for inv in change_set["inverseOperations"])

    applied = apply_timeline_change_set(document, change_set)
    hero = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1")
    assert hero["transform"]["properties"]["opacity"]["keyframes"][0]["value"] == 0
    assert hero["transform"]["properties"]["y"]["keyframes"][0]["value"] > 0

    reverted = revert_timeline_change_set(applied, change_set)
    hero_after = next(layer for layer in reverted["layers"] if layer["id"] == "layer-hero-1")
    assert hero_after["transform"]["properties"] == {}


def test_change_set_rejects_stale_base_hash() -> None:
    document = build_timeline(design_ir_fixture())
    operations = timeline_preset_operations("fade-in", ["layer-hero-1"], {"start": 0, "duration": 400})
    change_set = build_timeline_change_set(document, "фейд", operations)
    mutated = copy.deepcopy(document)
    mutated["composition"]["duration"] = 9000
    mutated["layers"] = [
        {**layer, "out": 9000} for layer in mutated["layers"]
    ]
    assert validate_timeline(mutated) == []
    with pytest.raises(ValueError, match="baseTimelineHash"):
        apply_timeline_change_set(mutated, change_set)


def test_apply_preset_operation_expands_deterministically() -> None:
    document = build_timeline(design_ir_fixture(), {"duration": 8000})
    # layer-hero-1-1 — первый ребёнок секции hero (CTA-кнопка)
    change_set = build_timeline_change_set(document, "пульс CTA", [{
        "kind": "apply-preset",
        "target": "layer-hero-1-1",
        "payload": {"preset": "cta-pulse", "layerIds": ["layer-hero-1-1"],
                    "params": {"start": 1000, "duration": 800}},
    }])
    applied = apply_timeline_change_set(document, change_set)
    cta = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1-1")
    scale = cta["transform"]["properties"]["scale"]["keyframes"]
    assert [kf["value"] for kf in scale] == [1, 1.08, 1]
    reverted = revert_timeline_change_set(applied, change_set)
    cta_after = next(layer for layer in reverted["layers"] if layer["id"] == "layer-hero-1-1")
    assert cta_after["transform"]["properties"] == {}


def test_manual_keyframe_operation_via_change_set() -> None:
    document = build_timeline(design_ir_fixture(), {"duration": 8000})
    change_set = build_timeline_change_set(document, "ручной кейфрейм", [{
        "kind": "set-keyframes",
        "target": "layer-features-1",
        "path": "/transform/properties/rotation",
        "value": {"keyframes": [
            {"t": 0, "value": 0, "easing": "ease-in-out"},
            {"t": 2000, "value": 3, "easing": "ease-in-out"},
            {"t": 4000, "value": 0},
        ]},
    }])
    applied = apply_timeline_change_set(document, change_set)
    layer = next(item for item in applied["layers"] if item["id"] == "layer-features-1")
    assert len(layer["transform"]["properties"]["rotation"]["keyframes"]) == 3
    assert validate_timeline(applied) == []


def test_composition_edit_via_change_set() -> None:
    document = build_timeline(design_ir_fixture(), {"duration": 8000})
    change_set = build_timeline_change_set(document, "формат сторис", [
        {"kind": "set-composition", "target": "composition", "path": "/width", "value": 1080},
        {"kind": "set-composition", "target": "composition", "path": "/height", "value": 1920},
        {"kind": "set-composition", "target": "composition", "path": "/aspect", "value": "9:16"},
    ])
    applied = apply_timeline_change_set(document, change_set)
    assert applied["composition"]["width"] == 1080
    assert applied["composition"]["aspect"] == "9:16"
    reverted = revert_timeline_change_set(applied, change_set)
    assert reverted["composition"]["width"] == 1920


def test_all_presets_produce_valid_documents() -> None:
    document = build_timeline(design_ir_fixture(), {"duration": 8000})
    targets = ["layer-hero-1", "layer-features-1"]
    for preset in PRESET_NAMES:
        operations = timeline_preset_operations(preset, targets, {"start": 0, "duration": 600, "staggerMs": 150})
        change_set = build_timeline_change_set(document, f"пресет {preset}", operations)
        applied = apply_timeline_change_set(document, change_set)
        assert validate_timeline(applied) == [], preset


def test_empty_timeline_helper() -> None:
    empty = TimelineIR.empty("9:16")
    assert empty["composition"]["width"] == 1080
    assert empty["composition"]["height"] == 1920
    # пустой таймлайн валиден по схеме (слои появятся из входов ноды)
    assert validate_timeline(dict(empty)) == []
