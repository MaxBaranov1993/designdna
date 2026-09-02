"""Motion IR construction and validation for editable product-flow videos."""
from __future__ import annotations

import jsonschema

from .hash import content_hash
from .schema import load_aux_schema

MOTION_VERSION = "1.0"
ALLOWED_TRANSITIONS = {"cut", "fade", "slide-left", "slide-up", "zoom"}
ALLOWED_EASINGS = {"linear", "ease", "ease-in", "ease-out", "ease-in-out"}
def load_schema() -> dict:
    return load_aux_schema("motion-ir")


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
