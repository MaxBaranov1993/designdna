"""Focused schema and semantic acceptance checks for Motion IR 2.0."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "motion-ir-2.0.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft7Validator(SCHEMA)


def check(name: str, condition: bool, detail: Any = "") -> None:
    print(("[OK] " if condition else "[FAIL] ") + name)
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def _schema_errors(document: dict[str, Any]) -> list[str]:
    errors = sorted(VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors
    ]


def _all_compositions(document: dict[str, Any]) -> list[dict[str, Any]]:
    root = document.get("composition")
    nested = document.get("compositions")
    result = [root] if isinstance(root, dict) else []
    if isinstance(nested, list):
        result.extend(item for item in nested if isinstance(item, dict))
    return result


def _matches_value_type(value_type: str, value: Any) -> bool:
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type in {"string", "path", "color"}:
        return isinstance(value, str)
    size = {"vec2": 2, "vec4": 4}.get(value_type)
    return bool(size and isinstance(value, list) and len(value) == size and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ))


def semantic_errors(document: dict[str, Any]) -> list[str]:
    """Validate cross-reference, timeline, hierarchy, and typed-value invariants."""
    errors: list[str] = []
    compositions = _all_compositions(document)
    composition_ids = [item.get("id") for item in compositions]
    if len(composition_ids) != len(set(composition_ids)):
        errors.append("compositions: ids must be unique")

    assets = document.get("assets") if isinstance(document.get("assets"), list) else []
    asset_ids = [item.get("id") for item in assets if isinstance(item, dict)]
    if len(asset_ids) != len(set(asset_ids)):
        errors.append("assets: ids must be unique")
    known_assets = set(asset_ids)
    asset_types = {item.get("id"): item.get("type") for item in assets if isinstance(item, dict)}
    known_compositions = set(composition_ids)

    global_ids: list[Any] = list(composition_ids)
    for collection in (document.get("markers", []), document.get("captions", []), assets):
        global_ids.extend(item.get("id") for item in collection if isinstance(item, dict))

    composition_graph: dict[Any, set[Any]] = {item: set() for item in composition_ids}
    for composition in compositions:
        composition_id = composition.get("id")
        duration = composition.get("duration", 0)
        layers = composition.get("layers") if isinstance(composition.get("layers"), list) else []
        layer_ids = [layer.get("id") for layer in layers if isinstance(layer, dict)]
        global_ids.extend(layer_ids)
        if len(layer_ids) != len(set(layer_ids)):
            errors.append(f"composition/{composition_id}/layers: ids must be unique")
        layer_by_id = {layer.get("id"): layer for layer in layers if isinstance(layer, dict)}

        for layer in layers:
            if not isinstance(layer, dict):
                continue
            layer_id = layer.get("id")
            parent_id = layer.get("parentId")
            if parent_id is not None and parent_id not in layer_by_id:
                errors.append(f"layer/{layer_id}/parentId: dangling layer reference")
            if parent_id == layer_id:
                errors.append(f"layer/{layer_id}/parentId: hierarchy cycle")
            layer_type = layer.get("type")
            has_source = "sourceKey" in layer or "designIrRevision" in layer
            if layer_type not in {"design", "scene"} and has_source:
                errors.append(f"layer/{layer_id}/sourceKey: only design and scene layers may link Design IR")
            if layer_type in {"design", "scene"} and (
                layer.get("designIrRevision") != document.get("source", {}).get("baseDesignIrRevision")
            ):
                errors.append(f"layer/{layer_id}/designIrRevision: must match source revision")
            asset_id = layer.get("assetId")
            if asset_id is not None:
                if asset_id not in known_assets:
                    errors.append(f"layer/{layer_id}/assetId: dangling asset reference")
                elif layer_type in {"image", "video", "audio"} and asset_types.get(asset_id) != layer_type:
                    errors.append(f"layer/{layer_id}/assetId: asset type does not match layer type")
            nested_id = layer.get("nestedCompositionId")
            if nested_id is not None:
                if layer_type != "group":
                    errors.append(f"layer/{layer_id}/nestedCompositionId: only group layers may nest compositions")
                if nested_id not in known_compositions:
                    errors.append(f"layer/{layer_id}/nestedCompositionId: dangling composition reference")
                else:
                    composition_graph.setdefault(composition_id, set()).add(nested_id)

            clips = layer.get("clips") if isinstance(layer.get("clips"), list) else []
            clip_ids = [clip.get("id") for clip in clips if isinstance(clip, dict)]
            global_ids.extend(clip_ids)
            if len(clip_ids) != len(set(clip_ids)):
                errors.append(f"layer/{layer_id}/clips: ids must be unique")
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                start, clip_duration = clip.get("start", 0), clip.get("duration", 0)
                clip_in, clip_out = clip.get("in", 0), clip.get("out", 0)
                if start + clip_duration > duration:
                    errors.append(f"clip/{clip.get('id')}: exceeds composition duration")
                if clip_out <= clip_in or clip_out - clip_in < clip_duration:
                    errors.append(f"clip/{clip.get('id')}: invalid in/out range")

            properties = layer.get("properties") if isinstance(layer.get("properties"), list) else []
            property_ids = [track.get("id") for track in properties if isinstance(track, dict)]
            global_ids.extend(property_ids)
            if len(property_ids) != len(set(property_ids)):
                errors.append(f"layer/{layer_id}/properties: ids must be unique")
            for track in properties:
                if not isinstance(track, dict):
                    continue
                expected_types = {
                    "transform.position": "vec2", "transform.scale": "vec2",
                    "transform.rotation": "number", "transform.anchorPoint": "vec2",
                    "opacity": "number", "crop": "vec4", "blur": "number",
                    "mask.path": "path", "mask.opacity": "number",
                }
                expected_type = expected_types.get(track.get("propertyPath"))
                if expected_type != track.get("valueType"):
                    errors.append(f"property/{track.get('id')}/valueType: must be {expected_type}")
                seen_times: set[Any] = set()
                for keyframe in track.get("keyframes", []):
                    if not isinstance(keyframe, dict):
                        continue
                    time = keyframe.get("time", 0)
                    if time > duration:
                        errors.append(f"property/{track.get('id')}/keyframe: exceeds composition duration")
                    if time in seen_times:
                        errors.append(f"property/{track.get('id')}/keyframes: times must be unique")
                    seen_times.add(time)
                    if not _matches_value_type(str(track.get("valueType")), keyframe.get("value")):
                        errors.append(f"property/{track.get('id')}/value: does not match valueType")
                    interpolation = keyframe.get("interpolation")
                    if interpolation != "bezier" and "bezierHandles" in keyframe:
                        errors.append(f"property/{track.get('id')}/keyframe: bezier handles require bezier interpolation")
                    if interpolation != "spring" and "spring" in keyframe:
                        errors.append(f"property/{track.get('id')}/keyframe: spring parameters require spring interpolation")

            masks = layer.get("masks") if isinstance(layer.get("masks"), list) else []
            mask_ids = [mask.get("id") for mask in masks if isinstance(mask, dict)]
            global_ids.extend(mask_ids)
            if len(mask_ids) != len(set(mask_ids)):
                errors.append(f"layer/{layer_id}/masks: ids must be unique")

        for layer_id in layer_ids:
            visited: set[Any] = set()
            cursor = layer_id
            while cursor is not None:
                if cursor in visited:
                    errors.append(f"layer/{layer_id}/parentId: hierarchy cycle")
                    break
                visited.add(cursor)
                parent = layer_by_id.get(cursor, {}).get("parentId")
                cursor = parent if parent in layer_by_id else None

    visiting: set[Any] = set()
    visited_compositions: set[Any] = set()

    def visit(composition_id: Any) -> None:
        if composition_id in visiting:
            errors.append(f"composition/{composition_id}: nested composition cycle")
            return
        if composition_id in visited_compositions:
            return
        visiting.add(composition_id)
        for child_id in composition_graph.get(composition_id, set()):
            visit(child_id)
        visiting.remove(composition_id)
        visited_compositions.add(composition_id)

    for composition_id in composition_ids:
        visit(composition_id)

    if len(global_ids) != len(set(global_ids)):
        errors.append("document: persisted ids must be globally unique")

    root_duration = document.get("composition", {}).get("duration", 0)
    for marker in document.get("markers", []):
        if isinstance(marker, dict) and marker.get("time", 0) > root_duration:
            errors.append(f"marker/{marker.get('id')}: exceeds root composition duration")
    for caption in document.get("captions", []):
        if isinstance(caption, dict) and caption.get("start", 0) + caption.get("duration", 0) > root_duration:
            errors.append(f"caption/{caption.get('id')}: exceeds root composition duration")

    render = document.get("renderSettings") if isinstance(document.get("renderSettings"), dict) else {}
    expected_codec = {"mp4": "h264", "webm": "vp9"}.get(render.get("format"))
    if expected_codec and render.get("codec") != expected_codec:
        errors.append(f"renderSettings/codec: {render.get('format')} requires {expected_codec}")
    return errors


def validate(document: dict[str, Any]) -> list[str]:
    schema = _schema_errors(document)
    return schema if schema else semantic_errors(document)


def product_walkthrough() -> dict[str, Any]:
    design_hash = "a" * 64
    interaction_hash = "b" * 64
    revision = "design-revision-42"
    position_track = {
        "id": "track-camera-position",
        "propertyPath": "transform.position",
        "valueType": "vec2",
        "keyframes": [
            {"time": 0, "value": [960, 540], "interpolation": "linear"},
            {
                "time": 4,
                "value": [720, 420],
                "interpolation": "bezier",
                "bezierHandles": {"in": [0.2, 0.0], "out": [0.8, 1.0]},
            },
        ],
    }
    opacity_track = {
        "id": "track-cta-opacity",
        "propertyPath": "opacity",
        "valueType": "number",
        "keyframes": [
            {"time": 0, "value": 0, "interpolation": "hold"},
            {
                "time": 1,
                "value": 1,
                "interpolation": "spring",
                "spring": {"mass": 1, "stiffness": 180, "damping": 20, "initialVelocity": 0},
            },
        ],
    }
    clip = lambda clip_id, start, duration: {  # noqa: E731 - compact fixture factory
        "id": clip_id, "start": start, "duration": duration, "in": 0, "out": duration
    }
    return {
        "version": "2.0",
        "source": {
            "interactionHash": interaction_hash,
            "baseDesignIrHash": design_hash,
            "baseDesignIrRevision": revision,
        },
        "composition": {
            "id": "comp-main", "name": "Checkout walkthrough", "width": 1920, "height": 1080,
            "fps": 30, "duration": 8, "background": "#111116", "colorSpace": "srgb",
            "layers": [
                {
                    "id": "layer-scene", "type": "scene", "name": "Checkout", "parentId": None,
                    "enabled": True, "locked": False, "sourceKey": "checkout/root",
                    "designIrRevision": revision, "clips": [clip("clip-scene", 0, 8)],
                    "properties": [opacity_track], "masks": [],
                },
                {
                    "id": "layer-camera", "type": "camera", "name": "Camera", "parentId": None,
                    "enabled": True, "locked": False, "clips": [clip("clip-camera", 0, 8)],
                    "properties": [position_track], "masks": [],
                },
                {
                    "id": "layer-product-shot", "type": "image", "name": "Product shot", "parentId": None,
                    "enabled": True, "locked": False, "assetId": "asset-product-shot",
                    "clips": [clip("clip-product-shot", 1, 5)], "properties": [],
                    "masks": [{
                        "id": "mask-product", "mode": "add", "inverted": False,
                        "path": "M0 0H800V600H0Z", "opacity": 1, "feather": 12,
                    }],
                },
                {
                    "id": "layer-precomp", "type": "group", "name": "CTA precomp", "parentId": None,
                    "enabled": True, "locked": False, "nestedCompositionId": "comp-cta",
                    "clips": [clip("clip-precomp", 2, 3)], "properties": [], "masks": [],
                },
                {
                    "id": "layer-audio", "type": "audio", "name": "Narration", "parentId": None,
                    "enabled": True, "locked": False, "assetId": "asset-narration",
                    "clips": [clip("clip-audio", 0, 8)], "properties": [], "masks": [],
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
        "markers": [{"id": "marker-submit", "time": 4, "label": "Submit CTA"}],
        "captions": [{"id": "caption-1", "start": 0.5, "duration": 2.5, "text": "Complete checkout", "language": "en-US"}],
        "assets": [
            {"id": "asset-product-shot", "type": "image", "hash": "c" * 64, "mime": "image/png", "uri": "assets/product.png"},
            {"id": "asset-narration", "type": "audio", "hash": "d" * 64, "mime": "audio/wav", "uri": "assets/narration.wav"},
        ],
        "renderSettings": {
            "format": "mp4", "codec": "h264", "quality": "high",
            "resolution": {"width": 1920, "height": 1080}, "fps": 30,
            "audio": {"enabled": True, "sampleRate": 48000, "channels": 2, "bitrateKbps": 192},
        },
    }


def rejected(document: dict[str, Any], mutate, expected: str) -> bool:
    broken = copy.deepcopy(document)
    mutate(broken)
    errors = validate(broken)
    return any(expected in error for error in errors)


def main() -> None:
    jsonschema.Draft7Validator.check_schema(SCHEMA)
    document = product_walkthrough()
    check("valid product walkthrough passes", not validate(document), validate(document))
    check("unknown persisted property is rejected", rejected(
        document, lambda value: value["composition"].update({"mystery": True}), "Additional properties"
    ))
    check("duplicate ids are rejected", rejected(
        document, lambda value: value["markers"].append(copy.deepcopy(value["markers"][0])), "ids must"
    ))
    check("dangling asset reference is rejected", rejected(
        document, lambda value: value["composition"]["layers"][2].update({"assetId": "missing"}), "dangling asset"
    ))
    check("out-of-bounds clip is rejected", rejected(
        document, lambda value: value["composition"]["layers"][0]["clips"][0].update({"duration": 9, "out": 9}),
        "exceeds composition",
    ))
    check("out-of-bounds keyframe is rejected", rejected(
        document, lambda value: value["composition"]["layers"][1]["properties"][0]["keyframes"][1].update({"time": 9}),
        "exceeds composition",
    ))
    check("invalid parent cycle is rejected", rejected(
        document,
        lambda value: (
            value["composition"]["layers"][0].update({"parentId": "layer-camera"}),
            value["composition"]["layers"][1].update({"parentId": "layer-scene"}),
        ),
        "hierarchy cycle",
    ))
    check("sourceKey misuse is rejected", rejected(
        document, lambda value: value["composition"]["layers"][1].update({"sourceKey": "checkout/root"}),
        "only design and scene",
    ))
    check("codec and format mismatch is rejected", rejected(
        document, lambda value: value["renderSettings"].update({"format": "webm"}), "webm requires vp9"
    ))
    check("typed keyframe mismatch is rejected", rejected(
        document,
        lambda value: value["composition"]["layers"][1]["properties"][0]["keyframes"][0].update({"value": "center"}),
        "does not match valueType",
    ))
    check("nested composition cycle is rejected", rejected(
        document,
        lambda value: value["compositions"][0]["layers"].append({
            "id": "layer-cycle", "type": "group", "name": "Cycle", "parentId": None,
            "enabled": True, "locked": False, "nestedCompositionId": "comp-main",
            "clips": [{"id": "clip-cycle", "start": 0, "duration": 1, "in": 0, "out": 1}],
            "properties": [], "masks": [],
        }),
        "nested composition cycle",
    ))
    print("ALL MOTION IR 2.0 CHECKS PASSED")


if __name__ == "__main__":
    main()
