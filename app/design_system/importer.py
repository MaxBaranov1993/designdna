"""Импорт дизайн-системы из файла — «загруженная» ДС наравне с собранной из Source.

Закрывает боль AI-редакторов, где библиотеку надо заново искать на диске при
каждом запуске, а свой стиль «закинуть» нельзя. Принимаем три формата:

- документ DesignDNA (экспорт другого проекта / кит): ``schemaVersion`` +
  ``foundations`` — переносится целиком, вместе с мастерами и вариантами;
- W3C Design Tokens / Tokens Studio JSON (то, что выгружает Figma):
  ``{"color": {"primary": {"$type": "color", "$value": "#…"}}}`` или
  ``{"global": {"colors": {"primary": {"value": "#…", "type": "color"}}}}``;
- плоская карта shadcn/ui (``background/foreground/primary/…``) либо
  IR-токены v1 (``mode/color/font/radius/spacing/shadow``).

Результат — черновик документа ДС (revision 0) с foundations, styleGuide и
irTokens, который генератор лочит так же, как ДС из Source.

Публичный API:
- detect_format(payload) -> "designdna-document" | "design-tokens" | "token-map" | None
- import_design_system(payload, *, name="", file_name="") -> dict (draft)
"""
from __future__ import annotations

import copy
import re
from typing import Any

from . import document as dsdoc
from .style_review import coerce_ir_tokens, ensure_style_guide

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# семантические роли IR ← подстроки имён токенов (нижний регистр, без разделителей)
_COLOR_ROLE_HINTS = (
    ("primary", ("primary", "brand", "accentmain", "cta")),
    ("accent", ("accent", "highlight")),
    ("secondary", ("secondary",)),
    ("background", ("background", "bg", "canvas", "page")),
    ("surface", ("surface", "card", "panel", "elevated")),
    ("textMuted", ("muted", "secondarytext", "textsecondary", "subtle", "caption")),
    ("text", ("foreground", "text", "ink", "oncanvas", "body", "fg")),
    ("border", ("border", "line", "stroke", "divider", "outline")),
)
_FONT_ROLE_HINTS = (
    ("display", ("display", "heading", "headline", "title", "serif", "h1")),
    ("body", ("body", "text", "sans", "base", "paragraph", "default")),
)


def _norm_name(*parts: str) -> str:
    return re.sub(r"[^a-z0-9]", "", "".join(str(p) for p in parts).lower())


def _px(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*(px|rem|em)?\s*$", value)
        if m:
            num = float(m.group(1))
            return num * 16 if m.group(2) in ("rem", "em") else num
    return None


# ---------- определение формата ----------

def _is_token_leaf(value: Any) -> bool:
    return isinstance(value, dict) and ("$value" in value or ("value" in value and len(value) <= 6))


def _has_token_leaves(payload: Any, depth: int = 0) -> bool:
    if depth > 6 or not isinstance(payload, dict):
        return False
    for v in payload.values():
        if _is_token_leaf(v):
            return True
        if isinstance(v, dict) and _has_token_leaves(v, depth + 1):
            return True
    return False


def detect_format(payload: Any) -> str | None:
    if not isinstance(payload, dict) or not payload:
        return None
    if payload.get("schemaVersion") and isinstance(payload.get("foundations"), dict):
        return "designdna-document"
    if _has_token_leaves(payload):
        return "design-tokens"
    if coerce_ir_tokens(payload) is not None:
        return "token-map"
    return None


# ---------- W3C / Tokens Studio → плоские значения ----------

def _iter_tokens(payload: dict, path: tuple = (), depth: int = 0):
    """(путь, тип, значение) по всем листьям-токенам."""
    if depth > 8:
        return
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        if _is_token_leaf(value):
            raw = value.get("$value", value.get("value"))
            typ = str(value.get("$type") or value.get("type") or "").lower()
            yield path + (str(key),), typ, raw
        else:
            yield from _iter_tokens(value, path + (str(key),), depth + 1)


def _resolve_alias(raw: Any, index: dict, depth: int = 0) -> Any:
    """{color.primary} / $color.primary → значение токена, если он есть."""
    if depth > 5 or not isinstance(raw, str):
        return raw
    m = re.match(r"^\{([^}]+)\}$", raw.strip()) or re.match(r"^\$([A-Za-z0-9_.\-]+)$", raw.strip())
    if not m:
        return raw
    key = _norm_name(m.group(1))
    target = index.get(key)
    return _resolve_alias(target, index, depth + 1) if target is not None else raw


def _pick_role(name: str, hints) -> str | None:
    for role, needles in hints:
        if any(needle in name for needle in needles):
            return role
    return None


def _from_design_tokens(payload: dict) -> dict:
    """Токены → {tokens v1 (частичные), primitives, radii, spacing, shadows, families}."""
    leaves = list(_iter_tokens(payload))
    index = {_norm_name(".".join(p)): v for p, _t, v in leaves}
    index.update({_norm_name(p[-1]): v for p, _t, v in leaves if _norm_name(p[-1]) not in index})
    colors: dict[str, str] = {}
    primitives: dict[str, str] = {}
    families: dict[str, str] = {}
    radii: list[float] = []
    spacing: dict[str, float] = {}
    shadows: list[str] = []
    for path, typ, raw in leaves:
        value = _resolve_alias(raw, index)
        full = _norm_name(*path)
        last = _norm_name(path[-1])
        if (typ == "color" or (isinstance(value, str) and _HEX.match(value.strip()))) and isinstance(value, str) and _HEX.match(value.strip()):
            hexv = value.strip().lower()
            primitives[".".join(path)[:60]] = hexv
            # сначала имя самого токена (brand.accent → accent), потом весь путь
            role = _pick_role(last, _COLOR_ROLE_HINTS) or _pick_role(full, _COLOR_ROLE_HINTS)
            if role and role not in colors:
                colors[role] = hexv
            continue
        if typ in ("fontfamily", "fontfamilies") or "font" in full and "famil" in full:
            fam = value[0] if isinstance(value, list) and value else value
            if isinstance(fam, str) and fam.strip():
                role = _pick_role(full, _FONT_ROLE_HINTS) or ("display" if "display" not in families else "body")
                families.setdefault(role, fam.split(",")[0].strip().strip("'\""))
            continue
        if typ in ("dimension", "spacing", "borderradius", "sizing", "number") or _px(value) is not None:
            px = _px(value)
            if px is None:
                continue
            if "radius" in full or "corner" in full or "round" in full:
                radii.append(px)
            elif "space" in full or "spacing" in full or "gap" in full or "padding" in full:
                spacing[last or f"space{len(spacing) + 1}"] = px
            continue
        if typ in ("shadow", "boxshadow") and isinstance(value, (str, dict, list)):
            shadows.append(_shadow_css(value))
    tokens: dict[str, Any] = {}
    if colors:
        tokens["color"] = colors
        bg = colors.get("background")
        if bg:
            tokens["mode"] = "dark" if _luminance(bg) < 0.45 else "light"
    if families:
        tokens["font"] = {role: {"family": fam} for role, fam in families.items()}
    return {"tokens": tokens, "primitives": primitives, "families": families,
            "radii": sorted({round(r, 2) for r in radii}), "spacing": spacing,
            "shadows": [s for s in shadows if s][:6]}


def _luminance(hex_color: str) -> float:
    body = hex_color.lstrip("#")
    if len(body) in (3, 4):
        body = "".join(ch * 2 for ch in body)
    try:
        r, g, b = (int(body[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return 1.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _shadow_css(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:200]
    layers = value if isinstance(value, list) else [value]
    parts = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        x, y, blur, spread = (layer.get("x", 0), layer.get("y", 0), layer.get("blur", 0), layer.get("spread", 0))
        color = layer.get("color", "#00000033")
        parts.append(f"{_px(x) or 0:g}px {_px(y) or 0:g}px {_px(blur) or 0:g}px {_px(spread) or 0:g}px {color}")
    return ", ".join(parts)[:200]


# ---------- foundations из IR-токенов ----------

_RADIUS_PX = {"none": 0, "sm": 4, "md": 8, "lg": 16, "xl": 24, "full": 999}


def _radius_px(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(_RADIUS_PX.get(str(value), 8))


def _foundations_from_ir_tokens(ir_tokens: dict, extra: dict | None = None) -> dict:
    """Та же форма, что builder._foundations_from_tokens, но basis = import."""
    extra = extra or {}
    color = dict(ir_tokens.get("color") or {})
    font = ir_tokens.get("font") or {}
    display = dict(font.get("display") or {})
    body = dict(font.get("body") or {})
    families = [f for f in (display.get("family"), body.get("family")) if isinstance(f, str) and f]
    radius = ir_tokens.get("radius") or {}
    px = {k: _radius_px(v) for k, v in radius.items() if k in ("card", "button", "input")}
    radii = list(extra.get("radii") or []) or sorted({v for v in px.values()})
    weights = sorted({int(w) for w in (display.get("weight"), body.get("weight")) if isinstance(w, (int, float))})
    primitives = {**{k: v for k, v in (extra.get("primitives") or {}).items() if isinstance(v, str)}}
    return {
        "mode": ir_tokens.get("mode") or "light",
        "colors": {"primitives": primitives, "semantic": color},
        "typography": {
            "families": list(dict.fromkeys(families))[:8],
            "scale": dict(extra.get("scale") or {}),
            "weights": weights,
            "display": display,
            "body": body,
        },
        "spacing": dict(extra.get("spacing") or {}),
        "radii": radii,
        "radius": px,
        "shadows": list(extra.get("shadows") or []),
        "breakpoints": {},
        "containers": {},
        "measurement": {"basis": "import", "fontSizeCount": 0,
                        "spacingCount": len(extra.get("spacing") or {}), "radiusCount": len(radii)},
    }


# ---------- импорт ----------

def import_design_system(payload: Any, *, name: str = "", file_name: str = "",
                         project_id: str = "default") -> dict:
    fmt = detect_format(payload)
    if fmt is None:
        raise ValueError(
            "Не распознан формат: нужен документ DesignDNA, W3C/Tokens Studio JSON "
            "или карта токенов (shadcn / IR tokens v1)")
    display_name = (name or "").strip() or (re.sub(r"\.[A-Za-z0-9]+$", "", file_name).strip() if file_name else "") or "Imported Design System"

    if fmt == "designdna-document":
        document = copy.deepcopy(payload)
        document["name"] = (name or "").strip() or str(document.get("name") or display_name)
        document["status"] = "draft"
        document["revision"] = 0
        document.pop("contentHash", None)
        document.setdefault("provenance", {})
        document["provenance"]["imported"] = {"format": fmt, "fileName": file_name}
        ensure_style_guide(document)
        return document

    if fmt == "design-tokens":
        parsed = _from_design_tokens(payload)
        ir_tokens = coerce_ir_tokens(parsed["tokens"]) if parsed["tokens"] else None
        if ir_tokens is None:
            raise ValueError("В токенах не нашлось ни одного цвета или шрифта с понятной ролью "
                             "(primary/background/text/border, display/body)")
        extra = {"primitives": parsed["primitives"], "radii": parsed["radii"],
                 "spacing": parsed["spacing"], "shadows": parsed["shadows"]}
    else:
        ir_tokens = coerce_ir_tokens(payload)
        extra = {}
        if isinstance(payload.get("primitives"), dict):
            extra["primitives"] = {k: v for k, v in payload["primitives"].items() if isinstance(v, str)}

    document = dsdoc.new_document(display_name, project_id=project_id, source_refs=[])
    document["foundations"] = _foundations_from_ir_tokens(ir_tokens, extra)
    document["provenance"]["imported"] = {"format": fmt, "fileName": file_name}
    ensure_style_guide(document)
    return document
