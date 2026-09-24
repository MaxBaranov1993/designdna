"""Timeline IR: authored video timelines over Design IR.

Контракт видео-монтажа: слои/группы с кейфреймами трансформаций поверх
готовых компонентов Design IR. Детерминированное извлечение слоёв из дерева
Design IR; интерполяция кейфреймов живёт в движке рендера
(`frontend/src/engine/timeline.ts`), здесь — контракт, валидация и обратимые
патчи (та же дисциплина, что SemanticChangeSet для Design IR).
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone

import jsonschema

from .hash import content_hash
from .schema import load_aux_schema

TIMELINE_VERSION = "timeline-ir/1.0"
CHANGE_SET_VERSION = "timeline-change-set/1.0"

ANIMATABLE_PROPERTIES = ("x", "y", "scale", "rotation", "opacity", "blur", "clip")
ALLOWED_EASINGS = ("linear", "ease", "ease-in", "ease-out", "ease-in-out", "cubic-bezier")
LAYER_TYPES = ("component", "group", "camera", "overlay")

# Детерминированная раскладка входного дизайна по слоям ограничена, чтобы
# таймлайн оставался обозримым: секции + их прямые дети, глубина <= 2.
EXTRACT_MAX_DEPTH = 2
EXTRACT_MAX_LAYERS = 256

# Границы сложности документа и патчей: контракт не должен расти бесконечно —
# ни от ручных правок, ни от ИИ-планов, ни от пресетов по сотням слоёв.
MAX_GROUPS = 64
MAX_KEYFRAMES_PER_TRACK = 256
MAX_TOTAL_KEYFRAMES = 4096
MAX_CHANGE_SET_OPERATIONS = 512
MAX_PROMPT_CHARS = 2000

# CSS-совместимые кривые для именованных изингов (паритет с движком рендера).
EASING_BEZIERS = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
}


def load_schema() -> dict:
    return load_aux_schema("timeline-ir")


def load_change_set_schema() -> dict:
    return load_aux_schema("timeline-change-set")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._:-]+", "-", str(value).lower()).strip("-")
    return slug or "node"


# --------------------------------------------------------------------------
# Валидация документа
# --------------------------------------------------------------------------

def validate(document: dict) -> list[str]:
    validator = jsonschema.Draft7Validator(load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    formatted = [f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}" for error in errors]
    if not isinstance(document, dict):
        return formatted

    composition = document.get("composition") if isinstance(document.get("composition"), dict) else {}
    duration = int(composition.get("duration") or 0)

    groups = document.get("groups") if isinstance(document.get("groups"), list) else []
    layers = document.get("layers") if isinstance(document.get("layers"), list) else []

    group_ids = [g.get("id") for g in groups if isinstance(g, dict)]
    if len(group_ids) != len(set(group_ids)):
        formatted.append("groups: ids must be unique")
    if len(groups) > MAX_GROUPS:
        formatted.append(f"groups: at most {MAX_GROUPS} groups are allowed")
    layer_ids = [layer.get("id") for layer in layers if isinstance(layer, dict)]
    if len(layer_ids) != len(set(layer_ids)):
        formatted.append("layers: ids must be unique")
    if len(layers) > EXTRACT_MAX_LAYERS:
        formatted.append(f"layers: at most {EXTRACT_MAX_LAYERS} layers are allowed")

    group_set = set(group_ids)
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        parent = group.get("parent")
        if parent is not None and parent not in group_set:
            formatted.append(f"groups/{index}/parent: group does not exist")

    total_keyframes = 0
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            continue
        prefix = f"layers/{index}"
        parent = layer.get("parent")
        if parent is not None and parent not in group_set:
            formatted.append(f"{prefix}/parent: group does not exist")
        if layer.get("type") == "component" and not layer.get("ref"):
            formatted.append(f"{prefix}/ref: component layers must reference a Design IR node")
        layer_in = int(layer.get("in") or 0)
        layer_out = int(layer.get("out") or 0)
        if layer_in >= layer_out:
            formatted.append(f"{prefix}: in must be less than out")
        if duration and layer_out > duration:
            formatted.append(f"{prefix}/out: exceeds composition duration")
        transform = layer.get("transform") if isinstance(layer.get("transform"), dict) else {}
        properties = transform.get("properties") if isinstance(transform.get("properties"), dict) else {}
        for prop, track in properties.items():
            if prop not in ANIMATABLE_PROPERTIES:
                formatted.append(f"{prefix}/transform/properties/{prop}: unknown property")
                continue
            keyframes = track.get("keyframes") if isinstance(track, dict) else None
            if not isinstance(keyframes, list):
                continue
            total_keyframes += len(keyframes)
            if len(keyframes) > MAX_KEYFRAMES_PER_TRACK:
                formatted.append(
                    f"{prefix}/transform/properties/{prop}: at most {MAX_KEYFRAMES_PER_TRACK} keyframes per track are allowed")
            previous_t = -1
            for kf_index, keyframe in enumerate(keyframes):
                if not isinstance(keyframe, dict):
                    continue
                t = int(keyframe.get("t") or 0)
                if t <= previous_t:
                    formatted.append(f"{prefix}/transform/properties/{prop}/keyframes/{kf_index}: t must be strictly ascending")
                if duration and t > duration:
                    formatted.append(f"{prefix}/transform/properties/{prop}/keyframes/{kf_index}: t exceeds duration")
                previous_t = t
                easing = keyframe.get("easing")
                if easing is not None and easing not in ALLOWED_EASINGS:
                    formatted.append(f"{prefix}/transform/properties/{prop}/keyframes/{kf_index}: unknown easing")
                if easing == "cubic-bezier" and not isinstance(keyframe.get("bezier"), list):
                    formatted.append(f"{prefix}/transform/properties/{prop}/keyframes/{kf_index}: cubic-bezier requires bezier handle")
                value = keyframe.get("value")
                if isinstance(value, (int, float)):
                    if prop == "opacity" and not 0 <= float(value) <= 1:
                        formatted.append(f"{prefix}/transform/properties/opacity/keyframes/{kf_index}: value must be within [0, 1]")
                    if prop == "scale" and float(value) < 0:
                        formatted.append(f"{prefix}/transform/properties/scale/keyframes/{kf_index}: value must be >= 0")
                    if prop == "blur" and not 0 <= float(value) <= 64:
                        formatted.append(f"{prefix}/transform/properties/blur/keyframes/{kf_index}: value must be within 0..64")
                    if prop == "clip" and not 0 <= float(value) <= 100:
                        formatted.append(f"{prefix}/transform/properties/clip/keyframes/{kf_index}: value must be within 0..100")
    if total_keyframes > MAX_TOTAL_KEYFRAMES:
        formatted.append(f"keyframes: at most {MAX_TOTAL_KEYFRAMES} keyframes are allowed per timeline")
    if not formatted and document.get("story"):
        from video_story import validate_story
        formatted.extend(validate_story(document["story"], duration))
    return formatted


# --------------------------------------------------------------------------
# Детерминированное извлечение слоёв из Design IR
# --------------------------------------------------------------------------

def _node_ref(node: dict, fallback_id: str) -> str:
    ref = node.get("sourceKey") or node.get("id") or fallback_id
    return str(ref)


def _node_name(node: dict, fallback: str) -> str:
    for key in ("type", "name", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return fallback


def extract_layers(design_ir: dict) -> dict:
    """Разложить дерево Design IR по группам и слоям для анимации.

    Секция дерева становится группой и компонентным слоем; её прямые дети —
    слоями внутри группы. Результат детерминирован: одинаковый вход даёт
    одинаковый манифест и одинаковый ``layerManifestHash``.
    """
    tree = design_ir.get("tree") if isinstance(design_ir.get("tree"), list) else []
    groups: list[dict] = []
    layers: list[dict] = []

    def empty_transform() -> dict:
        return {"anchor": {"x": 0.5, "y": 0.5}, "properties": {}}

    def add_element_layers(children: list, group_id: str, id_prefix: str, depth: int) -> None:
        if depth > EXTRACT_MAX_DEPTH or len(layers) >= EXTRACT_MAX_LAYERS:
            return
        for index, child in enumerate(children or []):
            if not isinstance(child, dict) or len(layers) >= EXTRACT_MAX_LAYERS:
                continue
            layer_id = f"layer-{id_prefix}-{index + 1}"
            layer = {
                "id": layer_id,
                "name": _node_name(child, f"element {index + 1}"),
                "type": "component",
                "ref": _node_ref(child, layer_id),
                "parent": group_id,
                "in": 0,
                "out": 0,
                "transform": empty_transform(),
            }
            if child.get("editable") is False:
                layer["locked"] = True
            layers.append(layer)
            nested = child.get("children")
            if isinstance(nested, list) and nested:
                add_element_layers(nested, group_id, f"{id_prefix}-{index + 1}", depth + 1)

    for section_index, section in enumerate(tree):
        if not isinstance(section, dict) or len(layers) >= EXTRACT_MAX_LAYERS:
            continue
        section_slug = _slug(section.get("id") or f"section-{section_index + 1}")
        group_id = f"grp-{section_slug}"
        groups.append({
            "id": group_id,
            "name": _node_name(section, f"section {section_index + 1}"),
            "parent": None,
        })
        layers.append({
            "id": f"layer-{section_slug}",
            "name": _node_name(section, f"section {section_index + 1}"),
            "type": "component",
            "ref": _node_ref(section, group_id),
            "parent": group_id,
            "in": 0,
            "out": 0,
            "transform": empty_transform(),
        })
        add_element_layers(section.get("children") or [], group_id, section_slug, 1)

    manifest = {"groups": groups, "layers": layers}
    return {"groups": groups, "layers": layers, "manifestHash": content_hash(manifest)}


# --------------------------------------------------------------------------
# Сборка таймлайна из Design IR
# --------------------------------------------------------------------------

def build(design_ir: dict, settings: dict | None = None) -> dict:
    """Собрать валидный Timeline IR из Design IR (детерминированно)."""
    raw = settings or {}
    width = max(320, min(3840, int(raw.get("width") or 1920)))
    height = max(240, min(2160, int(raw.get("height") or 1080)))
    fps = max(12, min(60, int(raw.get("fps") or 30)))
    duration = max(250, min(600000, int(raw.get("duration") or 6000)))
    background = str(raw.get("background") or "#111116")
    aspect = str(raw.get("aspect") or "")
    if aspect not in {"16:9", "9:16", "1:1", "custom"}:
        if (width, height) == (1920, 1080):
            aspect = "16:9"
        elif (width, height) == (1080, 1920):
            aspect = "9:16"
        elif width == height:
            aspect = "1:1"
        else:
            aspect = "custom"

    extracted = extract_layers(design_ir)
    layers = copy.deepcopy(extracted["layers"])
    for layer in layers:
        layer["in"] = 0
        layer["out"] = duration

    document = {
        "version": TIMELINE_VERSION,
        "source": {
            "designIrHash": content_hash(design_ir),
            "layerManifestHash": extracted["manifestHash"],
            "createdAt": _now(),
        },
        "composition": {
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "background": background,
            "aspect": aspect,
        },
        "groups": extracted["groups"],
        "layers": layers,
    }
    errors = validate(document)
    if errors:
        raise ValueError("invalid Timeline IR: " + "; ".join(errors[:5]))
    return document


# --------------------------------------------------------------------------
# Change-set: валидация и атомарное применение
# --------------------------------------------------------------------------

def validate_change_set(change_set: dict) -> list[str]:
    validator = jsonschema.Draft7Validator(load_change_set_schema())
    errors = sorted(validator.iter_errors(change_set), key=lambda error: list(error.path))
    formatted = [f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}" for error in errors]
    if not isinstance(change_set, dict):
        return formatted
    operations = change_set.get("operations") if isinstance(change_set.get("operations"), list) else []
    inverse = change_set.get("inverseOperations") if isinstance(change_set.get("inverseOperations"), list) else []
    if len(operations) > MAX_CHANGE_SET_OPERATIONS:
        formatted.append(
            f"operations: at most {MAX_CHANGE_SET_OPERATIONS} operations are allowed per change-set")
    op_ids = [op.get("id") for op in operations if isinstance(op, dict)]
    if len(op_ids) != len(set(op_ids)):
        formatted.append("operations: ids must be unique")
    forward_ids = set(op_ids)
    for index, op in enumerate(inverse):
        if not isinstance(op, dict):
            continue
        ref = op.get("inverseOf")
        if ref not in forward_ids:
            formatted.append(f"inverseOperations/{index}/inverseOf: must reference a forward operation id")
    return formatted


def _find_layer(document: dict, layer_id: str) -> dict | None:
    layers = document.get("layers") if isinstance(document.get("layers"), list) else []
    for layer in layers:
        if isinstance(layer, dict) and layer.get("id") == layer_id:
            return layer
    return None


def _composition_path_value(document: dict, path: str):
    composition = document.get("composition") if isinstance(document.get("composition"), dict) else {}
    key = path.lstrip("/")
    return composition.get(key)


def _previous_track(layer: dict, prop: str) -> dict:
    transform = layer.get("transform") if isinstance(layer.get("transform"), dict) else {}
    properties = transform.get("properties") if isinstance(transform.get("properties"), dict) else {}
    track = properties.get(prop)
    return copy.deepcopy(track) if isinstance(track, dict) else {"keyframes": []}


def _previous_layer_property(layer: dict, path: str):
    key = path.lstrip("/")
    return copy.deepcopy(layer.get(key))


# Кинематографические кривые, которые пресеты пишут как cubic-bezier: CSS-имена
# (ease-out и т.п.) слишком «механические» для продуктового ролика.
NAMED_CURVES = {
    "expo-out": (0.16, 1.0, 0.3, 1.0),
    "quart-out": (0.25, 1.0, 0.5, 1.0),
    "back-out": (0.34, 1.56, 0.64, 1.0),
    "smooth": (0.65, 0.0, 0.35, 1.0),
    "cinematic": (0.4, 0.0, 0.1, 1.0),
}

# Слой камеры: один на документ, двигает всю композицию (движок применяет его
# трансформацию к обёртке страницы, а не к секции).
CAMERA_LAYER_ID = "camera"
CAMERA_PRESETS = ("camera-push", "camera-pull", "camera-pan", "camera-drift")


def keyframe(t: int, value: float, curve: str | None = None) -> dict:
    """Кейфрейм с именованной кривой (NAMED_CURVES) или CSS-изингом."""
    item: dict = {"t": int(t), "value": value}
    if curve in NAMED_CURVES:
        item["easing"] = "cubic-bezier"
        item["bezier"] = list(NAMED_CURVES[curve])
    elif curve in ALLOWED_EASINGS and curve != "cubic-bezier":
        item["easing"] = curve
    return item


def camera_layer(duration: int) -> dict:
    return {
        "id": CAMERA_LAYER_ID, "name": "Camera", "type": "camera", "parent": None,
        "in": 0, "out": max(250, int(duration)),
        "transform": {"anchor": {"x": 0.5, "y": 0.5}, "properties": {}},
    }


def has_camera_layer(timeline: dict) -> bool:
    return any(isinstance(layer, dict) and layer.get("id") == CAMERA_LAYER_ID
               for layer in (timeline.get("layers") or []))


def ensure_camera_operations(timeline: dict) -> list[dict]:
    """Операция add-layer для камеры, если её ещё нет (пустой список иначе)."""
    if has_camera_layer(timeline):
        return []
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    return [{"kind": "add-layer", "target": CAMERA_LAYER_ID,
             "value": camera_layer(int(composition.get("duration") or 6000))}]


def merge_keyframe_operations(timeline: dict, operations: list[dict]) -> list[dict]:
    """Слить set-keyframes по (слой, свойство): пресеты на одном свойстве
    дополняют друг друга и существующий трек, а не затирают его.

    Кейфреймы сортируются по времени; при совпадении времени побеждает более
    поздняя операция. Остальные операции проходят без изменений и сохраняют
    место первого set-keyframes своей группы.
    """
    layers = {str(layer.get("id")): layer for layer in (timeline.get("layers") or []) if isinstance(layer, dict)}
    merged: dict[tuple[str, str], dict] = {}
    result: list[dict] = []
    added_layers: set[str] = set()
    for op in operations:
        if op.get("kind") == "add-layer":
            # Несколько источников (шаблон + акцент) могут просить один и тот же
            # слой камеры: второй add-layer сломал бы уникальность id.
            target = str(op.get("target"))
            if target in added_layers or target in layers:
                continue
            added_layers.add(target)
            result.append(op)
            continue
        if op.get("kind") != "set-keyframes":
            result.append(op)
            continue
        key = (str(op.get("target")), str(op.get("path")))
        value = op.get("value")
        incoming = value.get("keyframes") if isinstance(value, dict) else value
        incoming = [kf for kf in (incoming or []) if isinstance(kf, dict)]
        if key not in merged:
            existing: list[dict] = []
            layer = layers.get(key[0])
            match = re.fullmatch(r"/transform/properties/([a-z]+)", key[1])
            if layer and match:
                track = ((layer.get("transform") or {}).get("properties") or {}).get(match.group(1))
                existing = [kf for kf in ((track or {}).get("keyframes") or []) if isinstance(kf, dict)]
            merged[key] = {"kind": "set-keyframes", "target": key[0], "path": key[1],
                           "payload": copy.deepcopy(op.get("payload") or {}),
                           "_by_t": {int(kf["t"]): copy.deepcopy(kf) for kf in existing}}
            result.append(merged[key])
        for kf in incoming:
            merged[key]["_by_t"][int(kf["t"])] = copy.deepcopy(kf)
    for op in merged.values():
        by_t = op.pop("_by_t")
        op["value"] = {"keyframes": [by_t[t] for t in sorted(by_t)]}
    return result


def preset_operations(preset: str, layer_ids: list[str], params: dict) -> list[dict]:
    """Детерминированные операции пресетов (явные кейфреймы, без LLM).

    ``params``: start, duration, staggerMs, travel (px), curve (имя из
    NAMED_CURVES или CSS-изинг) — переопределяет кривую пресета.
    """
    start = max(0, int(params.get("start") or 0))
    duration = max(100, int(params.get("duration") or 800))
    stagger = max(0, int(params.get("staggerMs") or 0))
    travel = int(params.get("travel") or 240)
    curve_override = params.get("curve")
    if curve_override is not None and curve_override not in NAMED_CURVES and curve_override not in ALLOWED_EASINGS:
        raise ValueError(f"unknown curve: {curve_override!r}")
    operations: list[dict] = []

    def curve(default: str) -> str:
        return str(curve_override or default)

    def track(layer_id: str, prop: str, keyframes: list[dict]) -> dict:
        return {"kind": "set-keyframes", "target": layer_id, "path": f"/transform/properties/{prop}",
                "value": {"keyframes": keyframes}, "payload": {"preset": preset}}

    def fade_ops(layer_id: str, s: int, e: int) -> list[dict]:
        return [track(layer_id, "opacity", [keyframe(s, 0, curve("expo-out")), keyframe(e, 1)])]

    for index, layer_id in enumerate(layer_ids):
        s = start + stagger * index
        e = s + duration
        mid = s + duration // 2
        if preset == "fade-in":
            operations.extend(fade_ops(layer_id, s, e))
        elif preset == "fade-in-up":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "y", [keyframe(s, travel, curve("expo-out")), keyframe(e, 0)]))
        elif preset == "slide-in-left":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "x", [keyframe(s, -travel, curve("expo-out")), keyframe(e, 0)]))
        elif preset == "slide-in-right":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "x", [keyframe(s, travel, curve("expo-out")), keyframe(e, 0)]))
        elif preset == "zoom-in":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "scale", [keyframe(s, 0.92, curve("expo-out")), keyframe(e, 1)]))
        elif preset == "scale-reveal":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "scale", [keyframe(s, 0.88, curve("back-out")), keyframe(e, 1)]))
        elif preset == "focus-pull":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "blur", [keyframe(s, 14, curve("expo-out")), keyframe(e, 0)]))
        elif preset == "wipe-reveal":
            operations.append(track(layer_id, "clip", [keyframe(s, 100, curve("expo-out")), keyframe(e, 0)]))
        elif preset == "wipe-out":
            operations.append(track(layer_id, "clip", [keyframe(s, 0, curve("smooth")), keyframe(e, 100)]))
        elif preset == "defocus":
            operations.append(track(layer_id, "blur", [keyframe(s, 0, curve("smooth")), keyframe(e, 6)]))
        elif preset == "rotate-in":
            operations.extend(fade_ops(layer_id, s, e))
            operations.append(track(layer_id, "rotation", [keyframe(s, -4, curve("expo-out")), keyframe(e, 0)]))
            operations.append(track(layer_id, "y", [keyframe(s, travel // 3, curve("expo-out")), keyframe(e, 0)]))
        elif preset == "zoom-spotlight":
            operations.append(track(layer_id, "scale", [keyframe(s, 1, curve("cinematic")), keyframe(e, 1.12)]))
        elif preset == "hero-focus":
            operations.append(track(layer_id, "scale", [keyframe(s, 1, curve("quart-out")), keyframe(e, 1.04)]))
        elif preset == "dim":
            operations.append(track(layer_id, "opacity", [keyframe(s, 1, curve("smooth")), keyframe(e, 0.35)]))
        elif preset == "fade-out":
            operations.append(track(layer_id, "opacity", [keyframe(s, 1, curve("smooth")), keyframe(e, 0)]))
        elif preset == "pan-down":
            operations.append(track(layer_id, "y", [keyframe(s, 0, curve("cinematic")), keyframe(e, -travel)]))
        elif preset == "drift-up":
            operations.append(track(layer_id, "y", [keyframe(s, travel // 6, curve("linear")), keyframe(e, -(travel // 6))]))
        elif preset == "cta-pulse":
            operations.append(track(layer_id, "scale", [keyframe(s, 1, curve("smooth")), keyframe(mid, 1.08, curve("smooth")), keyframe(e, 1)]))
        elif preset == "cta-bounce":
            operations.append(track(layer_id, "y", [keyframe(s, 0, curve("back-out")), keyframe(mid, -14, curve("back-out")), keyframe(e, 0)]))
            operations.append(track(layer_id, "scale", [keyframe(s, 1, curve("back-out")), keyframe(mid, 1.06, curve("back-out")), keyframe(e, 1)]))
        elif preset == "camera-push":
            operations.append(track(layer_id, "scale", [keyframe(s, 1, curve("cinematic")), keyframe(e, 1.08)]))
        elif preset == "camera-pull":
            operations.append(track(layer_id, "scale", [keyframe(s, 1.08, curve("cinematic")), keyframe(e, 1)]))
        elif preset == "camera-pan":
            operations.append(track(layer_id, "y", [keyframe(s, 0, curve("cinematic")), keyframe(e, -travel)]))
        elif preset == "camera-drift":
            operations.append(track(layer_id, "x", [keyframe(s, 0, curve("smooth")), keyframe(e, travel // 8)]))
            operations.append(track(layer_id, "y", [keyframe(s, 0, curve("smooth")), keyframe(e, -(travel // 12))]))
        else:
            raise ValueError(f"unknown preset: {preset!r}")
    return operations


PRESET_NAMES = (
    "fade-in", "fade-in-up", "slide-in-left", "slide-in-right", "zoom-in", "scale-reveal", "focus-pull", "rotate-in",
    "wipe-reveal", "wipe-out",
    "zoom-spotlight", "hero-focus", "dim", "defocus", "fade-out", "pan-down", "drift-up", "cta-pulse", "cta-bounce",
    "camera-push", "camera-pull", "camera-pan", "camera-drift",
)


def _apply_operation(document: dict, op: dict) -> None:
    kind = op.get("kind")
    target = str(op.get("target") or "")
    path = str(op.get("path") or "")
    if kind == "set-story":
        if op.get("value") is None:
            document.pop("story", None)
        else:
            document["story"] = copy.deepcopy(op["value"])
        return
    if kind == "set-composition":
        composition = document.setdefault("composition", {})
        key = path.lstrip("/")
        if key not in {"width", "height", "fps", "duration", "background", "aspect"}:
            raise ValueError(f"set-composition: unknown path {path!r}")
        composition[key] = op.get("value")
        return
    if kind == "add-layer":
        layer = op.get("value")
        if not isinstance(layer, dict):
            raise ValueError("add-layer: value must be a layer object")
        document.setdefault("layers", []).append(copy.deepcopy(layer))
        return
    if kind == "remove-layer":
        layers = document.get("layers") or []
        kept = [layer for layer in layers if not (isinstance(layer, dict) and layer.get("id") == target)]
        if len(kept) == len(layers):
            raise ValueError(f"remove-layer: layer {target!r} not found")
        document["layers"] = kept
        return
    if kind == "reorder-layer":
        layers = document.get("layers") or []
        index = next((i for i, layer in enumerate(layers) if isinstance(layer, dict) and layer.get("id") == target), None)
        if index is None:
            raise ValueError(f"reorder-layer: layer {target!r} not found")
        new_index = int(op.get("value") or 0)
        layer = layers.pop(index)
        layers.insert(max(0, min(len(layers), new_index)), layer)
        return
    layer = _find_layer(document, target)
    if layer is None:
        raise ValueError(f"layer {target!r} not found")
    if kind == "set-layer-property":
        key = path.lstrip("/")
        if key not in {"in", "out", "parent", "name", "locked"}:
            raise ValueError(f"set-layer-property: unknown path {path!r}")
        layer[key] = op.get("value")
        return
    if kind == "set-anchor":
        value = op.get("value")
        if not isinstance(value, dict):
            raise ValueError("set-anchor: value must be {x, y}")
        layer.setdefault("transform", {})["anchor"] = {"x": float(value.get("x", 0.5)), "y": float(value.get("y", 0.5))}
        return
    if kind == "set-keyframes":
        match = re.fullmatch(r"/transform/properties/([a-z]+)", path)
        if not match or match.group(1) not in ANIMATABLE_PROPERTIES:
            raise ValueError(f"set-keyframes: invalid path {path!r}")
        prop = match.group(1)
        value = op.get("value")
        keyframes = value.get("keyframes") if isinstance(value, dict) else value
        if not isinstance(keyframes, list):
            raise ValueError("set-keyframes: value must contain keyframes[]")
        transform = layer.setdefault("transform", {"anchor": {"x": 0.5, "y": 0.5}, "properties": {}})
        properties = transform.setdefault("properties", {})
        if keyframes:
            properties[prop] = {"keyframes": copy.deepcopy(keyframes)}
        else:
            # пустой трек = «анимации нет»: свойство удаляется, чтобы инверсии
            # возвращали слой в исходное состояние без артефактов
            properties.pop(prop, None)
        return
    raise ValueError(f"unknown operation: {kind!r}")


def build_change_set(document: dict, intent: str, operations: list[dict],
                     actor: str = "timeline-director", scope: list[str] | None = None) -> dict:
    """Собрать change-set с автоматическими инверсными операциями.

    Инверсия каждой операции вычисляется по текущему состоянию документа,
    поэтому применение ``inverseOperations`` возвращает таймлайн в исходное
    состояние (договор atomic/reversible).
    """
    if not isinstance(document, dict):
        raise ValueError("timeline document is required")
    if len(operations) > MAX_CHANGE_SET_OPERATIONS:
        raise ValueError(
            f"too many operations ({len(operations)} > {MAX_CHANGE_SET_OPERATIONS}) — "
            "shorten the request or split changes across multiple patches")
    work = copy.deepcopy(document)
    forward: list[dict] = []
    inverse: list[dict] = []
    for index, raw_op in enumerate(operations):
        op = copy.deepcopy(raw_op)
        op_id = f"op-{index + 1}"
        op["id"] = op_id
        kind = op.get("kind")
        target = str(op.get("target") or "")
        path = str(op.get("path") or "")
        inv: dict = {"id": f"inv-{index + 1}", "inverseOf": op_id, "kind": kind, "target": target}
        if kind == "set-story":
            inv["value"] = copy.deepcopy(work.get("story"))
        elif kind == "set-composition":
            inv["path"] = path
            inv["value"] = _composition_path_value(work, path)
        elif kind == "add-layer":
            inv["kind"] = "remove-layer"
            layer = op.get("value") if isinstance(op.get("value"), dict) else {}
            inv["target"] = str(layer.get("id") or target)
        elif kind == "remove-layer":
            inv["kind"] = "add-layer"
            inv["value"] = copy.deepcopy(_find_layer(work, target))
        elif kind == "set-layer-property":
            layer = _find_layer(work, target)
            inv["path"] = path
            inv["value"] = _previous_layer_property(layer, path) if layer else None
        elif kind == "set-anchor":
            layer = _find_layer(work, target)
            transform = layer.get("transform") if layer else {}
            inv["value"] = copy.deepcopy(transform.get("anchor") or {"x": 0.5, "y": 0.5})
        elif kind == "set-keyframes":
            match = re.fullmatch(r"/transform/properties/([a-z]+)", path)
            layer = _find_layer(work, target)
            inv["path"] = path
            inv["value"] = _previous_track(layer, match.group(1)) if (layer and match) else {"keyframes": []}
        elif kind == "reorder-layer":
            layers = work.get("layers") or []
            inv["value"] = next((i for i, layer in enumerate(layers) if isinstance(layer, dict) and layer.get("id") == target), 0)
        elif kind == "apply-preset":
            payload = op.get("payload") if isinstance(op.get("payload"), dict) else {}
            preset = str(payload.get("preset") or "")
            params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            layer_ids = payload.get("layerIds") if isinstance(payload.get("layerIds"), list) else [target]
            expanded = preset_operations(preset, [str(item) for item in layer_ids], params)
            inv_restore: list[dict] = []
            for exp_index, expanded_op in enumerate(expanded):
                match = re.fullmatch(r"/transform/properties/([a-z]+)", str(expanded_op.get("path") or ""))
                expanded_layer = _find_layer(work, str(expanded_op.get("target") or ""))
                inv_restore.append({
                    "id": f"inv-{index + 1}-{exp_index + 1}",
                    "inverseOf": op_id,
                    "kind": "set-keyframes",
                    "target": expanded_op.get("target"),
                    "path": expanded_op.get("path"),
                    "value": _previous_track(expanded_layer, match.group(1)) if (expanded_layer and match) else {"keyframes": []},
                })
            # применяем развёрнутые операции вместо apply-preset, инверсии уже сняты
            for expanded_op in expanded:
                _apply_operation(work, expanded_op)
            op["kind"] = "apply-preset"
            forward.append(op)
            inverse.extend(inv_restore)
            continue
        else:
            raise ValueError(f"unknown operation: {kind!r}")
        _apply_operation(work, op)
        forward.append(op)
        inverse.append(inv)

    change_set = {
        "version": CHANGE_SET_VERSION,
        "id": f"tcs-{content_hash({'intent': intent, 'ops': forward})[:16]}",
        "baseTimelineHash": content_hash(document),
        "intent": intent[:500],
        "scope": scope or list(dict.fromkeys(str(op.get("target")) for op in forward))[:8],
        "operations": forward,
        "inverseOperations": list(reversed(inverse)),
        "atomic": True,
        "status": "draft",
        "actor": actor[:120],
        "createdAt": _now(),
    }
    errors = validate_change_set(change_set)
    if errors:
        raise ValueError("invalid TimelineChangeSet: " + "; ".join(errors[:5]))
    return change_set


def apply_change_set(document: dict, change_set: dict, check_hash: bool = True) -> dict:
    """Атомарно применить change-set. Любая ошибка — отказ без частичных правок."""
    errors = validate_change_set(change_set)
    if errors:
        raise ValueError("invalid TimelineChangeSet: " + "; ".join(errors[:5]))
    if check_hash:
        expected = str(change_set.get("baseTimelineHash") or "")
        if expected and content_hash(document) != expected:
            raise ValueError("baseTimelineHash mismatch: timeline changed after patch preparation")
    for precondition in change_set.get("preconditions") or []:
        if not isinstance(precondition, dict):
            continue
        kind = precondition.get("kind")
        if kind == "timeline-hash-match" and content_hash(document) != precondition.get("expected"):
            raise ValueError("timeline-hash-match precondition failed")
        if kind == "layer-exists" and _find_layer(document, str(precondition.get("target") or "")) is None:
            raise ValueError(f"layer-exists precondition failed: {precondition.get('target')!r}")
    work = copy.deepcopy(document)
    for op in change_set.get("operations") or []:
        if not isinstance(op, dict):
            raise ValueError("operation must be an object")
        kind = op.get("kind")
        if kind == "apply-preset":
            payload = op.get("payload") if isinstance(op.get("payload"), dict) else {}
            preset = str(payload.get("preset") or "")
            params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
            layer_ids = payload.get("layerIds") if isinstance(payload.get("layerIds"), list) else [op.get("target")]
            for expanded in preset_operations(preset, [str(item) for item in layer_ids], params):
                _apply_operation(work, expanded)
            continue
        _apply_operation(work, op)
    errors = validate(work)
    if errors:
        raise ValueError("Timeline IR invalid after apply: " + "; ".join(errors[:5]))
    return work


def revert_change_set(document: dict, change_set: dict) -> dict:
    """Откатить применённый change-set его инверсными операциями.

    Операции отката — это ``inverseOperations`` исходного патча; их собственные
    инверсии восстанавливают исходные прямые операции, поэтому откат отката
    возвращает применённое состояние.
    """
    inverse = change_set.get("inverseOperations") or []
    forward_replay = copy.deepcopy(change_set.get("operations") or [])
    inv_id_by_forward: dict[str, str] = {}
    for inv in inverse:
        if isinstance(inv, dict):
            inv_id_by_forward.setdefault(str(inv.get("inverseOf") or ""), str(inv.get("id") or ""))
    for op in forward_replay:
        if not isinstance(op, dict):
            continue
        matched = inv_id_by_forward.get(str(op.get("id") or ""))
        if matched:
            op["inverseOf"] = matched
    revert_operations = copy.deepcopy(inverse)
    for op in revert_operations:
        if isinstance(op, dict):
            op.pop("inverseOf", None)
    revert = {
        "version": CHANGE_SET_VERSION,
        "id": f"revert-{str(change_set.get('id') or 'unknown')[:64]}",
        "baseTimelineHash": content_hash(document),
        "intent": f"revert: {change_set.get('intent', '')}",
        "scope": change_set.get("scope") or ["timeline"],
        "operations": revert_operations,
        "inverseOperations": forward_replay,
        "atomic": True,
        "status": "draft",
        "actor": "timeline-revert",
        "createdAt": _now(),
    }
    return apply_change_set(document, revert, check_hash=False)


class TimelineIR(dict):
    @classmethod
    def empty(cls, aspect: str = "16:9") -> "TimelineIR":
        width, height = (1080, 1920) if aspect == "9:16" else (1080, 1080) if aspect == "1:1" else (1920, 1080)
        return cls({
            "version": TIMELINE_VERSION,
            "source": {"designIrHash": "", "layerManifestHash": "", "createdAt": _now()},
            "composition": {"width": width, "height": height, "fps": 30, "duration": 0,
                            "background": "#111116", "aspect": aspect if aspect in {"16:9", "9:16", "1:1"} else "custom"},
            "groups": [],
            "layers": [],
        })

    @classmethod
    def from_json(cls, text: str) -> "TimelineIR":
        return cls(json.loads(text))
