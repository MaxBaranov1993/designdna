"""Production validation and fail-closed migration for Motion IR 2.0."""
from __future__ import annotations

import copy
from typing import Any, Callable

import jsonschema

from .hash import content_hash
from .schema import load_aux_schema

_V1_VALIDATOR = jsonschema.Draft7Validator(load_aux_schema("motion-ir"))
_V2_VALIDATOR = jsonschema.Draft7Validator(load_aux_schema("motion-ir-2.0"))


def motion_v2_content_hash(document: dict[str, Any]) -> str:
    """Return the repository's canonical content hash for a Motion IR document."""
    return content_hash(document)


def _schema_errors(document: Any) -> list[str]:
    errors = sorted(_V2_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors
    ]


def _all_compositions(document: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(document.get("composition"), dict):
        result.append(document["composition"])
    nested = document.get("compositions")
    if isinstance(nested, list):
        result.extend(item for item in nested if isinstance(item, dict))
    return result


def _matches_value_type(value_type: str, value: Any) -> bool:
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type in {"string", "path"}:
        return isinstance(value, str)
    if value_type == "color":
        return isinstance(value, str) and len(value) in {7, 9} and value.startswith("#")
    size = {"vec2": 2, "vec4": 4}.get(value_type)
    return bool(size and isinstance(value, list) and len(value) == size and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ))


def _find_cycle(nodes: list[Any], parent_of: Callable[[Any], Any]) -> Any | None:
    for node in nodes:
        visited: set[Any] = set()
        cursor = node
        while cursor is not None:
            if cursor in visited:
                return node
            visited.add(cursor)
            cursor = parent_of(cursor)
    return None


def _semantic_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    compositions = _all_compositions(document)
    composition_ids = [item["id"] for item in compositions]
    if len(composition_ids) != len(set(composition_ids)):
        errors.append("compositions: ids must be unique")

    assets = document["assets"]
    asset_ids = [item["id"] for item in assets]
    if len(asset_ids) != len(set(asset_ids)):
        errors.append("assets: ids must be unique")
    known_assets = set(asset_ids)
    asset_types = {item["id"]: item["type"] for item in assets}
    for asset in assets:
        mime_family = asset["mime"].split("/", 1)[0]
        if asset["type"] in {"image", "video", "audio"} and mime_family != asset["type"]:
            errors.append(f"asset/{asset['id']}/mime: does not match asset type")
    known_compositions = set(composition_ids)

    global_ids: list[Any] = list(composition_ids)
    for collection_name in ("markers", "captions", "assets"):
        global_ids.extend(item["id"] for item in document[collection_name])

    composition_graph: dict[Any, set[Any]] = {item: set() for item in composition_ids}
    expected_value_types = {
        "transform.position": "vec2",
        "transform.scale": "vec2",
        "transform.rotation": "number",
        "transform.anchorPoint": "vec2",
        "opacity": "number",
        "crop": "vec4",
        "blur": "number",
        "mask.path": "path",
        "mask.opacity": "number",
    }

    for composition in compositions:
        composition_id = composition["id"]
        duration = composition["duration"]
        layers = composition["layers"]
        layer_ids = [layer["id"] for layer in layers]
        global_ids.extend(layer_ids)
        if len(layer_ids) != len(set(layer_ids)):
            errors.append(f"composition/{composition_id}/layers: ids must be unique")
        layer_by_id = {layer["id"]: layer for layer in layers}

        for layer in layers:
            layer_id = layer["id"]
            parent_id = layer["parentId"]
            if parent_id is not None and parent_id not in layer_by_id:
                errors.append(f"layer/{layer_id}/parentId: dangling layer reference")

            layer_type = layer["type"]
            has_source = "sourceKey" in layer or "designIrRevision" in layer
            if layer_type not in {"design", "scene"} and has_source:
                errors.append(f"layer/{layer_id}/sourceKey: only design and scene layers may link Design IR")
            if layer_type in {"design", "scene"} and (
                layer["designIrRevision"] != document["source"]["baseDesignIrRevision"]
            ):
                errors.append(f"layer/{layer_id}/designIrRevision: must match source revision")

            asset_id = layer.get("assetId")
            if asset_id is not None:
                if layer_type not in {"image", "video", "audio"}:
                    errors.append(f"layer/{layer_id}/assetId: only media layers may reference assets")
                elif asset_id not in known_assets:
                    errors.append(f"layer/{layer_id}/assetId: dangling asset reference")
                elif asset_types[asset_id] != layer_type:
                    errors.append(f"layer/{layer_id}/assetId: asset type does not match layer type")

            nested_id = layer.get("nestedCompositionId")
            if nested_id is not None:
                if layer_type != "group":
                    errors.append(f"layer/{layer_id}/nestedCompositionId: only group layers may nest compositions")
                if nested_id not in known_compositions:
                    errors.append(f"layer/{layer_id}/nestedCompositionId: dangling composition reference")
                else:
                    composition_graph[composition_id].add(nested_id)

            clips = layer["clips"]
            clip_ids = [clip["id"] for clip in clips]
            global_ids.extend(clip_ids)
            if len(clip_ids) != len(set(clip_ids)):
                errors.append(f"layer/{layer_id}/clips: ids must be unique")
            for clip in clips:
                if clip["start"] + clip["duration"] > duration:
                    errors.append(f"clip/{clip['id']}: exceeds composition duration")
                if clip["out"] <= clip["in"] or clip["out"] - clip["in"] < clip["duration"]:
                    errors.append(f"clip/{clip['id']}: invalid in/out range")

            properties = layer["properties"]
            property_ids = [track["id"] for track in properties]
            global_ids.extend(property_ids)
            if len(property_ids) != len(set(property_ids)):
                errors.append(f"layer/{layer_id}/properties: ids must be unique")
            property_paths = [track["propertyPath"] for track in properties]
            if len(property_paths) != len(set(property_paths)):
                errors.append(f"layer/{layer_id}/properties: property paths must be unique")
            for track in properties:
                expected_type = expected_value_types[track["propertyPath"]]
                if track["valueType"] != expected_type:
                    errors.append(f"property/{track['id']}/valueType: must be {expected_type}")
                seen_times: set[Any] = set()
                previous_time: float | None = None
                for keyframe in track["keyframes"]:
                    time = keyframe["time"]
                    if time > duration:
                        errors.append(f"property/{track['id']}/keyframe: exceeds composition duration")
                    if time in seen_times:
                        errors.append(f"property/{track['id']}/keyframes: times must be unique")
                    if previous_time is not None and time < previous_time:
                        errors.append(f"property/{track['id']}/keyframes: times must be ordered")
                    seen_times.add(time)
                    previous_time = time
                    if not _matches_value_type(track["valueType"], keyframe["value"]):
                        errors.append(f"property/{track['id']}/value: does not match valueType")
                    interpolation = keyframe["interpolation"]
                    if interpolation != "bezier" and "bezierHandles" in keyframe:
                        errors.append(f"property/{track['id']}/keyframe: bezier handles require bezier interpolation")
                    if interpolation != "spring" and "spring" in keyframe:
                        errors.append(f"property/{track['id']}/keyframe: spring parameters require spring interpolation")

            masks = layer["masks"]
            mask_ids = [mask["id"] for mask in masks]
            global_ids.extend(mask_ids)
            if len(mask_ids) != len(set(mask_ids)):
                errors.append(f"layer/{layer_id}/masks: ids must be unique")

        cycle = _find_cycle(layer_ids, lambda item: layer_by_id.get(item, {}).get("parentId"))
        if cycle is not None:
            errors.append(f"layer/{cycle}/parentId: hierarchy cycle")

    composition_cycle = _find_cycle(
        composition_ids,
        lambda item: next(iter(composition_graph.get(item, set())), None)
        if len(composition_graph.get(item, set())) <= 1 else None,
    )
    # A graph node can reference several precomps, so use DFS in addition to the
    # compact single-parent cycle check above.
    visiting: set[Any] = set()
    visited: set[Any] = set()

    def visit(composition_id: Any) -> None:
        nonlocal composition_cycle
        if composition_id in visiting:
            composition_cycle = composition_id
            return
        if composition_id in visited:
            return
        visiting.add(composition_id)
        for child_id in composition_graph.get(composition_id, set()):
            visit(child_id)
        visiting.remove(composition_id)
        visited.add(composition_id)

    for composition_id in composition_ids:
        visit(composition_id)
    if composition_cycle is not None:
        errors.append(f"composition/{composition_cycle}: nested composition cycle")

    if len(global_ids) != len(set(global_ids)):
        errors.append("document: persisted ids must be globally unique")

    root_duration = document["composition"]["duration"]
    for marker in document["markers"]:
        if marker["time"] > root_duration:
            errors.append(f"marker/{marker['id']}: exceeds root composition duration")
    for caption in document["captions"]:
        if caption["start"] + caption["duration"] > root_duration:
            errors.append(f"caption/{caption['id']}: exceeds root composition duration")

    expected_codec = {"mp4": "h264", "webm": "vp9"}[document["renderSettings"]["format"]]
    if document["renderSettings"]["codec"] != expected_codec:
        errors.append(
            f"renderSettings/codec: {document['renderSettings']['format']} requires {expected_codec}"
        )
    return errors


def validate_motion_v2(document: Any) -> list[str]:
    """Return deterministic schema and semantic violations for Motion IR 2.0."""
    schema_errors = _schema_errors(document)
    if schema_errors:
        return schema_errors
    return _semantic_errors(document)


def _v1_schema_errors(document: Any) -> list[str]:
    errors = sorted(_V1_VALIDATOR.iter_errors(document), key=lambda error: list(error.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors
    ]


def migrate_motion_v1_to_v2(
    v1: dict[str, Any],
    base_design_ir_revision: str,
    asset_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Migrate representable v1 documents without guessing source or asset identity.

    ``asset_mapping`` may contain ``sceneSourceKeys`` (v1 scene id to Design IR
    sourceKey), ``trackAssets`` (v1 media track id to v2 asset id), and a strict
    v2 ``assets`` list. Unsupported clip fields and lossy scene transitions are
    rejected instead of silently discarded.
    """
    errors = _v1_schema_errors(v1)
    if errors:
        raise ValueError("invalid Motion IR 1.0: " + "; ".join(errors[:10]))
    if not isinstance(base_design_ir_revision, str) or not base_design_ir_revision:
        raise ValueError("base_design_ir_revision is required")

    mapping = asset_mapping or {}
    allowed_mapping_keys = {"sceneSourceKeys", "trackAssets", "assets"}
    unknown_mapping_keys = set(mapping) - allowed_mapping_keys
    if unknown_mapping_keys:
        raise ValueError(f"unknown asset mapping fields: {sorted(unknown_mapping_keys)}")
    scene_source_keys = mapping.get("sceneSourceKeys", {})
    track_assets = mapping.get("trackAssets", {})
    if not isinstance(scene_source_keys, dict) or not isinstance(track_assets, dict):
        raise ValueError("sceneSourceKeys and trackAssets must be objects")

    source = v1["source"]
    composition = v1["composition"]
    scenes = {scene["id"]: scene for scene in v1["scenes"]}
    if len(scenes) != len(v1["scenes"]):
        raise ValueError("v1 scenes must have unique ids")
    for scene in scenes.values():
        transition = scene["transition"]
        if transition["type"] != "cut" or transition["duration"] != 0:
            raise ValueError(f"scene {scene['id']} transition is not representable in Motion IR 2.0")

    supplied_assets = mapping.get("assets")
    if supplied_assets is None:
        supplied_assets = copy.deepcopy(v1["assets"])
    if not isinstance(supplied_assets, list):
        raise ValueError("assets mapping must be an array")

    layers: list[dict[str, Any]] = []
    seen_clip_ids: set[str] = set()
    allowed_clip_fields = {"id", "sceneId", "start", "duration", "locked"}
    known_track_ids = {track["id"] for track in v1["tracks"]}
    unknown_scene_mappings = set(scene_source_keys) - set(scenes)
    unknown_track_mappings = set(track_assets) - known_track_ids
    if unknown_scene_mappings:
        raise ValueError(f"sceneSourceKeys contains unknown scene ids: {sorted(unknown_scene_mappings)}")
    if unknown_track_mappings:
        raise ValueError(f"trackAssets contains unknown track ids: {sorted(unknown_track_mappings)}")
    for track in v1["tracks"]:
        clips = track["clips"]
        if not clips:
            raise ValueError(f"track {track['id']} has no representable clips")
        for clip in clips:
            unknown_fields = set(clip) - allowed_clip_fields
            if unknown_fields:
                raise ValueError(f"clip {clip.get('id', '<unknown>')} has unsupported fields: {sorted(unknown_fields)}")
            if not isinstance(clip.get("id"), str) or not clip["id"]:
                raise ValueError(f"track {track['id']} contains a clip without an id")
            if clip["id"] in seen_clip_ids:
                raise ValueError(f"duplicate v1 clip id: {clip['id']}")
            seen_clip_ids.add(clip["id"])
            if not isinstance(clip.get("start"), (int, float)) or not isinstance(clip.get("duration"), (int, float)):
                raise ValueError(f"clip {clip['id']} timing is not numeric")
            if clip["start"] < 0 or clip["duration"] <= 0:
                raise ValueError(f"clip {clip['id']} timing is invalid")

        layer_type = track["type"]
        if layer_type == "scene":
            for clip in clips:
                scene_id = clip.get("sceneId")
                scene = scenes.get(scene_id)
                if scene is None:
                    raise ValueError(f"clip {clip['id']} has a dangling or missing sceneId")
                if clip["start"] != scene["start"] or clip["duration"] != scene["duration"]:
                    raise ValueError(f"clip {clip['id']} timing disagrees with scene {scene_id}")
                source_key = scene_source_keys.get(scene_id)
                if not isinstance(source_key, str) or not source_key:
                    raise ValueError(f"scene {scene_id} requires an explicit sceneSourceKeys mapping")
                layers.append({
                    "id": f"layer-{clip['id']}",
                    "type": "scene",
                    "name": scene_id,
                    "parentId": None,
                    "enabled": True,
                    "locked": bool(track["locked"] or clip.get("locked", False)),
                    "sourceKey": source_key,
                    "designIrRevision": base_design_ir_revision,
                    "clips": [{
                        "id": clip["id"], "start": clip["start"], "duration": clip["duration"],
                        "in": 0, "out": clip["duration"],
                    }],
                    "properties": [],
                    "masks": [],
                })
            continue

        for clip in clips:
            if "sceneId" in clip:
                raise ValueError(f"non-scene clip {clip['id']} has an unrepresentable sceneId")
            if "locked" in clip and bool(clip["locked"]) != bool(track["locked"]):
                raise ValueError(f"clip {clip['id']} lock disagrees with its track and is not representable")
        asset_id = track_assets.get(track["id"])
        if layer_type == "audio" and (not isinstance(asset_id, str) or not asset_id):
            raise ValueError(f"audio track {track['id']} requires an explicit trackAssets mapping")
        layer: dict[str, Any] = {
            "id": f"layer-{track['id']}",
            "type": layer_type,
            "name": track["name"],
            "parentId": None,
            "enabled": True,
            "locked": track["locked"],
            "clips": [{
                "id": clip["id"], "start": clip["start"], "duration": clip["duration"],
                "in": 0, "out": clip["duration"],
            } for clip in clips],
            "properties": [],
            "masks": [],
        }
        if asset_id:
            layer["assetId"] = asset_id
        layers.append(layer)

    for marker in v1["markers"]:
        missing = {"id", "time", "label"} - set(marker)
        if missing:
            raise ValueError(f"v1 marker is missing required fields: {sorted(missing)}")
        unknown = set(marker) - {"id", "time", "label", "targetSourceKey"}
        if unknown:
            raise ValueError(f"marker {marker.get('id', '<unknown>')} has unsupported fields: {sorted(unknown)}")
        if marker.get("targetSourceKey"):
            raise ValueError(f"marker {marker.get('id', '<unknown>')} targetSourceKey is not representable")

    render = v1["renderSettings"]
    result = {
        "version": "2.0",
        "source": {
            "interactionHash": source["interactionHash"],
            "baseDesignIrHash": source["baseDesignIrHash"],
            "baseDesignIrRevision": base_design_ir_revision,
        },
        "composition": {
            "id": "comp-main",
            "name": "Migrated Motion IR",
            "width": composition["width"],
            "height": composition["height"],
            "fps": composition["fps"],
            "duration": composition["duration"],
            "background": composition["background"],
            "colorSpace": "srgb",
            "layers": layers,
        },
        "compositions": [],
        "markers": [{"id": item["id"], "time": item["time"], "label": item["label"]} for item in v1["markers"]],
        "captions": [],
        "assets": copy.deepcopy(supplied_assets),
        "renderSettings": {
            "format": render["format"],
            "codec": render["codec"],
            "quality": render["quality"],
            "resolution": {"width": composition["width"], "height": composition["height"]},
            "fps": composition["fps"],
            "audio": {"enabled": False, "sampleRate": 48000, "channels": 2, "bitrateKbps": 192},
        },
    }
    migrated_errors = validate_motion_v2(result)
    if migrated_errors:
        raise ValueError("v1 migration did not produce valid Motion IR 2.0: " + "; ".join(migrated_errors[:10]))
    return result
