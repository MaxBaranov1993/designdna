"""Quality Gate + Constraints: детерминированная инфраструктура правил поверх IR.

Controlled AI layer (см. docs/ARCHITECTURE.md и docs/ROADMAP.md):
после Source Import/Reskin нужен общий движок правил. Без LLM: проверка и
авто-доводка полностью детерминированы.

Правило = данные: id, описание, severity, check(ir) -> список нарушений
(path + message), опционально fix(ir) -> журнал правок. Нарушение — словарь
{rule, path, message, severity}; пути — в формате журнала mergeback
("tree.0.props.heading", "tokens.color.text").

Публичный API:
- check(ir, rules=None)              -> [violations]
- autofix(ir)                        -> (fixed_ir, journal) — solver без LLM
- check_constraints(ir, constraints) -> [violations]
- contrast_ratio(a, b)               -> float (WCAG)
"""
from __future__ import annotations

import copy
import math

from colorutils import hex_to_srgb, srgb_to_hex, srgb_to_oklch, oklch_to_srgb

# лимиты v1 (по схеме design-ir.schema.json и ТЗ)
WCAG_AA = 4.5
GRID_STEP = 8
MAX_BUTTON_LEN = 40
MAX_HEADING_LEN = 120
MAX_SUBHEADING_LEN = 300
MIN_TAP_TARGET = 24  # WCAG 2.2 AA: минимальный размер touch-target, px
MIN_FONT_SIZE = 12   # WCAG: читаемый минимум текста, px
DEFAULT_ARTBOARD_WIDTH = 960  # ширина холста по умолчанию (описание схемы)

SEVERITY_ERROR = "error"


# ---------- обход IR ----------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iter_sections(ir):
    """(index, path, секция) для секций дерева; битые элементы пропускаем."""
    tree = ir.get("tree")
    if not isinstance(tree, list):
        return
    for i, sec in enumerate(tree):
        if isinstance(sec, dict):
            yield i, f"tree.{i}", sec


def _iter_elements(children, path):
    """Рекурсивно (path, element) по children секций/элементов."""
    if not isinstance(children, list):
        return
    for j, el in enumerate(children):
        if not isinstance(el, dict):
            continue
        p = f"{path}.{j}"
        yield p, el
        yield from _iter_elements(el.get("children"), f"{p}.children")


def _iter_all_elements(ir):
    for i, base, sec in _iter_sections(ir):
        yield from _iter_elements(sec.get("children"), f"{base}.children")


def _iter_walk_leaves(value, path):
    """Рекурсивно (ключ, path, значение) по листьям словарей/списков."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_walk_leaves(v, f"{path}.{k}")
    elif isinstance(value, list):
        for j, v in enumerate(value):
            yield from _iter_walk_leaves(v, f"{path}.{j}")
    else:
        yield path.rsplit(".", 1)[-1], path, value


def get_path(obj, path):
    """Разыменовать путь "tree.0.props.heading" -> (найдено, значение)."""
    cur = obj
    for seg in path.split("."):
        if isinstance(cur, list):
            if not seg.isdigit() or int(seg) >= len(cur):
                return False, None
            cur = cur[int(seg)]
        elif isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return False, None
    return True, cur


# ---------- правило 1: ровно один h1 ----------

def _check_single_h1(ir) -> list:
    h1 = [(p, el) for p, el in _iter_all_elements(ir)
          if el.get("type") == "heading" and el.get("level") == 1]
    if len(h1) == 1:
        return []
    if not h1:
        return [{"path": "tree",
                 "message": "нет ни одного h1 среди heading-элементов"}]
    return [{"path": p,
             "message": f"h1 должен быть ровно один, найдено {len(h1)}"}
            for p, _ in h1]


# ---------- правило 2: кнопки/cta ----------

def _iter_buttons(ir):
    """(path, текст|None) всех кнопок: buttonElement в props, cta тарифов,
    submitText и элементы type=button."""
    for i, base, sec in _iter_sections(ir):
        props = sec.get("props")
        props = props if isinstance(props, dict) else {}
        for key in ("cta", "ctaPrimary", "ctaSecondary"):
            if key not in props:
                continue
            v = props[key]
            if isinstance(v, dict):
                yield f"{base}.props.{key}", v.get("text")
            elif isinstance(v, str):
                yield f"{base}.props.{key}", v
            else:
                yield f"{base}.props.{key}", None
        tiers = props.get("tiers")
        if isinstance(tiers, list):
            for j, tier in enumerate(tiers):
                if not isinstance(tier, dict) or "cta" not in tier:
                    continue
                v = tier["cta"]
                if isinstance(v, dict):
                    yield f"{base}.props.tiers.{j}.cta", v.get("text")
                elif isinstance(v, str):
                    yield f"{base}.props.tiers.{j}.cta", v
                else:
                    yield f"{base}.props.tiers.{j}.cta", None
        if "submitText" in props:
            v = props["submitText"]
            yield f"{base}.props.submitText", v if isinstance(v, str) else None
    for path, el in _iter_all_elements(ir):
        if el.get("type") == "button":
            yield path, el.get("text")


def _check_button_text(ir) -> list:
    out = []
    for path, text in _iter_buttons(ir):
        if not isinstance(text, str) or not text.strip():
            out.append({"path": path, "message": "пустой текст кнопки"})
        elif len(text) > MAX_BUTTON_LEN:
            out.append({"path": path,
                        "message": f"текст кнопки длиннее {MAX_BUTTON_LEN} "
                                   f"({len(text)})"})
    return out


# ---------- правило 3: alt у изображений ----------

def _iter_images(ir):
    for i, base, sec in _iter_sections(ir):
        props = sec.get("props")
        if isinstance(props, dict) and isinstance(props.get("media"), dict):
            yield f"{base}.props.media", props["media"]
    for path, el in _iter_all_elements(ir):
        if el.get("type") == "image":
            yield path, el


def _check_image_alt(ir) -> list:
    out = []
    for path, node in _iter_images(ir):
        alt = node.get("alt")
        if not isinstance(alt, str) or not alt.strip():
            out.append({"path": path, "message": "изображение без alt"})
    return out


# ---------- правило 4: лимиты длин заголовков ----------

def _check_heading_limits(ir) -> list:
    out = []
    for i, base, sec in _iter_sections(ir):
        for key, path, v in _iter_walk_leaves(sec.get("props"), f"{base}.props"):
            if not isinstance(v, str):
                continue
            if key == "heading" and len(v) > MAX_HEADING_LEN:
                out.append({"path": path,
                            "message": f"heading длиннее {MAX_HEADING_LEN} ({len(v)})"})
            elif key == "subheading" and len(v) > MAX_SUBHEADING_LEN:
                out.append({"path": path,
                            "message": f"subheading длиннее {MAX_SUBHEADING_LEN} ({len(v)})"})
    return out


# ---------- правило 5: контраст WCAG AA ----------

def _wcag_luminance(hex_color: str):
    try:
        r, g, b = hex_to_srgb(hex_color)
    except (ValueError, AttributeError, TypeError):
        return None

    def chan(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(color_a: str, color_b: str) -> float:
    """Контраст двух hex-цветов по WCAG (1..21)."""
    la, lb = _wcag_luminance(color_a), _wcag_luminance(color_b)
    if la is None or lb is None:
        raise ValueError(f"некорректный hex-цвет: {color_a!r} / {color_b!r}")
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# пары «текст → фон» из tokens: фон — background (текст и muted)
_CONTRAST_PAIRS = (("text", "background"), ("textMuted", "background"))


def _check_contrast(ir) -> list:
    tokens = ir.get("tokens")
    colors = tokens.get("color") if isinstance(tokens, dict) else None
    if not isinstance(colors, dict):
        return []
    out = []
    for fg, bg in _CONTRAST_PAIRS:
        c_fg, c_bg = colors.get(fg), colors.get(bg)
        if not isinstance(c_fg, str) or not isinstance(c_bg, str):
            continue
        if _wcag_luminance(c_fg) is None or _wcag_luminance(c_bg) is None:
            continue  # не-hex цвета отловит схема
        ratio = contrast_ratio(c_fg, c_bg)
        if ratio < WCAG_AA:
            out.append({"path": f"tokens.color.{fg}",
                        "message": f"контраст {c_fg} к {c_bg} = {ratio:.2f} "
                                   f"< {WCAG_AA} (WCAG AA)"})
    return out


def _fix_contrast(ir) -> list:
    """Доводит tokens.color.text/textMuted до WCAG AA к background, двигая
    lightness в OKLCH (hue/chroma сохраняются). Fallback — почти чёрный/белый."""
    tokens = ir.get("tokens")
    colors = tokens.get("color") if isinstance(tokens, dict) else None
    if not isinstance(colors, dict):
        return []
    bg = colors.get("background")
    if not isinstance(bg, str) or _wcag_luminance(bg) is None:
        return []
    bg_light = _wcag_luminance(bg) > 0.18  # светлый фон — текст затемняем
    journal = []
    for fg_key, _bg_key in _CONTRAST_PAIRS:
        fg = colors.get(fg_key)
        if not isinstance(fg, str) or _wcag_luminance(fg) is None:
            continue
        if contrast_ratio(fg, bg) >= WCAG_AA:
            continue
        try:
            L, C, H = srgb_to_oklch(hex_to_srgb(fg))
        except (ValueError, TypeError):
            continue
        best = None
        for i in range(1, 26):
            nl = max(0.0, L - 0.04 * i) if bg_light else min(1.0, L + 0.04 * i)
            rgb = tuple(min(1.0, max(0.0, c)) for c in oklch_to_srgb((nl, C, H)))
            cand = srgb_to_hex(rgb)
            if contrast_ratio(cand, bg) >= WCAG_AA:
                best = cand
                break
        if best is None:
            best = "#171717" if bg_light else "#fafafa"
            if contrast_ratio(best, bg) < WCAG_AA:
                best = "#000000" if bg_light else "#ffffff"
        colors[fg_key] = best
        journal.append(f"rule contrast починило tokens.color.{fg_key}: {fg} -> {best}")
    return journal


# ---------- правило 6: сетка 8px ----------

def _iter_frame_metrics(ir):
    """(контейнер, ключ, path) числовых метрик frame секций:
    padding (число/список), gap, width, height — то, что снапится к сетке."""
    for i, base, sec in _iter_sections(ir):
        frame = sec.get("frame")
        if not isinstance(frame, dict):
            continue
        fp = f"{base}.frame"
        pad = frame.get("padding")
        if _is_num(pad):
            yield frame, "padding", f"{fp}.padding"
        elif isinstance(pad, list):
            for j, v in enumerate(pad):
                if _is_num(v):
                    yield pad, j, f"{fp}.padding.{j}"
        for key in ("gap", "width", "height"):
            if _is_num(frame.get(key)):
                yield frame, key, f"{fp}.{key}"


def _check_grid(ir) -> list:
    out = []
    for container, key, path in _iter_frame_metrics(ir):
        v = container[key]
        if v % GRID_STEP != 0:
            out.append({"path": path,
                        "message": f"{format(v, 'g')} не кратно {GRID_STEP} (сетка)"})
    return out


def _snap8(v):
    """Округление к ближайшему кратному 8 (половинки — вверх)."""
    return int(math.floor(v / GRID_STEP + 0.5)) * GRID_STEP


def _fix_grid(ir) -> list:
    journal = []
    for container, key, path in _iter_frame_metrics(ir):
        v = container[key]
        nv = _snap8(v)
        if nv != v:
            container[key] = nv
            journal.append(f"rule grid-8 починило {path}: {format(v, 'g')} → {nv}")
    return journal


# ---------- правило 7: overflow за артборд ----------

def _artboard_size(ir):
    """(ширина, высота|None) артборда; высота hug/нет — None."""
    frame = ir.get("frame")
    frame = frame if isinstance(frame, dict) else {}
    w = frame.get("width")
    h = frame.get("height")
    width = w if _is_num(w) else DEFAULT_ARTBOARD_WIDTH
    height = h if _is_num(h) else None
    return width, height


def _geom_violations(frame, path, W, H) -> list:
    out = []
    w, x = frame.get("width"), frame.get("x")
    h, y = frame.get("height"), frame.get("y")
    if _is_num(w) and w > W:
        out.append({"path": f"{path}.width",
                    "message": f"ширина {format(w, 'g')} больше артборда {format(W, 'g')}"})
    if _is_num(x):
        if x < 0:
            out.append({"path": f"{path}.x",
                        "message": f"x={format(x, 'g')} — выход за левый край артборда"})
        elif _is_num(w) and x + w > W:
            out.append({"path": f"{path}.x",
                        "message": f"x+width={format(x + w, 'g')} выходит за правый край "
                                   f"артборда {format(W, 'g')}"})
    if H is not None:
        if _is_num(h) and h > H:
            out.append({"path": f"{path}.height",
                        "message": f"высота {format(h, 'g')} больше артборда {format(H, 'g')}"})
        if _is_num(y):
            if y < 0:
                out.append({"path": f"{path}.y",
                            "message": f"y={format(y, 'g')} — выход за верхний край артборда"})
            elif _is_num(h) and y + h > H:
                out.append({"path": f"{path}.y",
                            "message": f"y+height={format(y + h, 'g')} выходит за нижний край "
                                       f"артборда {format(H, 'g')}"})
    return out


def _check_overflow(ir) -> list:
    W, H = _artboard_size(ir)
    out = []
    for i, base, sec in _iter_sections(ir):
        frame = sec.get("frame")
        if isinstance(frame, dict):
            out.extend(_geom_violations(frame, f"{base}.frame", W, H))
    return out


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


def _fix_overflow(ir) -> list:
    """Вписать frame секций в артборд: размер урезается, позиция зажимается."""
    W, H = _artboard_size(ir)
    journal = []

    def fix_axis(container, size_key, pos_key, limit, path):
        size, pos = container.get(size_key), container.get(pos_key)
        if _is_num(size) and size > limit:
            container[size_key] = limit
            journal.append(f"rule frame-overflow починило {path}.{size_key}: "
                           f"{format(size, 'g')} → {format(limit, 'g')}")
            size = limit
        if _is_num(pos):
            hi = limit - size if _is_num(size) else limit
            np = _clamp(pos, 0, hi)
            if np != pos:
                container[pos_key] = np
                journal.append(f"rule frame-overflow починило {path}.{pos_key}: "
                               f"{format(pos, 'g')} → {format(np, 'g')}")

    for i, base, sec in _iter_sections(ir):
        frame = sec.get("frame")
        if not isinstance(frame, dict):
            continue
        fp = f"{base}.frame"
        fix_axis(frame, "width", "x", W, fp)
        if H is not None:
            fix_axis(frame, "height", "y", H, fp)
    return journal


# ---------- правило 8: не более двух шрифтов ----------

def _check_fonts(ir) -> list:
    tokens = ir.get("tokens")
    font = tokens.get("font") if isinstance(tokens, dict) else None
    if not isinstance(font, dict):
        return []
    families = {face.get("family") for face in font.values()
                if isinstance(face, dict) and isinstance(face.get("family"), str)}
    if len(families) > 2:
        return [{"path": "tokens.font",
                 "message": f"больше двух шрифтов: {', '.join(sorted(families))}"}]
    return []


# ---------- правило 9: touch-target (WCAG 2.2, 2.5.8) ----------

def _iter_framed_controls(ir):
    """(path, frame) интерактивных элементов (button/input) с числовым frame."""
    for path, el in _iter_all_elements(ir):
        if el.get("type") not in ("button", "input"):
            continue
        frame = el.get("frame")
        if isinstance(frame, dict):
            yield path, frame


def _check_tap_target(ir) -> list:
    out = []
    for path, frame in _iter_framed_controls(ir):
        h = frame.get("height")
        if _is_num(h) and 0 < h < MIN_TAP_TARGET:
            out.append({"path": f"{path}.frame.height",
                        "message": f"touch-target {h}px < {MIN_TAP_TARGET}px (WCAG 2.2, 2.5.8)"})
    return out


def _fix_tap_target(ir) -> list:
    journal = []
    for path, frame in _iter_framed_controls(ir):
        h = frame.get("height")
        if _is_num(h) and 0 < h < MIN_TAP_TARGET:
            frame["height"] = MIN_TAP_TARGET
            journal.append(f"rule tap-target починило {path}.frame.height: {h} -> {MIN_TAP_TARGET}")
    return journal


# ---------- правило 10: минимальный кегль (WCAG readability) ----------

def _iter_text_styles(ir):
    """(path, style) элементов с числовым style.fontSize."""
    for path, el in _iter_all_elements(ir):
        style = el.get("style")
        if isinstance(style, dict) and _is_num(style.get("fontSize")):
            yield path, style


def _check_min_font_size(ir) -> list:
    out = []
    for path, style in _iter_text_styles(ir):
        size = style["fontSize"]
        if 0 < size < MIN_FONT_SIZE:
            out.append({"path": f"{path}.style.fontSize",
                        "message": f"fontSize {size}px < {MIN_FONT_SIZE}px"})
    return out


def _fix_min_font_size(ir) -> list:
    journal = []
    for path, style in _iter_text_styles(ir):
        size = style["fontSize"]
        if 0 < size < MIN_FONT_SIZE:
            style["fontSize"] = MIN_FONT_SIZE
            journal.append(f"rule min-font-size починило {path}.style.fontSize: {size} -> {MIN_FONT_SIZE}")
    return journal

# ---------- реестр правил ----------

RULES = [
    {"id": "single-h1", "severity": SEVERITY_ERROR,
     "description": "ровно один h1 среди heading-элементов",
     "check": _check_single_h1},
    {"id": "button-text", "severity": SEVERITY_ERROR,
     "description": f"у всех кнопок/cta непустой текст длиной не более {MAX_BUTTON_LEN}",
     "check": _check_button_text},
    {"id": "image-alt", "severity": SEVERITY_ERROR,
     "description": "у всех изображений есть непустой alt",
     "check": _check_image_alt},
    {"id": "heading-limits", "severity": SEVERITY_ERROR,
     "description": f"heading не длиннее {MAX_HEADING_LEN}, "
                    f"subheading не длиннее {MAX_SUBHEADING_LEN} (лимиты схемы)",
     "check": _check_heading_limits},
    {"id": "contrast", "severity": SEVERITY_ERROR,
     "description": f"контраст текста к фону не ниже {WCAG_AA} (WCAG AA, по tokens)",
     "check": _check_contrast, "fix": _fix_contrast},
    {"id": "grid-8", "severity": SEVERITY_ERROR,
     "description": f"отступы/размеры секций кратны {GRID_STEP} (сетка snap)",
     "check": _check_grid, "fix": _fix_grid},
    {"id": "frame-overflow", "severity": SEVERITY_ERROR,
     "description": "frame секций не выходит за границы артборда",
     "check": _check_overflow, "fix": _fix_overflow},
    {"id": "fonts-limit", "severity": SEVERITY_ERROR,
     "description": "не более двух шрифтов (display+body токены)",
     "check": _check_fonts},
    {"id": "tap-target", "severity": SEVERITY_ERROR,
     "description": f"интерактивные элементы не ниже {MIN_TAP_TARGET}px (WCAG 2.2, 2.5.8)",
     "check": _check_tap_target, "fix": _fix_tap_target},
    {"id": "min-font-size", "severity": SEVERITY_ERROR,
     "description": f"текст не мельче {MIN_FONT_SIZE}px",
     "check": _check_min_font_size, "fix": _fix_min_font_size},
]
RULES_BY_ID = {r["id"]: r for r in RULES}


def check(ir, rules=None) -> list:
    """Прогнать правила; вернуть список нарушений {rule, path, message, severity}."""
    if not isinstance(ir, dict):
        raise ValueError("IR должен быть объектом")
    out = []
    for rule in (RULES if rules is None else rules):
        for v in rule["check"](ir):
            out.append({"rule": rule["id"], "severity": rule["severity"], **v})
    return out


def autofix(ir) -> tuple:
    """Solver без LLM: вернуть (исправленный IR, журнал правок). Вход не мутируется."""
    if not isinstance(ir, dict):
        raise ValueError("IR должен быть объектом")
    fixed = copy.deepcopy(ir)
    journal = []
    for rule in RULES:
        fix = rule.get("fix")
        if fix:
            journal.extend(fix(fixed))
    return fixed, journal


# ---------- Constraints: декларативные инварианты ----------

# допустимые проверки в ограничении: лок значения и диапазоны
_CONSTRAINT_CHECKS = {"lock", "min", "max", "enum", "max_len"}


def _cv(path, message) -> dict:
    return {"rule": "constraint", "path": path, "message": message,
            "severity": SEVERITY_ERROR}


def check_constraints(ir, constraints) -> list:
    """Проверить декларативные ограничения.

    Ограничение: {"path": "tree.0.props.heading", "lock": ..., "min": ...,
    "max": ..., "enum": [...], "max_len": N} — проверки комбинируются.
    lock требует присутствия поля; диапазоны отсутствующее поле пропускают.
    """
    if not isinstance(ir, dict):
        raise ValueError("IR должен быть объектом")
    if not isinstance(constraints, list):
        raise ValueError("constraints должен быть списком")
    out = []
    for i, c in enumerate(constraints):
        if not isinstance(c, dict):
            raise ValueError(f"constraint #{i}: не объект")
        path = c.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"constraint #{i}: нет path")
        keys = set(c) - {"path"}
        unknown = keys - _CONSTRAINT_CHECKS
        if unknown:
            raise ValueError(f"constraint #{i}: неизвестные ключи {sorted(unknown)}")
        if not keys:
            raise ValueError(f"constraint #{i}: пустое ограничение (нет проверок)")
        if "enum" in c and not isinstance(c["enum"], list):
            raise ValueError(f"constraint #{i}: enum должен быть списком")
        for k in ("min", "max"):
            if k in c and not _is_num(c[k]):
                raise ValueError(f"constraint #{i}: {k} должен быть числом")
        if "max_len" in c and not isinstance(c["max_len"], int):
            raise ValueError(f"constraint #{i}: max_len должен быть целым")

        found, value = get_path(ir, path)
        if "lock" in c:
            if not found:
                out.append(_cv(path, "поле отсутствует, а залочено"))
            elif value != c["lock"]:
                out.append(_cv(path, f"залочено значение {c['lock']!r}, "
                                     f"фактически {value!r}"))
        if not found:
            continue
        if "enum" in c and value not in c["enum"]:
            out.append(_cv(path, f"значение {value!r} не входит в {c['enum']!r}"))
        for bound in ("min", "max"):
            if bound not in c:
                continue
            if not _is_num(value):
                out.append(_cv(path, f"ожидалось число для {bound}, "
                                     f"фактически {value!r}"))
            elif bound == "min" and value < c["min"]:
                out.append(_cv(path, f"значение {format(value, 'g')} меньше "
                                     f"минимума {format(c['min'], 'g')}"))
            elif bound == "max" and value > c["max"]:
                out.append(_cv(path, f"значение {format(value, 'g')} больше "
                                     f"максимума {format(c['max'], 'g')}"))
        if "max_len" in c:
            if not isinstance(value, str):
                out.append(_cv(path, f"ожидалась строка для max_len, "
                                     f"фактически {value!r}"))
            elif len(value) > c["max_len"]:
                out.append(_cv(path, f"длина {len(value)} больше max_len {c['max_len']}"))
    return out
