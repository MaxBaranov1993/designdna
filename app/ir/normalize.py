"""Opt-in Style DNA normalization preview for Design IR 1.1."""
from __future__ import annotations

import copy
from typing import Any

from .hash import content_hash
from .style_dna import bind_element_styles, build_style_dna

SPACING = [0, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128]
FONT_SIZES = [12, 14, 16, 18, 20, 24, 30, 36, 48, 60, 72]
RADII = [0, 2, 4, 6, 8, 12, 16, 24, 9999]


def _snap(value: Any, scale: list[float], tolerance: float) -> Any:
    if not isinstance(value, (int, float)):
        return value
    nearest = min(scale, key=lambda candidate: abs(candidate - value))
    allowed = max(1.0, abs(float(value)) * tolerance)
    return nearest if abs(nearest - value) <= allowed else value


def _walk(ir: dict):
    def visit(node: dict, path: str):
        yield node, path
        for index, child in enumerate(node.get("children") or []):
            if isinstance(child, dict):
                yield from visit(child, f"{path}.children.{index}")
    for index, section in enumerate(ir.get("tree") or []):
        if isinstance(section, dict):
            yield from visit(section, f"tree.{index}")


def _record(changes: list[dict], path: str, before: Any, after: Any, token: str | None = None):
    if before == after:
        return
    item = {"path": path, "before": before, "after": after, "origin": "normalized"}
    if token:
        item["token"] = token
    changes.append(item)


def preview(ir: dict, tolerance: float = 0.12) -> dict:
    """Return a normalized copy and property-level diff without mutating input."""
    tolerance = max(0.0, min(float(tolerance), 0.5))
    original = copy.deepcopy(ir)
    tokens = original.get("tokens") if isinstance(original.get("tokens"), dict) else None
    if not tokens or not isinstance(tokens.get("semantic"), dict):
        tokens = build_style_dna(original)
    out = bind_element_styles(original, tokens)
    changes: list[dict] = []

    for node, path in _walk(out):
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        for prop in ("gap", "padding"):
            value = frame.get(prop)
            if isinstance(value, list):
                snapped = [_snap(item, SPACING, tolerance) for item in value]
            else:
                snapped = _snap(value, SPACING, tolerance)
            _record(changes, f"{path}.frame.{prop}", value, snapped)
            if value != snapped: frame[prop] = snapped

        style = node.get("style") if isinstance(node.get("style"), dict) else {}
        for prop, scale in (("fontSize", FONT_SIZES), ("borderRadius", RADII)):
            value = style.get(prop)
            snapped = _snap(value, scale, tolerance)
            _record(changes, f"{path}.style.{prop}", value, snapped)
            if value != snapped: style[prop] = snapped

        responsive = node.get("responsive") if isinstance(node.get("responsive"), dict) else {}
        for viewport, override in responsive.items():
            if not isinstance(override, dict): continue
            rframe = override.get("frame") if isinstance(override.get("frame"), dict) else {}
            for prop in ("gap", "padding"):
                value = rframe.get(prop)
                snapped = [_snap(item, SPACING, tolerance) for item in value] if isinstance(value, list) else _snap(value, SPACING, tolerance)
                _record(changes, f"{path}.responsive.{viewport}.frame.{prop}", value, snapped)
                if value != snapped: rframe[prop] = snapped
            rstyle = override.get("style") if isinstance(override.get("style"), dict) else {}
            for prop, scale in (("fontSize", FONT_SIZES), ("borderRadius", RADII)):
                value = rstyle.get(prop)
                snapped = _snap(value, scale, tolerance)
                _record(changes, f"{path}.responsive.{viewport}.style.{prop}", value, snapped)
                if value != snapped: rstyle[prop] = snapped

    out["tokens"] = tokens
    provenance = out.setdefault("provenance", {})
    provenance["normalizedFrom"] = original.get("contentHash") or content_hash(original)
    out["contentHash"] = content_hash(out)
    return {
        "normalizedIr": out,
        "patch": changes,
        "tokenChanges": sorted({item.get("token") for item in changes if item.get("token")}),
        "visualDelta": {
            "changedProperties": len(changes),
            "risk": "none" if not changes else ("low" if len(changes) <= 12 else "medium"),
            "requiresVisualReview": bool(changes),
        },
    }
