"""Reskin merge-back: детерминированный возврат залоченных полей после LLM.

Решение владельца 11 (docs/NODES-HOUDINI.md §7.2): модель НЕ обязана сохранить
структуру — после её ответа программа принудительно возвращает залоченные поля
из входного IR (топология дерева, frame, props-разметка), а из ответа модели
берёт только поля из разрешённой маски. Попытки тронуть залоченное молча
перезаписываются и пишутся в журнал.

Входной IR предполагается валидным по схеме; принятые от модели значения
проходят проверку типов/enum'ов, поэтому результат merge_back валиден по схеме
всегда, когда валиден вход.
"""
from __future__ import annotations

import copy
import logging
import re

log = logging.getLogger("mergeback")

_MISSING = object()  # «модель не вернула значение» (отличать от None)

_HEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
_FILL = re.compile(r"^#[0-9a-fA-F]{3,8}$")  # element.fill по схеме шире tokens.color
_WEIGHTS = {300, 400, 500, 600, 700, 800, 900}
_MODES = {"light", "dark"}
_SCALES = {"compact", "default", "spacious"}
_RADIUS = {"none", "sm", "md", "lg", "xl", "full"}
_SHADOWS = {"none", "sm", "md", "lg"}
_ASPECTS = {"1:1", "4:3", "16:9", "3:4", "9:16", "auto"}

# категории маски Reskin (чекбоксы, §7.2)
MASK_KEYS = ("colors", "fonts", "radii", "shadows", "texts", "images")
_ALIASES = {
    "color": "colors",
    "font": "fonts", "typography": "fonts",
    "radius": "radii",
    "shadow": "shadows",
    "text": "texts", "copy": "texts",
    "image": "images", "media": "images",
}

# ключи-разметка: залочены всегда (ссылки/иконки/варианты/флаги/типы — не контент)
_LOCKED_KEYS = {"type", "href", "icon", "variant", "inputType", "level", "size",
                "align", "tone", "required", "sticky", "transparent", "highlighted"}
# ключи изображений (mask.images)
_IMAGE_KEYS = {"src", "imagePrompt", "alt", "aspect"}
# контентные строки с потолком длины по схеме
_MAX_LEN = {"heading": 120, "subheading": 300}
# родители buttonElement: у кнопок text ≤ 40
_BUTTON_PARENTS = {"cta", "ctaPrimary", "ctaSecondary"}


def normalize_mask(mask) -> dict:
    """Маска Reskin → {colors, fonts, radii, shadows, texts, images: bool}.

    Не-словарь и неизвестные ключи → False: лок консервативен по умолчанию.
    """
    out = {k: False for k in MASK_KEYS}
    if isinstance(mask, dict):
        for key, val in mask.items():
            canon = _ALIASES.get(str(key).lower(), str(key).lower())
            if canon in out and bool(val):
                out[canon] = True
    return out


def merge_back(input_ir: dict, model_ir, mask) -> tuple[dict, list]:
    """Слить ответ модели с входным IR по маске лока.

    Возвращает (merged, journal). Залоченные поля (топология дерева, frame,
    props-разметка) — всегда из input_ir; из model_ir берутся только значения
    категорий, разрешённых маской. Битый/пустой ответ модели → копия входа.
    """
    if not isinstance(input_ir, dict):
        raise ValueError("input_ir должен быть объектом")
    merged = copy.deepcopy(input_ir)
    m = normalize_mask(mask)
    journal = []

    if not isinstance(model_ir, dict):
        journal.append("ответ модели не объект — возвращён входной IR без изменений")
        log.warning("mergeback: %s", journal[-1])
        return merged, journal

    # --- корневые залоченные поля: только журнал попыток ---
    for key in model_ir:
        if key not in ("version", "frame", "meta", "tokens", "tree"):
            journal.append(f"лишний корневой ключ {key!r} отброшен")
    if model_ir.get("version", _MISSING) not in (_MISSING, input_ir.get("version")):
        journal.append("version: изменение отброшено (залочен)")
    if "frame" in model_ir and model_ir["frame"] != input_ir.get("frame"):
        journal.append("frame артборда: попытка изменения геометрии — перезаписан из входа")
    if "meta" in model_ir and model_ir["meta"] != input_ir.get("meta"):
        journal.append("meta: изменения отброшены (залочено)")

    # --- tokens: только разрешённые маской категории ---
    merged["tokens"] = _merge_tokens(input_ir.get("tokens", {}),
                                     model_ir.get("tokens", _MISSING), m, journal)

    # --- tree: топология всегда из входа ---
    in_tree = input_ir.get("tree", [])
    mo_tree = model_ir.get("tree", _MISSING)
    if not isinstance(mo_tree, list):
        if in_tree:
            journal.append("tree: модель не вернула дерево — топология взята из входа")
    else:
        if len(mo_tree) != len(in_tree):
            journal.append(f"tree: модель вернула {len(mo_tree)} секций вместо "
                           f"{len(in_tree)} — топология взята из входа")
        kept = [_merge_section(in_tree[i], mo_tree[i], m, journal, f"tree.{i}")
                for i in range(min(len(in_tree), len(mo_tree)))]
        kept += [copy.deepcopy(s) for s in in_tree[len(mo_tree):]]
        merged["tree"] = kept

    for line in journal:
        log.info("mergeback: %s", line)
    return merged, journal


# ---------- tokens ----------

def _merge_named(in_d: dict, mo_d, out_d: dict, allowed: bool, journal: list,
                 path: str, check) -> None:
    """Слияние простого токена-словаря (color/radius): ключи только из входа."""
    if not isinstance(mo_d, dict):
        return
    for key, val in mo_d.items():
        if key not in in_d:
            journal.append(f"{path}.{key}: добавленный моделью ключ отброшен")
            continue
        if val == in_d[key]:
            continue
        if not allowed:
            journal.append(f"{path}.{key}: изменение при залоченной категории — перезаписано")
            continue
        if check(val):
            out_d[key] = val
        else:
            journal.append(f"{path}.{key}: некорректное значение {val!r} — оставлено входное")


def _merge_tokens(in_tok: dict, mo_tok, m: dict, journal: list) -> dict:
    out = copy.deepcopy(in_tok)
    if not isinstance(mo_tok, dict):
        if in_tok:
            journal.append("tokens: модель не вернула токены — взяты из входа")
        return out

    # mode (light/dark) относим к категории цветов
    mo_mode = mo_tok.get("mode", _MISSING)
    if mo_mode is not _MISSING and mo_mode != in_tok.get("mode"):
        if m["colors"] and mo_mode in _MODES:
            out["mode"] = mo_mode
        else:
            journal.append("tokens.mode: изменение перезаписано из входа")

    _merge_named(in_tok.get("color", {}), mo_tok.get("color", _MISSING),
                 out.setdefault("color", {}), m["colors"], journal, "tokens.color",
                 check=lambda v: isinstance(v, str) and bool(_HEX.match(v)))

    font_in = in_tok.get("font", {})
    font_mo = mo_tok.get("font")
    if isinstance(font_mo, dict):
        for face in ("display", "body"):
            mo_face = font_mo.get(face, _MISSING)
            if mo_face is _MISSING or face not in font_in or mo_face == font_in[face]:
                continue
            if not m["fonts"]:
                journal.append(f"tokens.font.{face}: изменение при залоченных шрифтах — перезаписано")
                continue
            fam = mo_face.get("family") if isinstance(mo_face, dict) else None
            weight = mo_face.get("weight") if isinstance(mo_face, dict) else None
            if isinstance(fam, str) and fam.strip() and weight in _WEIGHTS:
                out.setdefault("font", {})[face] = {"family": fam, "weight": weight}
            else:
                journal.append(f"tokens.font.{face}: некорректный fontFace — оставлен входной")
        scale_mo = font_mo.get("scale", _MISSING)
        if scale_mo is not _MISSING and scale_mo != font_in.get("scale"):
            if m["fonts"] and scale_mo in _SCALES:
                out.setdefault("font", {})["scale"] = scale_mo
            else:
                journal.append("tokens.font.scale: изменение перезаписано из входа")

    _merge_named(in_tok.get("radius", {}), mo_tok.get("radius", _MISSING),
                 out.setdefault("radius", {}), m["radii"], journal, "tokens.radius",
                 check=lambda v: v in _RADIUS)

    mo_shadow = mo_tok.get("shadow", _MISSING)
    if mo_shadow is not _MISSING and mo_shadow != in_tok.get("shadow"):
        if m["shadows"] and mo_shadow in _SHADOWS:
            out["shadow"] = mo_shadow
        else:
            journal.append("tokens.shadow: изменение перезаписано из входа")

    # spacing — геометрия, залочен всегда (слайдер силы лока — v2)
    if "spacing" in mo_tok and mo_tok["spacing"] != in_tok.get("spacing"):
        journal.append("tokens.spacing: изменение отброшено (залочен)")
    return out


# ---------- дерево ----------

def _merge_section(in_sec: dict, mo_sec, m: dict, journal: list, path: str) -> dict:
    """Секция merged = входная копия; из модели — только props/children по маске."""
    out = copy.deepcopy(in_sec)
    if not isinstance(mo_sec, dict):
        journal.append(f"{path}: секция от модели не объект — взята из входа")
        return out
    if mo_sec.get("type") != in_sec.get("type"):
        journal.append(f"{path}: тип секции {mo_sec.get('type')!r} != "
                       f"{in_sec.get('type')!r} — секция взята из входа")
        return out
    if mo_sec.get("id", _MISSING) not in (_MISSING, in_sec.get("id")):
        journal.append(f"{path}: id {mo_sec.get('id')!r} отброшен (залочен {in_sec.get('id')!r})")
    if mo_sec.get("variant", _MISSING) not in (_MISSING, in_sec.get("variant")):
        journal.append(f"{path}: variant — props-разметка, изменение отброшено")
    if "frame" in mo_sec and mo_sec["frame"] != in_sec.get("frame"):
        journal.append(f"{path}.frame: попытка изменения геометрии — перезаписан из входа")
    if "_frames" in mo_sec and mo_sec["_frames"] != in_sec.get("_frames"):
        journal.append(f"{path}._frames: изменения отброшены (залочены)")
    if "props" in in_sec:
        out["props"] = _merge_value(in_sec.get("props", {}), mo_sec.get("props", _MISSING),
                                    m, journal, f"{path}.props", "props")
    if "children" in in_sec:
        out["children"] = _merge_value(in_sec.get("children", []), mo_sec.get("children", _MISSING),
                                       m, journal, f"{path}.children", "children")
    return out


def _merge_value(in_val, mo_val, m: dict, journal: list, path: str, key: str,
                 button_ctx: bool = False):
    """Значение узла merged. Залоченные/запрещённые маской поля — из входа."""
    if mo_val is _MISSING or mo_val == in_val:
        return copy.deepcopy(in_val)

    # frame на любом уровне — залочен
    if key == "frame":
        journal.append(f"{path}: попытка изменения frame — перезаписан из входа")
        return copy.deepcopy(in_val)

    # списки: длина — часть топологии
    if isinstance(in_val, list):
        if not isinstance(mo_val, list):
            journal.append(f"{path}: список заменён не-списком — взят из входа")
            return copy.deepcopy(in_val)
        if len(mo_val) != len(in_val):
            journal.append(f"{path}: длина списка {len(mo_val)} != {len(in_val)} — "
                           f"топология взята из входа")
        return [_merge_value(item, mo_val[i] if i < len(mo_val) else _MISSING,
                             m, journal, f"{path}.{i}", "", button_ctx)
                for i, item in enumerate(in_val)]

    # словари: ключи — часть props-разметки; лишние от модели отбрасываем
    if isinstance(in_val, dict):
        if not isinstance(mo_val, dict):
            journal.append(f"{path}: объект заменён не-объектом — взят из входа")
            return copy.deepcopy(in_val)
        out = {}
        for k, v in in_val.items():
            out[k] = _merge_value(v, mo_val.get(k, _MISSING), m, journal,
                                  f"{path}.{k}", k, button_ctx or k in _BUTTON_PARENTS)
        for k in mo_val:
            if k not in in_val:
                journal.append(f"{path}.{k}: добавленный моделью ключ отброшен (залочено)")
        return out

    # лист: разметка и числа/флаги залочены всегда
    if key in _LOCKED_KEYS or isinstance(in_val, (int, float, bool)):
        journal.append(f"{path}: изменение залоченного поля перезаписано из входа")
        return copy.deepcopy(in_val)

    if key in _IMAGE_KEYS:
        if not m["images"]:
            journal.append(f"{path}: изменение при залоченных изображениях — перезаписано")
            return copy.deepcopy(in_val)
        if key == "aspect":
            if mo_val in _ASPECTS:
                return mo_val
        elif isinstance(mo_val, str) and mo_val.strip():
            return mo_val
        journal.append(f"{path}: некорректное значение изображения — оставлено входное")
        return copy.deepcopy(in_val)

    # element.fill — цвет rect (категория colors)
    if key == "fill":
        if m["colors"] and isinstance(mo_val, str) and _FILL.match(mo_val):
            return mo_val
        journal.append(f"{path}: fill перезаписан из входа (лок или некорректный hex)")
        return copy.deepcopy(in_val)

    # строки — контент (категория texts)
    if isinstance(in_val, str):
        if not m["texts"]:
            journal.append(f"{path}: текст изменён при залоченных текстах — перезаписан")
            return copy.deepcopy(in_val)
        if not isinstance(mo_val, str):
            journal.append(f"{path}: текст заменён не-строкой — оставлен входной")
            return copy.deepcopy(in_val)
        limit = 40 if (button_ctx and key == "text") else _MAX_LEN.get(key)
        if limit and len(mo_val) > limit:
            journal.append(f"{path}: текст длиннее лимита {limit} — оставлен входной")
            return copy.deepcopy(in_val)
        return mo_val

    journal.append(f"{path}: изменение залоченного поля перезаписано из входа")
    return copy.deepcopy(in_val)
