"""Fluid responsive materialization helpers for Design IR 1.1."""
from __future__ import annotations

import copy

BREAKPOINTS = {
    "mobile": (320, 639),
    "tablet": (640, 1023),
    "desktop": (1024, 2560),
}

DEFAULT_VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}


def ensure_fluid_layout(ir: dict) -> dict:
    """Add conservative breakpoint fallbacks for generated card rows.

    Explicit device direction/wrap values always win. Source Import normally
    carries those measured overrides already, while generated repeated-card
    rows often only contain the desktop auto-layout frame.
    """
    out = copy.deepcopy(ir)
    responsive = out.setdefault("responsive", {})
    if not isinstance(responsive, dict):
        responsive = {}
        out["responsive"] = responsive
    viewports = responsive.setdefault("viewports", {})
    if not isinstance(viewports, dict):
        viewports = {}
        responsive["viewports"] = viewports
    for viewport, meta in DEFAULT_VIEWPORTS.items():
        current = viewports.setdefault(viewport, {})
        if not isinstance(current, dict):
            viewports[viewport] = copy.deepcopy(meta)
            continue
        for key, value in meta.items():
            current.setdefault(key, value)

    def visit(node: dict):
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        children = [child for child in node.get("children") or [] if isinstance(child, dict)]
        is_card_row = (
            frame.get("layout") == "auto"
            and frame.get("direction") == "row"
            and len(children) >= 2
            and all(child.get("type") == "card" for child in children)
        )
        if is_card_row:
            node_responsive = node.setdefault("responsive", {})
            if isinstance(node_responsive, dict):
                for viewport in ("tablet", "mobile"):
                    override = node_responsive.setdefault(viewport, {})
                    if not isinstance(override, dict):
                        continue
                    override_frame = override.setdefault("frame", {})
                    if not isinstance(override_frame, dict):
                        continue
                    if "direction" not in override_frame and "wrap" not in override_frame:
                        override_frame["wrap"] = True
        for child in children:
            visit(child)

    for section in out.get("tree") or []:
        if isinstance(section, dict):
            visit(section)
    return out


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
