"""Deterministic Tailwind projection for Design IR 1.1.

The projection is derived output: it never mutates Design IR and can always be
rebuilt from the canonical document. Exact mode emits arbitrary utilities;
normalized mode prefers semantic Style DNA utilities and Tailwind scales.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .hash import content_hash

VIEWPORTS = (("mobile", ""), ("tablet", "md:"), ("desktop", "lg:"))
SPACING_SCALE = {
    0: "0", 2: "0.5", 4: "1", 6: "1.5", 8: "2", 10: "2.5", 12: "3",
    16: "4", 20: "5", 24: "6", 32: "8", 40: "10", 48: "12",
    64: "16", 80: "20", 96: "24", 128: "32",
}
RADIUS_SCALE = {0: "none", 2: "sm", 4: "", 6: "md", 8: "lg", 12: "xl", 16: "2xl", 24: "3xl", 9999: "full"}
FONT_SIZE_SCALE = {12: "xs", 14: "sm", 16: "base", 18: "lg", 20: "xl", 24: "2xl", 30: "3xl", 36: "4xl", 48: "5xl", 60: "6xl", 72: "7xl"}


def _walk(ir: dict):
    def visit(node: dict, path: str, parent: dict | None = None):
        yield node, path, parent
        for index, child in enumerate(node.get("children") or []):
            if isinstance(child, dict):
                yield from visit(child, f"{path}.children.{index}", node)

    for index, section in enumerate(ir.get("tree") or []):
        if isinstance(section, dict):
            yield from visit(section, f"tree.{index}")


def _merge_viewport(node: dict, viewport: str) -> dict:
    out = copy.deepcopy(node)
    responsive = node.get("responsive") if isinstance(node.get("responsive"), dict) else {}
    override = responsive.get(viewport) if isinstance(responsive.get(viewport), dict) else {}
    for key in ("frame", "style", "styleBindings"):
        if isinstance(override.get(key), dict):
            out[key] = {**(out.get(key) if isinstance(out.get(key), dict) else {}), **override[key]}
    if "visible" in override:
        out["visible"] = override["visible"]
    return out


def _number(value: Any) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else (f"{value:.4f}".rstrip("0").rstrip("."))


def _arbitrary(value: Any, unit: str = "") -> str:
    if isinstance(value, str):
        safe = value.replace(" ", "_").replace("'", "\\'")
        return f"[{safe}]"
    return f"[{_number(value)}{unit}]"


def _scaled(prefix: str, value: Any, scale: dict, mode: str, unit: str = "px") -> str:
    if mode == "normalized" and isinstance(value, (int, float)) and value in scale:
        suffix = scale[value]
        return prefix if suffix == "" else f"{prefix}-{suffix}"
    return f"{prefix}-{_arbitrary(value, unit)}"


def _padding_classes(value: Any, mode: str) -> list[str]:
    if isinstance(value, (int, float)):
        return [_scaled("p", value, SPACING_SCALE, mode)]
    if isinstance(value, list) and len(value) == 2:
        return [_scaled("py", value[0], SPACING_SCALE, mode), _scaled("px", value[1], SPACING_SCALE, mode)]
    if isinstance(value, list) and len(value) == 4:
        return [_scaled(prefix, item, SPACING_SCALE, mode) for prefix, item in zip(("pt", "pr", "pb", "pl"), value)]
    return []


def _frame_classes(frame: dict, mode: str, parent_free: bool) -> list[str]:
    out: list[str] = []
    layout = frame.get("layout")
    if layout == "auto":
        out.append("flex")
        out.append("flex-row" if frame.get("direction") == "row" else "flex-col")
    elif layout == "free":
        out.append("relative")
    if frame.get("absolute") or parent_free:
        out.append("absolute")
    for prop, prefix in (("width", "w"), ("height", "h"), ("minWidth", "min-w"), ("maxWidth", "max-w"), ("minHeight", "min-h"), ("maxHeight", "max-h")):
        value = frame.get(prop)
        if value == "fill": out.append(f"{prefix}-full")
        elif value == "hug": out.append(f"{prefix}-fit")
        elif isinstance(value, (int, float)): out.append(f"{prefix}-{_arbitrary(value, 'px')}")
    if isinstance(frame.get("x"), (int, float)): out.append(f"left-{_arbitrary(frame['x'], 'px')}")
    if isinstance(frame.get("y"), (int, float)): out.append(f"top-{_arbitrary(frame['y'], 'px')}")
    if isinstance(frame.get("gap"), (int, float)): out.append(_scaled("gap", frame["gap"], SPACING_SCALE, mode))
    out.extend(_padding_classes(frame.get("padding"), mode))
    justify = {"start":"justify-start", "center":"justify-center", "end":"justify-end", "space-between":"justify-between", "space-around":"justify-around"}
    align = {"start":"items-start", "center":"items-center", "end":"items-end", "stretch":"items-stretch", "baseline":"items-baseline"}
    if frame.get("justify") in justify: out.append(justify[frame["justify"]])
    if frame.get("align") in align: out.append(align[frame["align"]])
    if frame.get("wrap") is True: out.append("flex-wrap")
    if frame.get("wrap") is False: out.append("flex-nowrap")
    if isinstance(frame.get("rotation"), (int, float)): out.append(f"rotate-{_arbitrary(frame['rotation'], 'deg')}")
    if frame.get("clip"): out.append("overflow-hidden")
    return out


def _semantic_utility(prop: str, binding: Any) -> str | None:
    if not isinstance(binding, dict):
        return None
    token = str(binding.get("token", ""))
    if not token.startswith("semantic."):
        return None
    role = re.sub(r"[^a-zA-Z0-9-]", "-", token[9:])
    return {"background": f"bg-{role}", "color": f"text-{role}", "borderColor": f"border-{role}"}.get(prop)


def _style_classes(style: dict, bindings: dict, mode: str) -> list[str]:
    out: list[str] = []
    color_props = {"background": "bg", "color": "text", "borderColor": "border"}
    for prop, prefix in color_props.items():
        value = style.get(prop)
        if not isinstance(value, str): continue
        semantic = _semantic_utility(prop, bindings.get(prop)) if mode == "normalized" else None
        out.append(semantic or f"{prefix}-{_arbitrary(value)}")
    if isinstance(style.get("borderWidth"), (int, float)):
        out.extend(["border-solid", f"border-{_arbitrary(style['borderWidth'], 'px')}"])
    family = style.get("fontFamily")
    if isinstance(family, str) and family.strip(): out.append(f"font-{_arbitrary("'" + family.strip() + "'")}")
    if isinstance(style.get("fontSize"), (int, float)): out.append(_scaled("text", style["fontSize"], FONT_SIZE_SCALE, mode))
    if isinstance(style.get("fontWeight"), (int, float)): out.append(f"font-{int(style['fontWeight'])}")
    if isinstance(style.get("lineHeight"), (int, float)): out.append(f"leading-{_arbitrary(style['lineHeight'])}")
    if isinstance(style.get("letterSpacing"), (int, float)): out.append(f"tracking-{_arbitrary(style['letterSpacing'], 'px')}")
    if isinstance(style.get("borderRadius"), (int, float)): out.append(_scaled("rounded", style["borderRadius"], RADIUS_SCALE, mode))
    if isinstance(style.get("boxShadow"), str) and style["boxShadow"]: out.append(f"shadow-{_arbitrary(style['boxShadow'])}")
    direct = {
        "underline":"underline", "line-through":"line-through", "overline":"overline", "nowrap":"whitespace-nowrap",
        "pre":"whitespace-pre", "pre-wrap":"whitespace-pre-wrap", "pre-line":"whitespace-pre-line", "break-spaces":"whitespace-break-spaces",
        "visible":"overflow-visible", "hidden":"overflow-hidden", "clip":"overflow-clip", "scroll":"overflow-scroll", "auto":"overflow-auto",
        "uppercase":"uppercase", "lowercase":"lowercase", "capitalize":"capitalize",
        "contain":"object-contain", "cover":"object-cover", "fill":"object-fill", "none":"object-none", "scale-down":"object-scale-down",
    }
    for prop in ("textDecoration", "whiteSpace", "overflow", "textTransform", "objectFit"):
        if style.get(prop) in direct: out.append(direct[style[prop]])
    if isinstance(style.get("opacity"), (int, float)): out.append(f"opacity-{_arbitrary(style['opacity'])}")
    return out


def _classes(node: dict, mode: str, parent_free: bool) -> list[str]:
    if node.get("visible") is False:
        return ["hidden"]
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    bindings = node.get("styleBindings") if isinstance(node.get("styleBindings"), dict) else {}
    classes = _frame_classes(frame, mode, parent_free) + _style_classes(style, bindings, mode)
    return list(dict.fromkeys(classes))


def _theme(ir: dict) -> dict:
    tokens = ir.get("tokens") if isinstance(ir.get("tokens"), dict) else {}
    semantic = tokens.get("semantic") if isinstance(tokens.get("semantic"), dict) else {}
    colors = {key: value for key, value in semantic.items() if key in {"primary","secondary","accent","background","surface","text","textMuted","border"} and isinstance(value, str)}
    return {
        "cssVariables": {f"--dna-{key}": value for key, value in colors.items()},
        "extend": {
            "colors": {key: f"var(--dna-{key})" for key in colors},
            "fontFamily": {
                key[:-4]: [value["family"]] for key, value in semantic.items()
                if key in ("displayFont", "bodyFont") and isinstance(value, dict) and isinstance(value.get("family"), str)
            },
        },
    }


def project(ir: dict, mode: str = "exact") -> dict:
    """Return a deterministic, mobile-first Tailwind projection."""
    if mode not in ("exact", "normalized"):
        raise ValueError("mode must be exact or normalized")
    nodes = []
    diagnostics: list[dict] = []
    has_responsive = isinstance(ir.get("responsive"), dict)
    for node, path, parent in _walk(ir):
        groups: dict[str, list[str]] = {}
        for viewport, prefix in VIEWPORTS:
            materialized = _merge_viewport(node, viewport) if has_responsive else node
            materialized_parent = _merge_viewport(parent, viewport) if has_responsive and parent else parent
            parent_frame = materialized_parent.get("frame") if isinstance(materialized_parent, dict) and isinstance(materialized_parent.get("frame"), dict) else {}
            parent_free = parent_frame.get("layout") == "free"
            classes = _classes(materialized, mode, parent_free)
            groups[viewport] = [prefix + item for item in classes]
        if not has_responsive:
            groups = {"base": groups["desktop"]}
        key = node.get("sourceKey") or path
        nodes.append({"sourceKey": key, "path": path, "type": node.get("type", "unknown"), "classes": groups})
        if not node.get("sourceKey"):
            diagnostics.append({"level": "warning", "sourceKey": key, "message": "Fallback path used because sourceKey is missing."})
    return {
        "version": "1.0",
        "irHash": ir.get("contentHash") or content_hash(ir),
        "mode": mode,
        "breakpoints": {"md": 640, "lg": 1024},
        "theme": _theme(ir),
        "nodes": nodes,
        "diagnostics": diagnostics,
    }
