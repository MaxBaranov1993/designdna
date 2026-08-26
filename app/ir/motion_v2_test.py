"""Focused production checks for Motion IR 2.0 validation and migration."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ir.motion_v2 import migrate_motion_v1_to_v2, motion_v2_content_hash, validate_motion_v2  # noqa: E402


def check(name: str, condition: bool, detail: Any = "") -> None:
    print(("[OK] " if condition else "[FAIL] ") + name)
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def clip(clip_id: str, start: float, duration: float) -> dict[str, Any]:
    return {"id": clip_id, "start": start, "duration": duration, "in": 0, "out": duration}


def valid_v2() -> dict[str, Any]:
    revision = "design-revision-42"
    return {
        "version": "2.0",
        "source": {
            "interactionHash": "a" * 64,
            "baseDesignIrHash": "b" * 64,
            "baseDesignIrRevision": revision,
        },
        "composition": {
            "id": "comp-main", "name": "Product walkthrough", "width": 1920, "height": 1080,
            "fps": 30, "duration": 8, "background": "#111116", "colorSpace": "srgb",
            "layers": [
                {
                    "id": "layer-scene", "type": "scene", "name": "Checkout", "parentId": None,
                    "enabled": True, "locked": False, "sourceKey": "checkout/root",
                    "designIrRevision": revision, "clips": [clip("clip-scene", 0, 8)],
                    "properties": [{
                        "id": "property-opacity", "propertyPath": "opacity", "valueType": "number",
                        "keyframes": [
                            {"time": 0, "value": 0, "interpolation": "linear"},
                            {"time": 1, "value": 1, "interpolation": "bezier", "bezierHandles": {"in": [0.2, 0], "out": [0.8, 1]}},
                        ],
                    }],
                    "masks": [],
                },
                {
                    "id": "layer-image", "type": "image", "name": "Product", "parentId": None,
                    "enabled": True, "locked": False, "assetId": "asset-image",
                    "clips": [clip("clip-image", 1, 5)], "properties": [],
                    "masks": [{"id": "mask-image", "mode": "add", "inverted": False, "path": "M0 0H1V1Z", "opacity": 1, "feather": 0}],
                },
                {
                    "id": "layer-precomp", "type": "group", "name": "CTA", "parentId": None,
                    "enabled": True, "locked": False, "nestedCompositionId": "comp-cta",
                    "clips": [clip("clip-precomp", 2, 3)], "properties": [], "masks": [],
                },
            ],
        },
        "compositions": [{
            "id": "comp-cta", "name": "CTA", "width": 800, "height": 300, "fps": 30,
            "duration": 3, "background": "#00000000", "colorSpace": "srgb",
            "layers": [{
                "id": "layer-cta", "type": "design", "name": "CTA", "parentId": None,
                "enabled": True, "locked": False, "sourceKey": "checkout/submit",
                "designIrRevision": revision, "clips": [clip("clip-cta", 0, 3)],
                "properties": [], "masks": [],
            }],
        }],
        "markers": [{"id": "marker-cta", "time": 4, "label": "CTA"}],
        "captions": [{"id": "caption-1", "start": 1, "duration": 2, "text": "Buy now", "language": "en"}],
        "assets": [{"id": "asset-image", "type": "image", "hash": "c" * 64, "mime": "image/png", "uri": "assets/product.png"}],
        "renderSettings": {
            "format": "mp4", "codec": "h264", "quality": "high",
            "resolution": {"width": 1920, "height": 1080}, "fps": 30,
            "audio": {"enabled": False, "sampleRate": 48000, "channels": 2, "bitrateKbps": 192},
        },
    }


def valid_v1() -> dict[str, Any]:
    return {
        "version": "1.0",
        "source": {"interactionHash": "a" * 64, "baseDesignIrHash": "b" * 64},
        "composition": {"width": 1920, "height": 1080, "fps": 30, "duration": 8000, "background": "#111116"},
        "scenes": [{
            "id": "motion-scene-1", "interactionSceneId": "scene-1", "start": 0, "duration": 8000,
            "viewport": "desktop", "transition": {"type": "cut", "duration": 0, "easing": "linear"},
        }],
        "tracks": [{
            "id": "track-scenes", "type": "scene", "name": "Scenes", "locked": False,
            "clips": [{"id": "clip-scene-1", "sceneId": "motion-scene-1", "start": 0, "duration": 8000, "locked": False}],
        }],
        "markers": [],
        "assets": [],
        "renderSettings": {"format": "mp4", "codec": "h264", "quality": "high"},
    }


def errors_after(document: dict[str, Any], mutate) -> list[str]:
    broken = copy.deepcopy(document)
    mutate(broken)
    return validate_motion_v2(broken)


def rejects(document: dict[str, Any], mutate, expected: str) -> bool:
    return any(expected in item for item in errors_after(document, mutate))


def migration_rejects(document: dict[str, Any], mutate, expected: str) -> bool:
    broken = copy.deepcopy(document)
    mutate(broken)
    try:
        migrate_motion_v1_to_v2(broken, "revision-1", {"sceneSourceKeys": {"motion-scene-1": "page/root"}})
    except ValueError as error:
        return expected in str(error)
    return False


def main() -> None:
    document = valid_v2()
    check("valid v2 passes", not validate_motion_v2(document), validate_motion_v2(document))
    check("content hash is stable", motion_v2_content_hash(document) == motion_v2_content_hash(copy.deepcopy(document)))

    migrated = migrate_motion_v1_to_v2(
        valid_v1(), "revision-1", {"sceneSourceKeys": {"motion-scene-1": "page/root"}}
    )
    check("v1 migration validates", not validate_motion_v2(migrated), validate_motion_v2(migrated))
    check("v1 migration preserves hashes", migrated["source"]["interactionHash"] == "a" * 64 and migrated["source"]["baseDesignIrHash"] == "b" * 64)
    check("v1 migration preserves render settings", {key: migrated["renderSettings"][key] for key in ("format", "codec", "quality")} == valid_v1()["renderSettings"])
    try:
        migrate_motion_v1_to_v2(valid_v1(), "revision-1")
    except ValueError as error:
        check("migration fails without explicit source linkage", "requires an explicit sceneSourceKeys" in str(error), error)
    else:
        check("migration fails without explicit source linkage", False, "migration unexpectedly succeeded")
    check("migration rejects ambiguous clip fields", migration_rejects(
        valid_v1(), lambda value: value["tracks"][0]["clips"][0].update({"mystery": 1}), "unsupported fields"
    ))
    check("migration rejects lossy transition", migration_rejects(
        valid_v1(), lambda value: value["scenes"][0]["transition"].update({"type": "fade", "duration": 300}),
        "not representable",
    ))
    ambiguous_non_scene = valid_v1()
    ambiguous_non_scene["tracks"] = [{
        "id": "track-camera", "type": "camera", "name": "Camera", "locked": False,
        "clips": [{"id": "clip-camera", "sceneId": "motion-scene-1", "start": 0, "duration": 8000, "locked": False}],
    }]
    try:
        migrate_motion_v1_to_v2(ambiguous_non_scene, "revision-1")
    except ValueError as error:
        check("migration rejects non-scene sceneId loss", "unrepresentable sceneId" in str(error), error)
    else:
        check("migration rejects non-scene sceneId loss", False, "migration unexpectedly succeeded")

    cases = [
        ("unknown property", lambda value: value["composition"].update({"mystery": True}), "Additional properties"),
        ("duplicate global id", lambda value: value["markers"].append({"id": "asset-image", "time": 2, "label": "duplicate"}), "globally unique"),
        ("dangling parent", lambda value: value["composition"]["layers"][0].update({"parentId": "missing"}), "dangling layer"),
        ("hierarchy cycle", lambda value: (
            value["composition"]["layers"][0].update({"parentId": "layer-image"}),
            value["composition"]["layers"][1].update({"parentId": "layer-scene"}),
        ), "hierarchy cycle"),
        ("dangling asset", lambda value: value["composition"]["layers"][1].update({"assetId": "missing"}), "dangling asset"),
        ("asset type mismatch", lambda value: value["assets"][0].update({"type": "video", "mime": "video/mp4"}), "asset type does not match"),
        ("asset mime mismatch", lambda value: value["assets"][0].update({"mime": "video/mp4"}), "does not match asset type"),
        ("clip bound", lambda value: value["composition"]["layers"][0]["clips"][0].update({"duration": 9, "out": 9}), "exceeds composition"),
        ("keyframe bound", lambda value: value["composition"]["layers"][0]["properties"][0]["keyframes"][1].update({"time": 9}), "exceeds composition"),
        ("source misuse", lambda value: value["composition"]["layers"][1].update({"sourceKey": "bad"}), "only design and scene"),
        ("source revision drift", lambda value: value["composition"]["layers"][0].update({"designIrRevision": "other"}), "must match source revision"),
        ("typed path", lambda value: value["composition"]["layers"][0]["properties"][0].update({"valueType": "vec2"}), "must be number"),
        ("typed value", lambda value: value["composition"]["layers"][0]["properties"][0]["keyframes"][0].update({"value": "zero"}), "does not match valueType"),
        ("codec mismatch", lambda value: value["renderSettings"].update({"format": "webm"}), "webm requires vp9"),
        ("marker bound", lambda value: value["markers"][0].update({"time": 9}), "exceeds root"),
        ("caption bound", lambda value: value["captions"][0].update({"start": 7}), "exceeds root"),
        ("composition cycle", lambda value: value["compositions"][0]["layers"].append({
            "id": "layer-cycle", "type": "group", "name": "Cycle", "parentId": None,
            "enabled": True, "locked": False, "nestedCompositionId": "comp-main",
            "clips": [clip("clip-cycle", 0, 1)], "properties": [], "masks": [],
        }), "nested composition cycle"),
    ]
    for name, mutate, expected in cases:
        check(f"validator rejects {name}", rejects(document, mutate, expected), errors_after(document, mutate))
    print("ALL PRODUCTION MOTION IR 2.0 CHECKS PASSED")


if __name__ == "__main__":
    main()
