"""AI-починка захвата с детерминированным судьёй.

Модель здесь НЕ измеряет и не придумывает геометрию: числа уже даёт браузер
через getBoundingClientRect/getComputedStyle, и заменить их гипотезой значит
сделать хуже. Модель делает то, чего не умеет детерминированный код —
смотрит на эталон и рендер и ставит диагноз: «здесь потеряно свечение»,
«фон обрезан по глифам», «контейнер уехал в потоке».

Контур замкнут на harness: каждое предложение применяется к копии IR, пиксельное
сходство меряется заново, и правка принимается ТОЛЬКО если сходство выросло.
Поэтому модель физически не может ухудшить результат — худший исход это
отсутствие улучшения и откат.

Набор операций намеренно узкий: восстановить визуальный канал, который в
источнике есть, а в IR не доехал. Ни создания узлов, ни свободных чисел.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable

# Свойства, которые модели разрешено восстанавливать. Это ровно те визуальные
# каналы, которые компилятор может потерять; геометрия (frame/x/y/width) сюда
# намеренно не входит — она измерена и не обсуждается.
REPAIRABLE_STYLE_PROPS = {
    "textShadow", "boxShadow", "backgroundClip", "backgroundImage",
    "opacity", "mixBlendMode", "filter", "letterSpacing", "textTransform",
    "fontWeight", "fontStyle", "textDecoration", "borderRadius", "color",
}
# Charset тот же, что у компилятора для shadow/filter: без url() и expression().
_SAFE_CSS_VALUE = re.compile(r"^[a-zA-Z0-9\s(),.%#/-]{1,300}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

REPAIR_OPS = ("restore-style", "pin-children", "raster-fallback")


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def region_rects(report_viewport: dict, limit: int = 4) -> list[dict]:
    """Худшие регионы 8×8-сетки harness → прямоугольники в пикселях блока."""
    diffs = report_viewport.get("region_diffs")
    size = report_viewport.get("reference_size") or report_viewport.get("render_size")
    if not isinstance(diffs, list) or not isinstance(size, list) or len(size) != 2:
        return []
    width, height = int(size[0]), int(size[1])
    grid = 8
    ordered = sorted(
        (item for item in diffs if isinstance(item, dict) and isinstance(item.get("region"), list)),
        key=lambda item: -float(item.get("mismatch_pct") or 0),
    )
    rects = []
    for item in ordered[:limit]:
        row, col = int(item["region"][0]), int(item["region"][1])
        rects.append({
            "x": width * col // grid,
            "y": height * row // grid,
            "width": width * (col + 1) // grid - width * col // grid,
            "height": height * (row + 1) // grid - height * row // grid,
            "mismatchPct": float(item.get("mismatch_pct") or 0),
        })
    return rects


def _absolute_frames(ir: dict) -> dict[str, dict]:
    """sourceKey → абсолютный кадр внутри блока (кадры в IR относительны)."""
    frames: dict[str, dict] = {}

    def visit(node: Any, offset_x: float, offset_y: float) -> None:
        if not isinstance(node, dict):
            return
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        x = offset_x + float(frame.get("x") or 0)
        y = offset_y + float(frame.get("y") or 0)
        key = str(node.get("sourceKey") or "")
        if key and frame.get("width") is not None:
            frames[key] = {"x": x, "y": y,
                           "width": float(frame.get("width") or 0),
                           "height": float(frame.get("height") or 0)}
        for child in node.get("children") or []:
            visit(child, x, y)

    for root in ir.get("tree") or []:
        visit(root, 0.0, 0.0)
    return frames


def nodes_in_region(ir: dict, rect: dict, limit: int = 12) -> list[dict]:
    """Узлы IR, пересекающие регион расхождения — вход диагностики."""
    frames = _absolute_frames(ir)
    by_key = {str(node.get("sourceKey") or ""): node for node in _walk(ir.get("tree") or [])
              if node.get("sourceKey")}
    rx0, ry0 = rect["x"], rect["y"]
    rx1, ry1 = rx0 + rect["width"], ry0 + rect["height"]
    hits = []
    for key, frame in frames.items():
        fx1, fy1 = frame["x"] + frame["width"], frame["y"] + frame["height"]
        if frame["x"] >= rx1 or fx1 <= rx0 or frame["y"] >= ry1 or fy1 <= ry0:
            continue
        node = by_key.get(key) or {}
        # Корень блока пересекает КАЖДЫЙ регион и никогда не объясняет
        # локальное расхождение — в диагностике это чистый шум.
        if str(node.get("type") or "") == "source-block":
            continue
        area = max(1.0, frame["width"] * frame["height"])
        hits.append({
            "sourceKey": key,
            "type": str(node.get("type") or ""),
            "text": str(node.get("text") or "")[:80],
            "frame": {name: round(value, 1) for name, value in frame.items()},
            "style": {name: value for name, value in (node.get("style") or {}).items()
                      if name in REPAIRABLE_STYLE_PROPS},
            "_area": area,
        })
    hits.sort(key=lambda item: item["_area"])  # мелкие узлы точнее описывают расхождение
    for item in hits:
        item.pop("_area", None)
    return hits[:limit]


def build_repair_prompt(block_name: str, viewport: str, rect: dict,
                        nodes: list[dict], metrics: dict) -> list[dict]:
    """Сообщения диагностики. Модель отвечает гипотезой и правками из набора."""
    system = (
        "You compare a website screenshot region with its reconstructed render and "
        "explain WHY they differ. The geometry is already measured by the browser and "
        "is not up for debate: never propose coordinates, sizes or positions. "
        "Only propose restoring visual channels that exist in the source but are "
        "missing from the reconstruction (glow, gradient text fill, shadow, blend, "
        "opacity, letter spacing, weight). If a node cannot be represented at all, "
        "propose a raster fallback. Return ONE JSON object, no prose."
    )
    schema = {
        "hypothesis": "one sentence: what is visually different and why",
        "operations": [
            {"op": "restore-style", "sourceKey": "<key from the list>",
             "property": "one of " + ", ".join(sorted(REPAIRABLE_STYLE_PROPS)),
             "value": "CSS value"},
            {"op": "pin-children", "sourceKey": "<container key>"},
            {"op": "raster-fallback", "sourceKey": "<key>"},
        ],
    }
    payload = {
        "block": block_name,
        "viewport": viewport,
        "region": rect,
        "measured": {
            "pixelSimilarity": metrics.get("pixel_similarity"),
            "bboxP95": metrics.get("bbox_p95"),
        },
        "nodesInRegion": nodes,
        "output": schema,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def validate_operations(parsed: Any, ir: dict) -> list[dict]:
    """Строгая валидация ответа: только известные операции по существующим узлам."""
    if not isinstance(parsed, dict):
        raise ValueError("repair response must be a JSON object")
    raw_ops = parsed.get("operations")
    if not isinstance(raw_ops, list):
        raise ValueError("operations must be a list")
    known = {str(node.get("sourceKey") or "") for node in _walk(ir.get("tree") or [])
             if node.get("sourceKey")}
    clean: list[dict] = []
    for raw in raw_ops[:12]:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "")
        source_key = str(raw.get("sourceKey") or "")
        if op not in REPAIR_OPS or source_key not in known:
            continue
        if op == "restore-style":
            prop = str(raw.get("property") or "")
            value = raw.get("value")
            if prop not in REPAIRABLE_STYLE_PROPS:
                continue
            if prop in ("opacity", "fontWeight", "borderRadius", "letterSpacing"):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                clean.append({"op": op, "sourceKey": source_key, "property": prop,
                              "value": float(value)})
                continue
            text = str(value or "").strip()
            if not text:
                continue
            if prop == "color" and not _HEX.match(text):
                continue
            if not _SAFE_CSS_VALUE.match(text):
                continue
            clean.append({"op": op, "sourceKey": source_key, "property": prop, "value": text})
        else:
            clean.append({"op": op, "sourceKey": source_key})
    return clean


def apply_operations(ir: dict, operations: list[dict]) -> dict:
    """Применить правки к КОПИИ IR. Геометрия не меняется ни одной операцией."""
    patched = copy.deepcopy(ir)
    by_key = {str(node.get("sourceKey") or ""): node for node in _walk(patched.get("tree") or [])
              if node.get("sourceKey")}
    for operation in operations:
        node = by_key.get(operation["sourceKey"])
        if node is None:
            continue
        if operation["op"] == "restore-style":
            style = node.setdefault("style", {})
            if isinstance(style, dict):
                style[operation["property"]] = operation["value"]
        elif operation["op"] == "pin-children":
            # Контейнер уехал в потоке: закрепляем детей по УЖЕ ИЗМЕРЕННЫМ
            # кадрам, а не по числам от модели.
            frame = node.get("frame")
            if isinstance(frame, dict):
                frame["layout"] = "free"
            for child in node.get("children") or []:
                child_frame = child.get("frame") if isinstance(child, dict) else None
                if isinstance(child_frame, dict) and child_frame.get("width") is not None:
                    child_frame["absolute"] = True
        elif operation["op"] == "raster-fallback":
            meta = node.setdefault("sourceMeta", {})
            if isinstance(meta, dict):
                meta["kind"] = "raster-repair"
            node["editable"] = False
    return patched


def make_browser_measurer(page, reference_png: bytes, viewport: str,
                          width: int, height: int) -> Callable[[dict], float | None]:
    """Судья: рендерит IR тем же движком и меряет сходство с тем же эталоном.

    Это ровно та метрика, по которой работает fidelity-гейт — цикл не может
    «улучшить» результат по своей отдельной шкале.
    """
    from fidelity_harness import _image_metrics, _render_block_png

    def measure(candidate: dict) -> float | None:
        try:
            render_png = _render_block_png(page, candidate, viewport, width, height)
            metrics = _image_metrics(reference_png, render_png)
        except Exception:
            return None
        value = metrics.get("pixel_similarity")
        return None if value is None else float(value)

    return measure


def repair_block(ir: dict, *, block_name: str, viewport: str, report_viewport: dict,
                 measure: Callable[[dict], float | None],
                 propose: Callable[[list[dict]], str],
                 max_regions: int = 3,
                 min_gain: float = 0.15) -> dict:
    """Замкнутый цикл: диагноз → правка → повторный замер → принять/откатить.

    `measure(ir) -> pixel_similarity` и `propose(messages) -> raw JSON` внедряются
    снаружи: юнит-тесты гоняют логику без браузера и без сети.
    Правка принимается только если сходство выросло минимум на `min_gain`.
    """
    baseline = measure(ir)
    if baseline is None:
        return {"applied": [], "rejected": [], "baseline": None, "similarity": None,
                "reason": "baseline similarity is unavailable"}
    current_ir = copy.deepcopy(ir)
    current = float(baseline)
    applied: list[dict] = []
    rejected: list[dict] = []

    for rect in region_rects(report_viewport, limit=max_regions):
        nodes = nodes_in_region(current_ir, rect)
        if not nodes:
            continue
        messages = build_repair_prompt(block_name, viewport, rect, nodes, report_viewport)
        try:
            raw = propose(messages)
            match = re.search(r"\{.*\}", str(raw or ""), re.S)
            if not match:
                continue
            operations = validate_operations(json.loads(match.group(0)), current_ir)
        except (ValueError, json.JSONDecodeError):
            continue
        if not operations:
            continue
        candidate = apply_operations(current_ir, operations)
        score = measure(candidate)
        if score is None or float(score) < current + min_gain:
            rejected.append({"region": rect, "operations": operations,
                             "similarity": None if score is None else float(score)})
            continue
        current_ir = candidate
        current = float(score)
        applied.append({"region": rect, "operations": operations, "similarity": current})

    return {
        "ir": current_ir,
        "applied": applied,
        "rejected": rejected,
        "baseline": float(baseline),
        "similarity": current,
        "gain": round(current - float(baseline), 2),
    }
