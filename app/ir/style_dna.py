"""Style DNA extraction, binding and application for Design IR.

Stage-1 contract:
- Primitives are real measured values from the source (colors, fonts, sizes,
  radii, spacings, border widths, shadows).
- Semantic tokens map primitives to roles (primary, surface, text, border,
  buttonRadius, sectionGap, ...).
- styleBindings link element style properties to tokens without replacing the
  exact measured value.
- Applying a token update recursively rewrites bound styles and responsive
  overrides while preserving unbound exact properties.
"""
from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .hash import canonical_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if not s or s in ("transparent", "none", "null"):
        return None
    if len(s) == 4 and s.startswith("#"):
        return "#" + "".join(c + c for c in s[1:])
    if len(s) == 7 and s.startswith("#"):
        return s
    return None


def _walk_nodes(ir: dict):
    if isinstance(ir, dict):
        yield ir
        for child in ir.get("tree", []):
            yield from _walk_nodes(child)
        for child in ir.get("children", []):
            yield from _walk_nodes(child)
    elif isinstance(ir, list):
        for item in ir:
            yield from _walk_nodes(item)


def _node_style(node: dict) -> dict:
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    if node.get("type") == "rect" and isinstance(node.get("fill"), str):
        style = {**style, "background": node["fill"]}
    return style


def _responsive_styles(node: dict):
    responsive = node.get("responsive")
    if not isinstance(responsive, dict):
        return
    for viewport, override in responsive.items():
        if isinstance(override, dict) and isinstance(override.get("style"), dict):
            yield viewport, override, override["style"]


# ---------- primitives ----------


def extract_primitives(ir: dict) -> dict:
    """Collect measured exact values from an IR tree."""
    color_counts: Counter[str] = Counter()
    text_color_counts: Counter[str] = Counter()
    bg_color_counts: Counter[str] = Counter()
    fonts: list[dict] = []
    font_sizes: list[float] = []
    radii: list[float] = []
    spacings: list[float] = []
    border_widths: list[float] = []
    shadows: list[str] = []

    seen_fonts: set[str] = set()
    seen_shadows: set[str] = set()

    for node in _walk_nodes(ir):
        style = _node_style(node)
        node_type = node.get("type")

        for key in ("color", "background", "borderColor"):
            color = _hex_color(style.get(key))
            if color:
                color_counts[color] += 1
                if key == "color":
                    text_color_counts[color] += 1
                if key == "background":
                    bg_color_counts[color] += 1

        family = style.get("fontFamily")
        weight = style.get("fontWeight")
        if isinstance(family, str) and family.strip():
            font_key = f"{family.strip()}|{weight}"
            if font_key not in seen_fonts:
                seen_fonts.add(font_key)
                fonts.append({"family": family.strip(), "weight": weight if isinstance(weight, int) else 400})

        size = style.get("fontSize")
        if isinstance(size, (int, float)) and size > 0:
            font_sizes.append(float(size))

        radius = style.get("borderRadius")
        if isinstance(radius, (int, float)):
            radii.append(float(radius))

        width = style.get("borderWidth")
        if isinstance(width, (int, float)):
            border_widths.append(float(width))

        shadow = style.get("boxShadow")
        if isinstance(shadow, str) and shadow.strip() and shadow != "none" and shadow not in seen_shadows:
            seen_shadows.add(shadow)
            shadows.append(shadow)

        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        for spacing_key in ("gap", "padding"):
            value = frame.get(spacing_key)
            if isinstance(value, (int, float)) and value > 0:
                spacings.append(float(value))
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, (int, float)) and v > 0:
                        spacings.append(float(v))

    # Background is the most common background color; text is the most common text color.
    colors_by_freq = [c for c, _ in color_counts.most_common()]
    return {
        "colors": colors_by_freq,
        "fonts": sorted(fonts, key=lambda f: (f["family"], f["weight"])),
        "fontSizes": sorted(set(font_sizes)),
        "radii": sorted(set(radii)),
        "spacings": sorted(set(spacings)),
        "borderWidths": sorted(set(border_widths)),
        "shadows": shadows,
        "_bg_counts": dict(bg_color_counts.most_common()),
        "_text_counts": dict(text_color_counts.most_common()),
    }


# ---------- semantic mapping ----------


def _closest(value: float, values: list[float]) -> float:
    if not values:
        return value
    return min(values, key=lambda v: abs(v - value))


def _most_common(values: list[Any], fallback: Any) -> Any:
    if not values:
        return fallback
    return Counter(values).most_common(1)[0][0]


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    rgb = tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def build_semantic(primitives: dict, mode: str | None = None) -> dict:
    """Map measured primitives to semantic tokens."""
    colors = primitives.get("colors") or []
    fonts = primitives.get("fonts") or []
    radii = primitives.get("radii") or []
    spacings = primitives.get("spacings") or []
    bg_counts = primitives.get("_bg_counts") or {}
    text_counts = primitives.get("_text_counts") or {}

    if not colors:
        colors = ["#ffffff", "#171717"]

    # Background and text are decided by frequency in their respective style properties.
    background = max(bg_counts, key=bg_counts.get) if bg_counts else colors[0]
    text = max(text_counts, key=text_counts.get) if text_counts else (
        "#f8fafc" if _luminance(background) < 0.5 else "#171717"
    )

    # Infer mode from background luminance if not provided.
    if mode is None:
        mode = "dark" if _luminance(background) < 0.5 else "light"

    # Primary: the most common non-background, non-text color (likely buttons/links).
    primary = text
    for c, count in Counter({c: count for c, count in Counter(colors).items() if c not in (background, text)}).most_common():
        primary = c
        break

    surface_candidates = [c for c in colors if c not in (background, text, primary)]
    surface = surface_candidates[0] if surface_candidates else background

    muted_candidates = [c for c in colors if c not in (background, text, primary, surface)]
    text_muted = muted_candidates[0] if muted_candidates else ("#a1a1aa" if mode == "dark" else "#666666")

    border_candidates = [c for c in colors if c not in (background,)]
    border = border_candidates[-1] if border_candidates else ("#2a2a32" if mode == "dark" else "#e0e0e0")

    display_font = fonts[0] if fonts else {"family": "Inter", "weight": 700}
    body_font = fonts[-1] if len(fonts) > 1 else (fonts[0] if fonts else {"family": "Inter", "weight": 400})

    return {
        "primary": primary,
        "secondary": primary,
        "accent": primary,
        "background": background,
        "surface": surface,
        "text": text,
        "textMuted": text_muted,
        "border": border,
        "buttonRadius": _closest(8, radii) if radii else 8,
        "cardRadius": _closest(16, radii) if radii else 16,
        "inputRadius": _closest(8, radii) if radii else 8,
        "sectionGap": _closest(96, spacings) if spacings else 96,
        "containerWidth": 1200,
        "displayFont": display_font,
        "bodyFont": body_font,
    }


def _schema_compatible_tokens(semantic: dict, mode: str) -> dict:
    """Return the legacy schema token contract from semantic values."""
    return {
        "mode": mode,
        "color": {
            "primary": semantic["primary"],
            "secondary": semantic.get("secondary") or semantic["primary"],
            "accent": semantic.get("accent") or semantic["primary"],
            "background": semantic["background"],
            "surface": semantic["surface"],
            "text": semantic["text"],
            "textMuted": semantic["textMuted"],
            "border": semantic["border"],
        },
        "font": {
            "display": semantic.get("displayFont") or {"family": "Inter", "weight": 700},
            "body": semantic.get("bodyFont") or {"family": "Inter", "weight": 400},
            "scale": "default",
        },
        "radius": {
            "card": _radius_enum(semantic.get("cardRadius", 16)),
            "button": _radius_enum(semantic.get("buttonRadius", 8)),
            "input": _radius_enum(semantic.get("inputRadius", 8)),
        },
        "spacing": {
            "section": _section_spacing_enum(semantic.get("sectionGap", 96)),
            "container": "default",
        },
        "shadow": "none",
    }


def _radius_enum(px: float) -> str:
    if px <= 0:
        return "none"
    if px <= 4:
        return "sm"
    if px <= 12:
        return "md"
    if px <= 24:
        return "lg"
    if px <= 48:
        return "xl"
    return "full"


def _section_spacing_enum(px: float) -> str:
    if px <= 48:
        return "sm"
    if px <= 80:
        return "md"
    if px <= 120:
        return "lg"
    return "xl"


# ---------- build full DNA ----------


def build_style_dna(ir: dict, source: str | None = None) -> dict:
    """Build a complete Style DNA token set from an IR document."""
    primitives = extract_primitives(ir)
    mode = ir.get("tokens", {}).get("mode") if isinstance(ir.get("tokens"), dict) else None
    semantic = build_semantic(primitives, mode=mode)
    base = _schema_compatible_tokens(semantic, semantic.get("mode", "light"))
    # Persist only the public primitive lists, not internal frequency counters.
    base["primitives"] = {k: v for k, v in primitives.items() if not k.startswith("_")}
    base["semantic"] = semantic
    base["provenance"] = {
        "schemaVersion": "1.1",
        "createdAt": _now(),
        "generator": "style-dna-v1",
    }
    if source:
        base["provenance"]["importedFrom"] = source
    return base


# ---------- bindings ----------


def _token_for_value(value: Any, primitives: dict, semantic: dict) -> str | None:
    """Return the best semantic or primitive token name for a measured value."""
    color = _hex_color(value)
    if color:
        for role in ("primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"):
            if semantic.get(role) == color:
                return f"semantic.{role}"
        colors = primitives.get("colors") or []
        if color in colors:
            return f"primitive.color.{colors.index(color)}"
        return None

    if isinstance(value, (int, float)):
        radius = semantic.get("buttonRadius")
        if radius is not None and abs(float(value) - radius) < 0.5:
            return "semantic.buttonRadius"
        card_radius = semantic.get("cardRadius")
        if card_radius is not None and abs(float(value) - card_radius) < 0.5:
            return "semantic.cardRadius"
        return None

    return None


def bind_element_styles(ir: dict, tokens: dict | None = None) -> dict:
    """Add styleBindings to every element in the IR tree.

    Existing bindings are overwritten. The exact measured value is preserved.
    Semantic role bindings (button -> primary, text -> text, etc.) take
    precedence over primitive bindings so Style DNA updates propagate visually.
    """
    ir = copy.deepcopy(ir)
    if tokens is None:
        tokens = build_style_dna(ir)
    primitives = tokens.get("primitives", {})
    semantic = tokens.get("semantic", {})

    def _semantic_role_binding(node: dict, prop: str, value: Any) -> str | None:
        """Return a semantic token for well-known element/property pairs."""
        node_type = node.get("type", "")
        label = str(node.get("text", node.get("title", ""))).lower()
        is_action = node_type == "button" or (
            label and any(k in label for k in ("найти", "войти", "разместить", "search", "login", "sign", "post", "submit", "buy", "send"))
        )
        color = _hex_color(value)
        if prop == "background" and color and color not in ("#ffffff", "#fff", "transparent", "none"):
            if is_action:
                return "semantic.primary"
            if node_type in ("card", "section", "source-block"):
                return "semantic.surface"
            if node_type == "input":
                return "semantic.background"
        if prop == "color" and color:
            if is_action:
                return "semantic.background"
            if node_type in ("text", "heading"):
                return "semantic.text"
        if prop == "borderColor" and color:
            return "semantic.border"
        if prop == "borderRadius":
            if is_action:
                return "semantic.buttonRadius"
            if node_type in ("card", "section"):
                return "semantic.cardRadius"
            if node_type == "input":
                return "semantic.inputRadius"
        return None

    for node in _walk_nodes(ir):
        style = _node_style(node)
        if not style:
            continue
        bindings: dict[str, dict] = {}
        for prop, value in style.items():
            token = _semantic_role_binding(node, prop, value)
            if not token:
                token = _token_for_value(value, primitives, semantic)
            if token:
                bindings[prop] = {"property": prop, "token": token, "origin": "imported"}
        if bindings:
            node["styleBindings"] = bindings
        # Bind responsive overrides too.
        for viewport, override, rstyle in _responsive_styles(node):
            rbindings: dict[str, dict] = {}
            for prop, value in rstyle.items():
                token = _semantic_role_binding(node, prop, value)
                if not token:
                    token = _token_for_value(value, primitives, semantic)
                if token:
                    rbindings[prop] = {"property": prop, "token": token, "origin": "imported"}
            if rbindings:
                override["styleBindings"] = rbindings
    return ir


# ---------- application ----------


def _resolve_token(token: str, tokens: dict) -> Any:
    if token.startswith("semantic."):
        return tokens.get("semantic", {}).get(token[9:])
    if token.startswith("primitive.color."):
        idx = int(token[16:])
        colors = tokens.get("primitives", {}).get("colors") or []
        if 0 <= idx < len(colors):
            return colors[idx]
    return None


def apply_tokens(ir: dict, tokens: dict) -> dict:
    """Recursively update bound styles with new token values.

    Unbound exact properties are left untouched.
    """
    ir = copy.deepcopy(ir)
    for node in _walk_nodes(ir):
        bindings = node.get("styleBindings")
        if isinstance(bindings, dict):
            style = node.setdefault("style", {})
            for prop, binding in bindings.items():
                value = _resolve_token(binding.get("token", ""), tokens)
                if value is not None:
                    style[prop] = value
                    binding["origin"] = "manual"
        # Apply responsive bindings.
        for viewport, override, rstyle in _responsive_styles(node):
            rbindings = override.get("styleBindings")
            if isinstance(rbindings, dict):
                for prop, binding in rbindings.items():
                    value = _resolve_token(binding.get("token", ""), tokens)
                    if value is not None:
                        rstyle[prop] = value
                        binding["origin"] = "manual"
    # Update root tokens preserving primitives/semantic structure.
    if isinstance(ir.get("tokens"), dict):
        ir["tokens"] = {**ir["tokens"], **tokens}
    else:
        ir["tokens"] = tokens
    return ir


# ---------- source import bridge ----------


def enrich_ir(ir: dict, source: str | None = None) -> dict:
    """Attach full Style DNA primitives, semantic tokens and styleBindings to an IR document.

    Display-токены (mode/color/font/radius/spacing/shadow), замеренные capture'ом
    на живом DOM, точнее эвристик build_style_dna: renderer темит артборд по ним,
    и их подмена ломает pixel parity со источником. Поэтому валидные захваченные
    токены сохраняются; primitives/semantic/styleBindings добавляются всегда.
    """
    ir = copy.deepcopy(ir)
    existing = ir.get("tokens") if isinstance(ir.get("tokens"), dict) else None
    tokens = build_style_dna(ir, source=source)
    if existing and {"mode", "color", "font", "radius", "spacing", "shadow"}.issubset(existing):
        tokens = {**tokens, **{key: existing[key]
                               for key in ("mode", "color", "font", "radius", "spacing", "shadow")
                               if key in existing}}
    ir = bind_element_styles(ir, tokens)
    ir["tokens"] = tokens
    return ir


def extract_from_signals(signals: dict, source: str | None = None) -> dict | None:
    """Convert legacy page-token signals into the new Style DNA model."""
    if not isinstance(signals, dict):
        return None
    try:
        bg = _hex_color(str(signals.get("bodyBg") or "#ffffff")) or "#ffffff"
        text = _hex_color(str(signals.get("bodyColor") or "#171717")) or "#171717"
        mode = "dark" if _luminance(bg) < 0.5 else "light"
        primary = _hex_color(str(signals.get("buttonBg") or "")) or text
        link = _hex_color(str(signals.get("linkColor") or "")) or primary
        muted = _hex_color(str(signals.get("mutedColor") or ""))
        border = _hex_color(str(signals.get("borderColor") or ""))
        display = signals.get("displayFont") or {}
        body_font = signals.get("bodyFont") or {}

        semantic = {
            "primary": primary,
            "secondary": primary,
            "accent": link,
            "background": bg,
            "surface": bg,
            "text": text,
            "textMuted": muted or ("#9ca3af" if mode == "dark" else "#666666"),
            "border": border or ("#374151" if mode == "dark" else "#d1d5db"),
            "buttonRadius": _median(signals.get("buttonRadius")) or 8,
            "cardRadius": _median(signals.get("cardRadius")) or 16,
            "inputRadius": _median(signals.get("inputRadius")) or 8,
            "sectionGap": _median(signals.get("sectionPadding")) or 96,
            "containerWidth": _median(signals.get("containerWidth")) or 1200,
            "displayFont": {"family": _font_family(display.get("family")), "weight": _snap_weight(display.get("weight"), 700)},
            "bodyFont": {"family": _font_family(body_font.get("family")), "weight": _snap_weight(body_font.get("weight"), 400)},
        }
        base = _schema_compatible_tokens(semantic, mode)
        base["primitives"] = {
            "colors": [c for c in {bg, text, primary, link, muted, border} if c],
            "fonts": [semantic["displayFont"], semantic["bodyFont"]],
            "radii": [semantic["buttonRadius"], semantic["cardRadius"], semantic["inputRadius"]],
            "spacings": [semantic["sectionGap"]],
        }
        base["semantic"] = semantic
        base["provenance"] = {
            "schemaVersion": "1.1",
            "createdAt": _now(),
            "generator": "style-dna-signals-v1",
        }
        if source:
            base["provenance"]["importedFrom"] = source
        return base
    except Exception:
        return None


def _median(values: Any) -> float | None:
    if not isinstance(values, list) or not values:
        return None
    nums = sorted(v for v in values if isinstance(v, (int, float)))
    if not nums:
        return None
    mid = len(nums) // 2
    return float(nums[mid] if len(nums) % 2 else (nums[mid - 1] + nums[mid]) / 2)


def _font_family(value: Any) -> str:
    if not isinstance(value, str):
        return "Inter"
    family = value.split(",")[0].strip().strip('"\'')
    return family or "Inter"


def _snap_weight(value: Any, fallback: int) -> int:
    weights = {300, 400, 500, 600, 700, 800, 900}
    try:
        w = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(weights, key=lambda x: abs(x - w))
