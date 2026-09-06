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
import re

from colorutils import hex_to_srgb, srgb_to_hex, srgb_to_oklab, srgb_to_oklch, oklch_to_srgb

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


def _fix_single_h1(ir) -> list:
    """Несколько h1: первый остаётся, остальные понижаются до h2.

    Отсутствие h1 не чиним автоматически — повышение произвольного заголовка
    может исказить смысл; это остаётся находкой для судьи."""
    journal = []
    seen = False
    for path, el in _iter_all_elements(ir):
        if el.get("type") != "heading" or el.get("level") != 1:
            continue
        if not seen:
            seen = True
            continue
        el["level"] = 2
        journal.append(f"rule single-h1 понизило {path}.level: 1 -> 2")
    return journal


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

# ---------- правило: наложения и выход за границы во free-раскладке ----------
#
# Композиционные секции и починки судьи любят абсолютные координаты; типичные
# дефекты живой генерации — карточка поверх соседа и обрезанный контент. Это
# считается детерминированно: прямоугольники детей free-родителя.

FREE_OVERLAP_RATIO = 0.25


def _rect(frame):
    if not isinstance(frame, dict):
        return None
    x, y, w, h = frame.get("x"), frame.get("y"), frame.get("width"), frame.get("height")
    if all(_is_num(v) for v in (x, y, w, h)) and w > 0 and h > 0:
        return (float(x), float(y), float(w), float(h))
    return None


def _check_free_overlap(ir) -> list:
    out = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        children = node.get("children") if isinstance(node.get("children"), list) else []
        if frame.get("layout") == "free" and children:
            pw = frame.get("width") if _is_num(frame.get("width")) else None
            ph = frame.get("height") if _is_num(frame.get("height")) else None
            rects = []
            for i, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                r = _rect(child.get("frame"))
                if r is None:
                    continue
                cpath = f"{path}.children[{i}]"
                x, y, w, h = r
                if pw is not None and x + w > pw + 0.5:
                    out.append({"path": f"{cpath}.frame", "message": f"x+width={format(x + w, 'g')} выходит за ширину родителя {format(pw, 'g')}"})
                if ph is not None and y + h > ph + 0.5:
                    out.append({"path": f"{cpath}.frame", "message": f"y+height={format(y + h, 'g')} выходит за высоту родителя {format(ph, 'g')}"})
                rects.append((cpath, r))
            for a in range(len(rects)):
                for b in range(a + 1, len(rects)):
                    (pa, (ax, ay, aw, ah)), (pb, (bx, by, bw, bh)) = rects[a], rects[b]
                    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
                    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
                    inter = ix * iy
                    smaller = min(aw * ah, bw * bh)
                    if smaller > 0 and inter / smaller > FREE_OVERLAP_RATIO:
                        out.append({"path": f"{pb}.frame",
                                    "message": f"перекрывает {pa} на {round(100 * inter / smaller)}% площади"})
        for i, child in enumerate(children):
            walk(child, f"{path}.children[{i}]")

    for i, base, sec in _iter_sections(ir):
        walk(sec, base)
    return out



# ---------- DS-lint: дисциплина токенов (цвет, шрифт, роли типографики) ----------
#
# Ровно тот дрейф, что виден у AI-редакторов при росте числа экранов:
# «почти такой же» цвет вне палитры, третий шрифт, line-height 1.30 у одного
# абзаца и 1.35 у соседнего. Правила читают токены самого документа
# (tokens.color / v2.color / primitives, tokens.font / v2.type.families,
# v2.type.roles), поэтому работают и без документа ДС: генератор лочит токены
# ДС в IR, а редактор правит их в инспекторе.
#
# Пропускаются точные копии: секции source-block (измеренный источник),
# поддеревья с sourceMeta.componentRef (пиннутые мастера ДС — их менять нельзя,
# иначе strict-валидация отбросит «mutated-exact-master») и editable:false.

SEVERITY_WARNING = "warning"
TYPE_ROLES = ("display", "h1", "h2", "h3", "lead", "body", "small", "eyebrow")
HEADING_LEVEL_ROLE = {1: "h1", 2: "h2", 3: "h3", 4: "lead"}
# ΔE в oklab, до которого цвет считается «дрейфом токена» и снапится автоматически;
# дальше — только находка (дизайнер решает сам). strict_tokens=True снапит всё.
AUTO_SNAP_DISTANCE = 0.12
_COLOR_STYLE_KEYS = ("color", "background", "borderColor")
_ROLE_STYLE_KEYS = ("fontSize", "lineHeight", "fontWeight", "letterSpacing")


def _norm_hex(value):
    """'#abc' / '#aabbcc' / '#aabbccdd' -> ('#aabbcc', 'dd' | ''); иначе None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v.startswith("#"):
        return None
    body = v[1:]
    if not re.fullmatch(r"[0-9a-fA-F]{3,8}", body) or len(body) in (5, 7):
        return None
    if len(body) in (3, 4):
        body = "".join(ch * 2 for ch in body)
    return "#" + body[:6].lower(), body[6:].lower()


def _document_palette(ir) -> dict:
    """{hex: имя токена} из tokens.color, v2.color, primitives, semantic."""
    tokens = ir.get("tokens")
    if not isinstance(tokens, dict):
        return {}
    palette = {}

    def take(container, prefix):
        if not isinstance(container, dict):
            return
        for _key, path, value in _iter_walk_leaves(container, prefix):
            norm = _norm_hex(value)
            if norm and norm[0] not in palette:
                palette[norm[0]] = path

    take(tokens.get("color"), "tokens.color")
    v2 = tokens.get("v2")
    if isinstance(v2, dict):
        take(v2.get("color"), "tokens.v2.color")
    take(tokens.get("primitives"), "tokens.primitives")
    take(tokens.get("semantic"), "tokens.semantic")
    return palette


def _family_name(value) -> str:
    """Первое семейство стека без кавычек, в нижнем регистре."""
    if not isinstance(value, str):
        return ""
    first = value.split(",")[0].strip().strip("'\"").strip()
    return first.lower()


def _document_families(ir) -> set:
    tokens = ir.get("tokens")
    out = set()
    if isinstance(tokens, dict):
        font = tokens.get("font")
        if isinstance(font, dict):
            for face in font.values():
                if isinstance(face, dict):
                    name = _family_name(face.get("family"))
                    if name:
                        out.add(name)
        v2 = tokens.get("v2")
        typ = v2.get("type") if isinstance(v2, dict) else None
        fams = typ.get("families") if isinstance(typ, dict) else None
        if isinstance(fams, dict):
            for face in fams.values():
                if isinstance(face, dict):
                    name = _family_name(face.get("family"))
                    if name:
                        out.add(name)
    meta = ir.get("meta")
    faces = meta.get("fontFaces") if isinstance(meta, dict) else None
    if isinstance(faces, list):
        for face in faces:
            if isinstance(face, dict):
                name = _family_name(face.get("family"))
                if name:
                    out.add(name)
    return out


def _type_roles(ir) -> dict:
    tokens = ir.get("tokens")
    v2 = tokens.get("v2") if isinstance(tokens, dict) else None
    typ = v2.get("type") if isinstance(v2, dict) else None
    roles = typ.get("roles") if isinstance(typ, dict) else None
    return roles if isinstance(roles, dict) else {}


def _is_exact_copy(node) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("editable") is False:
        return True
    meta = node.get("sourceMeta")
    return isinstance(meta, dict) and isinstance(meta.get("componentRef"), dict)


def _iter_lintable_elements(ir):
    """(path, element) вне точных копий: source-block, componentRef, editable:false."""

    def walk(children, path):
        if not isinstance(children, list):
            return
        for j, el in enumerate(children):
            if not isinstance(el, dict) or _is_exact_copy(el):
                continue
            p = f"{path}.{j}"
            yield p, el
            yield from walk(el.get("children"), f"{p}.children")

    for i, base, sec in _iter_sections(ir):
        if sec.get("type") == "source-block" or _is_exact_copy(sec):
            continue
        yield from walk(sec.get("children"), f"{base}.children")


def _oklab(hex6):
    try:
        return srgb_to_oklab(hex_to_srgb(hex6))
    except (ValueError, TypeError):
        return None


def _nearest_token(hex6, palette):
    """(hex токена, путь, расстояние ΔE oklab) или None."""
    lab = _oklab(hex6)
    if lab is None:
        return None
    best = None
    for token_hex, path in palette.items():
        tl = _oklab(token_hex)
        if tl is None:
            continue
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(lab, tl)))
        if best is None or d < best[2]:
            best = (token_hex, path, d)
    return best


def _iter_color_slots(ir):
    """(path, контейнер, ключ, hex6, alpha) цветов элементов вне точных копий."""
    for path, el in _iter_lintable_elements(ir):
        style = el.get("style")
        if isinstance(style, dict):
            for key in _COLOR_STYLE_KEYS:
                norm = _norm_hex(style.get(key))
                if norm:
                    yield f"{path}.style.{key}", style, key, norm[0], norm[1]
        if el.get("type") == "rect":
            norm = _norm_hex(el.get("fill"))
            if norm:
                yield f"{path}.fill", el, "fill", norm[0], norm[1]


def _check_token_color(ir) -> list:
    palette = _document_palette(ir)
    if not palette:
        return []
    out = []
    for path, _c, _k, hex6, _alpha in _iter_color_slots(ir):
        if hex6 in palette:
            continue
        near = _nearest_token(hex6, palette)
        hint = f"; ближайший токен {near[1]} ({near[0]}, ΔE {near[2]:.2f})" if near else ""
        out.append({"path": path, "message": f"цвет {hex6} не из токенов документа{hint}"})
    return out


def _fix_token_color(ir, strict_tokens=False) -> list:
    palette = _document_palette(ir)
    if not palette:
        return []
    journal = []
    for path, container, key, hex6, alpha in _iter_color_slots(ir):
        if hex6 in palette:
            continue
        near = _nearest_token(hex6, palette)
        if near is None or (not strict_tokens and near[2] > AUTO_SNAP_DISTANCE):
            continue
        new = near[0] + alpha
        old = container[key]
        container[key] = new
        journal.append(f"rule token-color починило {path}: {old} -> {new} ({near[1]})")
    return journal


def _check_token_font(ir) -> list:
    families = _document_families(ir)
    if not families:
        return []
    out = []
    for path, el in _iter_lintable_elements(ir):
        style = el.get("style")
        if not isinstance(style, dict):
            continue
        name = _family_name(style.get("fontFamily"))
        if name and name not in families:
            out.append({"path": f"{path}.style.fontFamily",
                        "message": f"шрифт «{name}» не из дизайн-системы "
                                   f"(разрешены: {', '.join(sorted(families))})"})
    return out


def _fix_token_font(ir, strict_tokens=False) -> list:
    """Снимает чужое семейство: тег/роль дальше наследуют display/body из токенов."""
    families = _document_families(ir)
    if not families:
        return []
    journal = []
    for path, el in _iter_lintable_elements(ir):
        style = el.get("style")
        if not isinstance(style, dict):
            continue
        name = _family_name(style.get("fontFamily"))
        if name and name not in families:
            old = style.pop("fontFamily")
            journal.append(f"rule token-font починило {path}.style.fontFamily: «{old}» снят, наследуется токен")
    return journal


def element_type_role(el) -> tuple:
    """(роль, явная ли) для текстового элемента: typeRole либо уровень заголовка."""
    if not isinstance(el, dict):
        return None, False
    role = el.get("typeRole")
    if role in TYPE_ROLES:
        return role, True
    if el.get("type") == "heading":
        return HEADING_LEVEL_ROLE.get(el.get("level") or 2), False
    return None, False


def _role_drift(style, role_spec) -> list:
    """Список (ключ стиля, факт, ожидание) отклонений инлайна от роли."""
    out = []
    size = role_spec.get("size")
    if _is_num(style.get("fontSize")) and _is_num(size) and abs(style["fontSize"] - size) > 0.5:
        out.append(("fontSize", style["fontSize"], size))
    lh = role_spec.get("lineHeight")
    if _is_num(style.get("lineHeight")) and _is_num(lh) and abs(style["lineHeight"] - lh) > 0.011:
        out.append(("lineHeight", style["lineHeight"], lh))
    weight = role_spec.get("weight")
    if _is_num(style.get("fontWeight")) and _is_num(weight) and int(style["fontWeight"]) != int(weight):
        out.append(("fontWeight", style["fontWeight"], weight))
    tracking = role_spec.get("tracking")
    if _is_num(style.get("letterSpacing")) and _is_num(tracking) and _is_num(size):
        expected_px = round(tracking * size, 2)
        if abs(style["letterSpacing"] - expected_px) > 0.5:
            out.append(("letterSpacing", style["letterSpacing"], expected_px))
    return out


def _check_type_role_drift(ir) -> list:
    roles = _type_roles(ir)
    if not roles:
        return []
    out = []
    for path, el in _iter_lintable_elements(ir):
        if el.get("type") not in ("heading", "text"):
            continue
        role, explicit = element_type_role(el)
        spec = roles.get(role) if role else None
        style = el.get("style")
        if not isinstance(spec, dict) or not isinstance(style, dict):
            continue
        for key, actual, expected in _role_drift(style, spec):
            why = "роль" if explicit else f"уровень h{el.get('level') or 2} → роль"
            out.append({"path": f"{path}.style.{key}",
                        "message": f"{key} {actual} расходится с {why} {role} ({expected})"})
    return out


def _fix_type_role_drift(ir, strict_tokens=False) -> list:
    """Явная typeRole — источник правды: инлайновые кегль/интерлиньяж/вес/разрядка
    снимаются, рендер берёт роль. Заголовки без typeRole только репортятся."""
    roles = _type_roles(ir)
    if not roles:
        return []
    journal = []
    for path, el in _iter_lintable_elements(ir):
        if el.get("type") not in ("heading", "text"):
            continue
        role, explicit = element_type_role(el)
        if not explicit:
            continue
        spec = roles.get(role)
        style = el.get("style")
        if not isinstance(spec, dict) or not isinstance(style, dict):
            continue
        for key, actual, expected in _role_drift(style, spec):
            style.pop(key, None)
            journal.append(f"rule type-role-drift починило {path}.style.{key}: {actual} снят, роль {role} даёт {expected}")
    return journal


RULES = [
    {"id": "single-h1", "severity": SEVERITY_ERROR,
     "description": "ровно один h1 среди heading-элементов",
     "check": _check_single_h1, "fix": _fix_single_h1},
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
    {"id": "free-overlap", "severity": SEVERITY_ERROR,
     "description": "во free-раскладке дети не перекрываются и не выходят за границы родителя",
     "check": _check_free_overlap},
    # DS-lint: дисциплина токенов (предупреждения — они не роняют gate, но чинятся)
    {"id": "token-color", "severity": SEVERITY_WARNING,
     "description": "цвета элементов только из токенов документа (color / v2.color / primitives)",
     "check": _check_token_color, "fix": _fix_token_color, "strict_aware": True},
    {"id": "token-font", "severity": SEVERITY_WARNING,
     "description": "семейства шрифтов только из токенов документа (display / body / fontFaces)",
     "check": _check_token_font, "fix": _fix_token_font, "strict_aware": True},
    {"id": "type-role-drift", "severity": SEVERITY_WARNING,
     "description": "кегль/интерлиньяж/вес/разрядка текста совпадают с ролью типографики (typeRole или уровень заголовка)",
     "check": _check_type_role_drift, "fix": _fix_type_role_drift, "strict_aware": True},
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


def autofix(ir, strict_tokens: bool = False, *, rules=None) -> tuple:
    """Solver без LLM: вернуть (исправленный IR, журнал правок). Вход не мутируется.

    strict_tokens=True (ДС в режиме strict): цвета вне палитры снапятся к ближайшему
    токену всегда, а не только при малом ΔE."""
    if not isinstance(ir, dict):
        raise ValueError("IR должен быть объектом")
    fixed = copy.deepcopy(ir)
    journal = []
    for rule in (RULES if rules is None else rules):
        fix = rule.get("fix")
        if not fix:
            continue
        if rule.get("strict_aware"):
            journal.extend(fix(fixed, strict_tokens=strict_tokens))
        else:
            journal.extend(fix(fixed))
    return fixed, journal


def passed(violations) -> bool:
    """Gate пройден, если нет нарушений уровня error (warning — находки DS-lint)."""
    return not any(v.get("severity", SEVERITY_ERROR) == SEVERITY_ERROR for v in violations)


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
