"""Fluid responsive materialization helpers for Design IR 1.1."""
from __future__ import annotations

import copy

BREAKPOINTS = {
    "mobile": (320, 639),
    "tablet": (640, 1023),
    "desktop": (1024, 2560),
}


def viewport_for_width(width: int | float) -> str:
    """Resolve a custom canvas width to the canonical editing viewport."""
    width = max(320, min(int(width), 2560))
    if width < 640:
        return "mobile"
    if width < 1024:
        return "tablet"
    return "desktop"


def clamp_width(width: int | float) -> int:
    return max(320, min(int(width), 2560))


def materialize(ir: dict, width: int | float) -> dict:
    """Return a runtime copy with the matching override and exact canvas width."""
    out = copy.deepcopy(ir)
    width = clamp_width(width)
    viewport = viewport_for_width(width)
    meta = out.get("responsive", {}).get("viewports", {}).get(viewport, {})
    out["frame"] = {**(out.get("frame") or {}), "width": width}
    if isinstance(meta.get("height"), (int, float)):
        out["frame"]["height"] = meta["height"]

    def visit(node: dict):
        override = node.get("responsive", {}).get(viewport, {}) if isinstance(node.get("responsive"), dict) else {}
        if override.get("visible") is False:
            node["__responsiveHidden"] = True
        for key in ("frame", "style", "styleBindings"):
            if isinstance(override.get(key), dict):
                node[key] = {**(node.get(key) or {}), **override[key]}
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for section in out.get("tree") or []:
        if isinstance(section, dict):
            visit(section)
    out.setdefault("meta", {})["activeViewport"] = viewport
    return out


def property_source(node: dict, viewport: str, group: str) -> str:
    """Report whether frame/style values are shared or viewport-specific."""
    if viewport == "desktop":
        return "shared"
    override = node.get("responsive", {}).get(viewport, {}) if isinstance(node.get("responsive"), dict) else {}
    return viewport if isinstance(override.get(group), dict) and override[group] else "shared"
