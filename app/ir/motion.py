"""Motion IR construction and validation for editable product-flow videos."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .hash import content_hash

DEFAULT_POSE = {"opacity": 1.0, "x": 0.0, "y": 0.0, "scale": 1.0, "rotate": 0.0}

MOTION_VERSION = "1.0"
ALLOWED_TRANSITIONS = {"cut", "fade", "slide-left", "slide-up", "zoom"}
ALLOWED_EASINGS = {"linear", "ease", "ease-in", "ease-out", "ease-in-out"}
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "motion-ir.schema.json"


def load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(document: dict, interaction: dict | None = None) -> list[str]:
    validator = jsonschema.Draft7Validator(load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    formatted = [f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}" for error in errors]
    if not isinstance(document, dict):
        return formatted
    scenes = document.get("scenes") if isinstance(document.get("scenes"), list) else []
    ids = [scene.get("id") for scene in scenes if isinstance(scene, dict)]
    if len(ids) != len(set(ids)):
        formatted.append("scenes: ids must be unique")
    cursor = 0
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        if scene.get("start") != cursor:
            formatted.append(f"scenes/{index}/start: scenes must be contiguous")
        transition = scene.get("transition") if isinstance(scene.get("transition"), dict) else {}
        if int(transition.get("duration") or 0) > int(scene.get("duration") or 0):
            formatted.append(f"scenes/{index}/transition/duration: cannot exceed scene duration")
        cursor = int(scene.get("start") or 0) + int(scene.get("duration") or 0)
    composition = document.get("composition") if isinstance(document.get("composition"), dict) else {}
    render_settings = document.get("renderSettings") if isinstance(document.get("renderSettings"), dict) else {}
    expected_codec = "h264" if render_settings.get("format") == "mp4" else "vp9"
    if render_settings.get("codec") and render_settings.get("codec") != expected_codec:
        formatted.append(f"renderSettings/codec: {render_settings.get('format')} requires {expected_codec}")
    if scenes and composition.get("duration") != cursor:
        formatted.append("composition/duration: must equal the end of the last scene")
    by_id = {scene.get("id"): scene for scene in scenes if isinstance(scene, dict)}
    tracks = document.get("tracks") if isinstance(document.get("tracks"), list) else []
    scene_track = next((track for track in tracks if isinstance(track, dict) and track.get("type") == "scene"), None)
    if scenes and not scene_track:
        formatted.append("tracks: a scene track is required")
    elif scene_track:
        clips = scene_track.get("clips") if isinstance(scene_track.get("clips"), list) else []
        if len(clips) != len(scenes):
            formatted.append("tracks/scene/clips: must contain one clip per scene")
        for index, clip in enumerate(clips):
            scene = by_id.get(clip.get("sceneId")) if isinstance(clip, dict) else None
            if not scene:
                formatted.append(f"tracks/scene/clips/{index}/sceneId: scene does not exist")
            elif clip.get("start") != scene.get("start") or clip.get("duration") != scene.get("duration"):
                formatted.append(f"tracks/scene/clips/{index}: timing must match the referenced scene")
    if interaction:
        known = {scene.get("id") for scene in interaction.get("scenes", []) if isinstance(scene, dict)}
        for index, scene in enumerate(scenes):
            if isinstance(scene, dict) and scene.get("interactionSceneId") not in known:
                formatted.append(f"scenes/{index}/interactionSceneId: scene does not exist")
    return formatted


def build(interaction: dict, composition: dict | None = None,
          scene_settings: dict | None = None, render_settings: dict | None = None) -> dict:
    """Build deterministic contiguous Motion IR from Interaction IR scenes."""
    interaction_scenes = interaction.get("scenes") if isinstance(interaction.get("scenes"), list) else []
    if not interaction_scenes:
        raise ValueError("Interaction IR has no scenes")
    settings = scene_settings or {}
    raw_composition = composition or {}
    width = max(320, min(3840, int(raw_composition.get("width") or 1920)))
    height = max(240, min(2160, int(raw_composition.get("height") or 1080)))
    fps = max(12, min(60, int(raw_composition.get("fps") or 30)))
    raw_render = render_settings or {}
    output_format = str(raw_render.get("format") or "mp4")
    if output_format not in {"mp4", "webm"}:
        output_format = "mp4"
    quality = str(raw_render.get("quality") or "high")
    if quality not in {"draft", "high", "lossless"}:
        quality = "high"
    scenes = []
    clips = []
    cursor = 0
    for index, source_scene in enumerate(interaction_scenes):
        source_id = str(source_scene.get("id") or f"scene-{index}")
        config = settings.get(source_id) if isinstance(settings.get(source_id), dict) else {}
        duration = max(250, min(30000, int(config.get("duration") or (1500 if index == len(interaction_scenes) - 1 else 1200))))
        transition_type = str(config.get("transition") or ("cut" if index == 0 else "fade"))
        if transition_type not in ALLOWED_TRANSITIONS:
            transition_type = "fade"
        transition_duration = 0 if transition_type == "cut" else max(100, min(duration, int(config.get("transitionDuration") or 300)))
        easing = str(config.get("easing") or "ease-in-out")
        if easing not in ALLOWED_EASINGS:
            easing = "ease-in-out"
        scene_id = f"motion-{source_id}"
        scene = {
            "id": scene_id,
            "interactionSceneId": source_id,
            "start": cursor,
            "duration": duration,
            "viewport": source_scene.get("viewport") if source_scene.get("viewport") in {"desktop", "tablet", "mobile"} else "desktop",
            "transition": {"type": transition_type, "duration": transition_duration, "easing": easing},
        }
        scenes.append(scene)
        clips.append({"id": f"clip-{index + 1}", "sceneId": scene_id, "start": cursor, "duration": duration, "locked": False})
        cursor += duration
    events = interaction.get("events") if isinstance(interaction.get("events"), list) else []
    markers = [{
        "id": f"marker-{index + 1}",
        "time": min(cursor, max(0, int(event.get("time") or 0))),
        "label": str(event.get("type") or "event"),
        "targetSourceKey": str(event.get("targetSourceKey") or ""),
    } for index, event in enumerate(events) if isinstance(event, dict)]
    base_hash = str(interaction_scenes[0].get("baseDesignIrHash") or "")
    document = {
        "version": MOTION_VERSION,
        "source": {"interactionHash": content_hash(interaction), "baseDesignIrHash": base_hash},
        "composition": {"width": width, "height": height, "fps": fps, "duration": cursor, "background": "#111116"},
        "scenes": scenes,
        "tracks": [{"id": "track-scenes", "type": "scene", "name": "Scenes", "clips": clips, "locked": False}],
        "markers": markers,
        "assets": [],
        "renderSettings": {
            "format": output_format,
            "codec": "h264" if output_format == "mp4" else "vp9",
            "quality": quality,
        },
    }
    errors = validate(document, interaction)
    if errors:
        raise ValueError("invalid Motion IR: " + "; ".join(errors[:5]))
    return document


def _section_name(section: dict, index: int) -> str:
    semantic = section.get("semantic") if isinstance(section.get("semantic"), dict) else {}
    label = semantic.get("label") or section.get("type") or f"Слой {index + 1}"
    return str(label)[:48]


def layers_from_design(ir: dict) -> list[dict]:
    tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
    layers = []
    for index, section in enumerate(tree):
        if not isinstance(section, dict):
            continue
        layers.append({
            "id": f"layer-{index}",
            "name": _section_name(section, index),
            "sectionIndex": index,
            "sourceKey": str(section.get("sourceKey") or ""),
            "enabled": True,
            "keyframes": [],
        })
    return layers


def interpolate_pose(keyframes: list[dict], time_ms: float) -> dict:
    pose = dict(DEFAULT_POSE)
    if not keyframes:
        return pose
    ordered = sorted(
        (frame for frame in keyframes if isinstance(frame, dict) and isinstance(frame.get("t"), (int, float))),
        key=lambda frame: float(frame["t"]),
    )
    if not ordered:
        return pose
    if time_ms <= float(ordered[0]["t"]):
        src = ordered[0]
        for key in DEFAULT_POSE:
            if key in src:
                pose[key] = float(src[key])
        return pose
    if time_ms >= float(ordered[-1]["t"]):
        src = ordered[-1]
        for key in DEFAULT_POSE:
            if key in src:
                pose[key] = float(src[key])
        return pose
    start = ordered[0]
    end = ordered[-1]
    for index in range(1, len(ordered)):
        if time_ms <= float(ordered[index]["t"]):
            start = ordered[index - 1]
            end = ordered[index]
            break
    span = max(1.0, float(end["t"]) - float(start["t"]))
    mix = (time_ms - float(start["t"])) / span
    mix = mix * mix * (3 - 2 * mix)
    for key in DEFAULT_POSE:
        a = float(start[key]) if key in start else DEFAULT_POSE[key]
        b = float(end[key]) if key in end else DEFAULT_POSE[key]
        pose[key] = a + (b - a) * mix
    return pose


def frame_comp_state(motion: dict, frame_index: int) -> dict:
    composition = motion.get("composition") or {}
    fps = max(1, int(composition.get("fps") or 30))
    time_ms = frame_index * 1000 / fps
    camera = interpolate_pose(((motion.get("camera") or {}).get("keyframes") or []), time_ms)
    layers = []
    for layer in motion.get("layers") or []:
        if not isinstance(layer, dict) or not layer.get("enabled", True):
            continue
        pose = interpolate_pose(layer.get("keyframes") or [], time_ms)
        layers.append({
            "id": layer.get("id"),
            "sectionIndex": int(layer.get("sectionIndex") or 0),
            **pose,
        })
    return {"time": time_ms, "camera": camera, "layers": layers}


def default_product_comp(layers: list[dict], duration_hint: int | None = None) -> tuple[list[dict], dict, int]:
    count = max(1, len(layers))
    step = 1100 if count > 4 else 1400
    duration = duration_hint or min(28000, max(3200, count * step + 900))
    next_layers = []
    for index, layer in enumerate(layers):
        enter = index * step
        next_layers.append({
            **layer,
            "keyframes": [
                {"t": max(0, enter - 80), "opacity": 0, "x": 0, "y": 56, "scale": 0.94, "rotate": 0},
                {"t": enter + 520, "opacity": 1, "x": 0, "y": 0, "scale": 1, "rotate": 0},
                {"t": duration, "opacity": 1, "x": 0, "y": 0, "scale": 1, "rotate": 0},
            ],
        })
    camera = {
        "keyframes": [
            {"t": 0, "opacity": 1, "x": 0, "y": 0, "scale": 1, "rotate": 0},
            {"t": duration, "opacity": 1, "x": 0, "y": -min(240, 36 * count), "scale": 1.04, "rotate": 0},
        ]
    }
    return next_layers, camera, duration


def apply_director_plan(layers: list[dict], plan: dict) -> tuple[list[dict], dict, int]:
    planned = {item.get("id"): item for item in plan.get("layers") or [] if isinstance(item, dict)}
    duration = max(250, min(28000, int(plan.get("duration") or 0)))
    next_layers = []
    max_t = 0
    for layer in layers:
        src = planned.get(layer["id"], {})
        frames = []
        for frame in src.get("keyframes") or []:
            if not isinstance(frame, dict) or not isinstance(frame.get("t"), (int, float)):
                continue
            item = {"t": max(0, min(28000, int(frame["t"])))}
            for key in ("opacity", "x", "y", "scale", "rotate"):
                if key in frame:
                    item[key] = float(frame[key])
            frames.append(item)
            max_t = max(max_t, item["t"])
        if not frames:
            frames = [{"t": 0, **DEFAULT_POSE}, {"t": max(duration, 1200), **DEFAULT_POSE}]
        next_layers.append({**layer, "keyframes": frames})
    camera_frames = []
    for frame in ((plan.get("camera") or {}).get("keyframes") or []):
        if not isinstance(frame, dict) or not isinstance(frame.get("t"), (int, float)):
            continue
        item = {"t": max(0, min(28000, int(frame["t"])))}
        for key in ("opacity", "x", "y", "scale", "rotate"):
            if key in frame:
                item[key] = float(frame[key])
        camera_frames.append(item)
        max_t = max(max_t, item["t"])
    if not camera_frames:
        camera_frames = [{"t": 0, **DEFAULT_POSE}]
    duration = max(duration, max_t + 400, 800)
    return next_layers, {"keyframes": camera_frames}, min(28000, duration)


def _wrap_comp_document(ir: dict, layers: list[dict], camera: dict, duration: int,
                        composition: dict | None, render_settings: dict | None) -> dict:
    raw_composition = composition or {}
    width = max(320, min(3840, int(raw_composition.get("width") or 1080)))
    height = max(240, min(2160, int(raw_composition.get("height") or 1920)))
    fps = max(12, min(60, int(raw_composition.get("fps") or 30)))
    raw_render = render_settings or {}
    output_format = str(raw_render.get("format") or "mp4")
    if output_format not in {"mp4", "webm"}:
        output_format = "mp4"
    quality = str(raw_render.get("quality") or "high")
    if quality not in {"draft", "high", "lossless"}:
        quality = "high"
    duration = max(250, min(30000, int(duration)))
    viewport = "mobile" if height > width else "desktop"
    base_hash = str(ir.get("contentHash") or content_hash(ir))
    document = {
        "version": MOTION_VERSION,
        "source": {
            "interactionHash": content_hash({"mode": "comp", "base": base_hash}),
            "baseDesignIrHash": base_hash,
        },
        "composition": {
            "width": width, "height": height, "fps": fps,
            "duration": duration, "background": "#0b0b10",
        },
        "scenes": [{
            "id": "motion-comp-root",
            "interactionSceneId": "comp-root",
            "start": 0,
            "duration": duration,
            "viewport": viewport,
            "transition": {"type": "cut", "duration": 0, "easing": "linear"},
        }],
        "tracks": [{
            "id": "track-layers", "type": "scene", "name": "Layers", "locked": False,
            "clips": [{"id": "clip-comp", "sceneId": "motion-comp-root", "start": 0, "duration": duration, "locked": False}],
        }],
        "markers": [],
        "assets": [],
        "layers": layers,
        "camera": camera,
        "renderSettings": {
            "format": output_format,
            "codec": "h264" if output_format == "mp4" else "vp9",
            "quality": quality,
        },
    }
    errors = validate(document)
    if errors:
        raise ValueError("invalid Motion IR: " + "; ".join(errors[:5]))
    return document


def build_from_design(ir: dict, composition: dict | None = None,
                      render_settings: dict | None = None, plan: dict | None = None) -> dict:
    """Build a keyframed composition from page/component Design IR."""
    layers = layers_from_design(ir)
    if not layers:
        raise ValueError("В макете нет секций для ролика")
    if plan:
        layers, camera, duration = apply_director_plan(layers, plan)
    else:
        layers, camera, duration = default_product_comp(layers)
    return _wrap_comp_document(ir, layers, camera, duration, composition, render_settings)


def direct_comp_plan(ir: dict, prompt: str, composition: dict | None = None) -> dict:
    """Ask the motion director model for a keyframe plan. Falls back to the product preset."""
    from llm_client import chat

    layers = layers_from_design(ir)
    payload = {
        "prompt": prompt,
        "composition": composition or {},
        "layers": [{"id": layer["id"], "name": layer["name"], "sectionIndex": layer["sectionIndex"]} for layer in layers],
    }
    system = (
        "Ты motion-режиссёр в духе After Effects. Верни ТОЛЬКО JSON без markdown:\n"
        '{"duration": 6400, "layers": [{"id": "layer-0", "keyframes": '
        '[{"t": 0, "opacity": 0, "x": 0, "y": 40, "scale": 0.94, "rotate": 0}, '
        '{"t": 700, "opacity": 1, "x": 0, "y": 0, "scale": 1, "rotate": 0}]}], '
        '"camera": {"keyframes": [{"t": 0, "x": 0, "y": 0, "scale": 1}, {"t": 6400, "x": 0, "y": -80, "scale": 1.05}]}}\n'
        "Правила: используй только переданные id слоёв; t в мс от 0 до duration; "
        "2–6 кейфреймов на слой; анимируй сами компоненты (opacity/x/y/scale/rotate), "
        "не делай слайдшоу из целых экранов."
    )
    try:
        raw = chat("codex", [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], temperature=0.4, role="motion_director")
        from llm_client import extract_json
        plan = json.loads(extract_json(raw))
        if not isinstance(plan, dict) or not isinstance(plan.get("layers"), list):
            raise ValueError("director returned no layers")
        return plan
    except Exception:
        layers, camera, duration = default_product_comp(layers)
        return {"duration": duration, "layers": layers, "camera": camera}


class MotionIR(dict):
    @classmethod
    def empty(cls, composition: str = "16:9") -> "MotionIR":
        width, height = (1080, 1920) if composition == "9:16" else (1920, 1080)
        return cls({
            "version": MOTION_VERSION,
            "source": {"interactionHash": "", "baseDesignIrHash": ""},
            "composition": {"width": width, "height": height, "fps": 30, "duration": 0, "background": "#111116"},
            "scenes": [], "tracks": [], "markers": [], "assets": [],
            "renderSettings": {"format": "mp4", "codec": "h264", "quality": "high"},
        })
