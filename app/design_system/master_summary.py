"""Компактные сводки мастеров и декоративные сигнатуры дизайн-системы.

Полный masterIr одной секции весит десятки тысяч символов: в контексте
генератора помещались два-три мастера, а в extend/style-only — ни одного,
и модель рисовала «нейрослоп» по одним hex-значениям. Сводка описывает
мастер в ~600–900 символах: размер и поверхность корня, анатомию
(тексты-образцы с гарнитурой/кеглем/весом, поля, кнопки, точки, пилюли),
декоративные признаки и токены привязки. Сигнатуры собирают те же признаки
по всей системе: моно-лейблы, статус-бейджи, стрелки в CTA, разделители,
нумерация шагов, однострочная форма, тонкие рамки, цветные тени.

Всё детерминировано и считается на лету из мастеров в контексте, поэтому
работает и для уже опубликованных ревизий без перерасчёта identity.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

MAX_DEPTH = 14
MAX_ANATOMY = 14
MAX_SUMMARY_CHARS = 900
MAX_SIGNATURES = 10
_ARROWS = ("→", "↗", "›", "»")
_TEXT_KEYS = ("text", "title", "heading", "label", "placeholder", "value")
_NUMBERED_WORD = re.compile(r"^(day|step|phase|шаг|день|этап)\s*\d", re.I)
_NUMBERED_MARK = re.compile(r"^\d{1,2}\s*[·.)]\s+\S")
_STAT = re.compile(r"^(\$|€|₽|£)?\d[\d,.]*\s*(k|m|%|\+)?$|^[+-]?\d[\d,.]*\s*(%|x|×)$", re.I)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.match(r"^-?\d+(?:\.\d+)?", value.strip())
        if match:
            return float(match.group(0))
    return None


def _fmt(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _family(style: dict) -> str:
    return str(style.get("fontFamily") or "").split(",")[0].strip().strip("'\"")


def _is_mono(family: str) -> bool:
    lowered = family.lower()
    return "mono" in lowered or "code" in lowered or "courier" in lowered


def _text_of(node: dict) -> str:
    for key in _TEXT_KEYS:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    for key in _TEXT_KEYS:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _short(text: str, limit: int = 42) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _size(node: dict) -> tuple[float | None, float | None]:
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    return _num(frame.get("width")), _num(frame.get("height"))


def _style(node: dict) -> dict:
    return node.get("style") if isinstance(node.get("style"), dict) else {}


def _has_fill(style: dict) -> bool:
    value = style.get("background") or style.get("backgroundColor")
    return isinstance(value, str) and value.strip() not in ("", "none", "transparent")


def _has_border(style: dict) -> bool:
    width = _num(style.get("borderWidth"))
    color = str(style.get("borderColor") or style.get("border") or "")
    return bool(width and width > 0 and color and color not in ("none", "transparent"))


def _has_shadow(style: dict) -> bool:
    shadow = style.get("boxShadow")
    return isinstance(shadow, str) and shadow.strip() not in ("", "none")


def _type_spec(style: dict) -> str:
    """«Hanken Grotesk 12/400 #908da0 upper tracked» — типографика узла одной строкой."""
    family = _family(style)
    size, weight = _num(style.get("fontSize")), style.get("fontWeight")
    parts = [family] if family else []
    if size:
        parts.append(f"{_fmt(size)}/{weight}" if weight else _fmt(size))
    color = style.get("color")
    if isinstance(color, str) and color.startswith("#"):
        parts.append(color.lower())
    if str(style.get("textTransform") or "") == "uppercase":
        parts.append("upper")
    tracking = _num(style.get("letterSpacing"))
    if tracking and tracking >= 0.5:
        parts.append("tracked")
    return " ".join(parts)


def _surface_spec(style: dict, width: float | None, height: float | None) -> str:
    parts: list[str] = []
    if _has_fill(style):
        parts.append(f"bg {str(style.get('background') or style.get('backgroundColor'))[:40]}")
    if _has_border(style):
        parts.append(f"border {_fmt(_num(style.get('borderWidth')))}px {style.get('borderColor')}")
    radius = _num(style.get("borderRadius"))
    if radius is not None and radius > 0:
        parts.append("pill" if height and radius >= height / 2 else f"r{_fmt(radius)}")
    if _has_shadow(style):
        parts.append("shadow")
    return " ".join(parts)


class _Walker:
    """Один проход по дереву: анатомия, декоративные признаки, образцы текста."""

    def __init__(self) -> None:
        self.anatomy: list[dict] = []
        self.traits: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = {}
        self.mono_labels: list[dict] = []
        self.borders: list[tuple[float, str]] = []
        self.shadows: list[str] = []
        self.pills: list[dict] = []

    # --- накопление ---------------------------------------------------------
    def note(self, trait: str, example: str = "") -> None:
        self.traits[trait] += 1
        if example:
            bucket = self.examples.setdefault(trait, [])
            if example not in bucket and len(bucket) < 4:
                bucket.append(example)

    def add(self, kind: str, text: str = "", spec: str = "", extra: str = "") -> None:
        """Анатомия хранится структурно: переносы строк источника (один абзац,
        разбитый захватом на несколько text-узлов, плюс дубли для других
        вьюпортов) склеиваются в одну запись, одинаковые соседи считаются ×N."""
        if self.anatomy:
            last = self.anatomy[-1]
            if kind == "text" and last["kind"] == "text" and last["spec"] == spec and text:
                if text in last["text"]:
                    return
                if last["text"] in text:
                    last["text"] = text
                    return
                last["text"] = f"{last['text']} {text}"
                return
            if (last["kind"], last["text"], last["spec"], last["extra"]) == (kind, text, spec, extra):
                last["count"] += 1
                return
        self.anatomy.append({"kind": kind, "text": text, "spec": spec, "extra": extra, "count": 1})

    def render(self) -> list[str]:
        out = []
        for entry in self.anatomy:
            piece = entry["kind"]
            if entry["text"]:
                piece += f' "{_short(entry["text"])}"'
            if entry["spec"]:
                piece += " " + entry["spec"]
            if entry["extra"]:
                piece += " " + entry["extra"]
            if entry["count"] > 1:
                piece += f" ×{entry['count']}"
            out.append(piece.strip())
        return out

    # --- обход --------------------------------------------------------------
    def visit(self, node: dict, depth: int = 0, siblings: list | None = None) -> None:
        if depth > MAX_DEPTH or not isinstance(node, dict):
            return
        kind = str(node.get("type") or "")
        style = _style(node)
        width, height = _size(node)
        text = _text_of(node)
        children = [child for child in (node.get("children") or []) if isinstance(child, dict)]
        family = _family(style)
        size = _num(style.get("fontSize"))
        self._text_traits(text, style, family, size)
        if _has_border(style):
            self.borders.append((float(_num(style.get("borderWidth")) or 0), str(style.get("borderColor"))))
        if _has_shadow(style):
            self.shadows.append(str(style.get("boxShadow")))
        if kind in ("text", "heading", "paragraph", "link"):
            if text:
                self.add("link" if kind == "link" else "text", text, _type_spec(style))
            self._prefix_hint(node, siblings)
            return
        if kind == "button":
            radius = _num(style.get("borderRadius"))
            self.add("button", _short(text, 30), _type_spec(style), _surface_spec(style, width, height))
            if height and radius is not None and radius >= height / 2:
                self.note("pill-button", text)
            if _has_shadow(style) and "rgba" in str(style.get("boxShadow")):
                self.note("glow-shadow", str(style.get("boxShadow"))[:60])
            return  # текст кнопки уже учтён; дочерний text — дубликат
        if kind == "input":
            placeholder = str(node.get("placeholder") or text or "")
            radius = _num(style.get("borderRadius")) or 0
            self.add("input", _short(placeholder, 30), _type_spec(style), "square" if radius == 0 else f"r{_fmt(radius)}")
            if _is_mono(family):
                self.note("mono-input", placeholder)
            if radius == 0:
                self.note("square-input", placeholder)
            self._form_hint(siblings)
            return
        if kind in ("image", "icon", "avatar", "logo"):
            radius = _num(style.get("borderRadius"))
            round_shape = bool(width and radius and radius >= width / 2)
            small = bool(width and height and max(width, height) <= 28)
            label = "icon" if (small or kind == "icon") else "avatar" if (round_shape or kind == "avatar") else "image"
            self.add(label, "", f"{_fmt(width)}×{_fmt(height)}")
            self.note(label)
            return
        # контейнеры: точка, разделитель, фон-паттерн, пилюля, инициал, поверхность
        surface = _surface_spec(style, width, height)
        if width and height and max(width, height) <= 8 and _has_fill(style):
            self.add("dot", "", f"{_fmt(width)}px {style.get('background') or style.get('backgroundColor')}")
            self.note("status-dot")
            return
        if width and height and height <= 2 and width >= 40 and (_has_fill(style) or _has_border(style)):
            self.add("divider", "", "1px")
            self.note("divider")
            return
        background_image = style.get("backgroundImage")
        if isinstance(background_image, str) and background_image not in ("", "none"):
            trait = "gradient-bg" if "gradient" in background_image else "image-bg"
            self.note(trait, background_image[:60])
            self.add("bg-pattern", "", background_image[:56])
        radius = _num(style.get("borderRadius"))
        child_label = next((_text_of(child) for child in children if _text_of(child)), "")
        is_pill = bool(height and radius is not None and height <= 40 and radius >= height / 2
                       and (_has_fill(style) or _has_border(style)))
        if is_pill:
            dot = next((child for child in children
                        if max(_size(child)[0] or 0, _size(child)[1] or 0) <= 8 and _has_fill(_style(child))), None)
            label = child_label or text
            label_style = next((_style(child) for child in children if _text_of(child)), style)
            extra = surface + (f" + dot {_fmt(_size(dot)[0])}px" if dot is not None else "")
            self.add("pill", _short(label, 30), _type_spec(label_style), extra.strip())
            if re.fullmatch(r"\d{1,2}", label or ""):
                self.note("numbered-pill", label)
            else:
                self.note("pill-badge", label)
                if dot is not None:
                    self.note("status-dot", label)
                self.pills.append({"label": label, "height": height, "dot": dot is not None,
                                   "type": _type_spec(label_style)})
            return
        square = bool(width and height and abs(width - height) <= 2 and width <= 40)
        if square and _has_fill(style) and len(child_label) == 1 and child_label.isalnum():
            self.add("initial", child_label, f"{_fmt(width)}px", surface)
            self.note("avatar-initial", child_label)
            return
        if surface and depth > 0:
            self.add(kind or "box", "", f"{_fmt(width)}×{_fmt(height)}", surface)
        for child in children:
            self.visit(child, depth + 1, children)

    def _text_traits(self, text: str, style: dict, family: str, size: float | None) -> None:
        if not text:
            return
        upper = str(style.get("textTransform") or "") == "uppercase" or (text.isupper() and len(text) >= 2)
        tracked = bool((_num(style.get("letterSpacing")) or 0) >= 0.5)
        if _is_mono(family) and size and size <= 13 and len(text) >= 2:
            self.note("mono-label", text if len(text) >= 3 else "")
            self.mono_labels.append({"family": family, "size": size, "upper": upper, "tracked": tracked, "text": text})
        elif size and size <= 12 and (upper or tracked) and len(text) >= 3:
            self.note("small-caps-label", text)
        if text.rstrip().endswith(_ARROWS):
            self.note("arrow-cta", text)
        if " · " in text or " • " in text:
            self.note("dot-separator", text)
        if " / " in text:
            self.note("slash-separator", text)
        if _NUMBERED_WORD.match(text) or _NUMBERED_MARK.match(text):
            self.note("numbered-label", text)
        if _STAT.match(text):
            self.note("stat-number", text)

    def _prefix_hint(self, node: dict, siblings: list | None) -> None:
        if not siblings:
            return
        try:
            index = siblings.index(node)
        except ValueError:
            return
        nxt = siblings[index + 1] if index + 1 < len(siblings) else None
        if isinstance(nxt, dict) and str(nxt.get("type") or "") == "input":
            self.note("input-prefix", _text_of(node))

    def _form_hint(self, siblings: list | None) -> None:
        button = next((s for s in siblings or [] if isinstance(s, dict) and s.get("type") == "button"), None)
        if button is not None:
            self.note("inline-form", _text_of(button))


def _root_spec(root: dict) -> dict:
    style = _style(root)
    frame = root.get("frame") if isinstance(root.get("frame"), dict) else {}
    width, height = _size(root)
    spec: dict[str, Any] = {"size": f"{_fmt(width)}×{_fmt(height)}"}
    surface = _surface_spec(style, width, height)
    if surface:
        spec["surface"] = surface
    layout = []
    if frame.get("direction"):
        layout.append(str(frame["direction"]))
    if frame.get("gap") is not None:
        layout.append(f"gap {_fmt(_num(frame.get('gap')))}")
    padding = frame.get("padding")
    if isinstance(padding, list) and padding:
        layout.append("pad " + "/".join(_fmt(_num(p)) for p in padding[:4]))
    elif _num(padding) is not None:
        layout.append(f"pad {_fmt(_num(padding))}")
    if layout:
        spec["layout"] = " ".join(layout)
    bindings = root.get("styleBindings") if isinstance(root.get("styleBindings"), dict) else {}
    tokens = {}
    # color намеренно не включаем: цвет текста уже есть у каждого текста в анатомии,
    # а привязка корня бывает ошибочной (ссылка «semantic.background» → невидимая ссылка).
    for prop in ("background", "borderColor", "borderRadius"):
        binding = bindings.get(prop)
        token = binding.get("token") if isinstance(binding, dict) else binding
        if isinstance(token, str) and token:
            tokens[prop] = token
    if tokens:
        spec["tokens"] = tokens
    return spec


def summarize_master(component: dict) -> dict:
    """Структурированная сводка мастера: корень, анатомия, декоративные признаки."""
    master = component.get("masterIr") if isinstance(component.get("masterIr"), dict) else {}
    tree = master.get("tree") if isinstance(master.get("tree"), list) else []
    root = tree[0] if tree and isinstance(tree[0], dict) else {}
    walker = _Walker()
    walker.visit(root)
    summary: dict[str, Any] = {
        "key": str(component.get("componentKey") or ""),
        "name": str(component.get("name") or component.get("componentKey") or ""),
        "category": str(component.get("category") or ""),
    }
    description = str(component.get("description") or "").strip()
    if description and not description.lower().startswith("observed"):
        summary["description"] = description[:120]
    variants = [str(key) for key, value in (component.get("variants") or {}).items() if isinstance(value, dict)]
    if variants and variants != ["default"]:
        summary["variants"] = variants[:6]
    summary["root"] = _root_spec(root)
    anatomy = walker.render()
    summary["anatomy"] = anatomy[:MAX_ANATOMY]
    if len(anatomy) > MAX_ANATOMY:
        summary["anatomy"].append(f"…+{len(anatomy) - MAX_ANATOMY}")
    decor = [trait for trait, _count in walker.traits.most_common() if trait not in ("image", "icon", "avatar")]
    if decor:
        summary["decor"] = decor[:8]
    return summary


def summary_line(component: dict, *, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    """Строка промпта «- Master key [category]: {...}», уложенная в max_chars."""
    summary = summarize_master(component)
    key, category = summary.pop("key"), summary.pop("category")
    prefix = f"- Master {key} [{category}]: "
    payload = _json(summary)
    while len(prefix) + len(payload) > max_chars and summary.get("anatomy"):
        # Каждый шаг убирает один реальный элемент анатомии (маркер «…» не в счёт),
        # поэтому цикл конечен.
        anatomy = [item for item in summary["anatomy"] if not str(item).startswith("…")]
        if len(anatomy) <= 3:
            break
        summary["anatomy"] = anatomy[:-1] + ["…"]
        payload = _json(summary)
    if len(prefix) + len(payload) > max_chars:
        payload = payload[: max_chars - len(prefix) - 1].rstrip() + "…"
    return prefix + payload


def _walk_all(components: list[dict]) -> _Walker:
    walker = _Walker()
    for component in components:
        master = component.get("masterIr") if isinstance(component, dict) and isinstance(component.get("masterIr"), dict) else {}
        for section in master.get("tree") or []:
            if isinstance(section, dict):
                walker.visit(section)
    return walker


def _signature(sig_id: str, name: str, rule: str, examples: list[str], confidence: float) -> dict:
    unique = list(dict.fromkeys(str(e)[:60] for e in examples if str(e).strip()))
    return {"id": sig_id, "name": name, "rule": rule, "examples": unique[:3],
            "provenance": "measured", "confidence": round(confidence, 2), "confirmed": False}


def decorative_signatures(components: list[dict]) -> list[dict]:
    """Кросс-компонентные декоративные сигнатуры системы с примерами из мастеров."""
    components = [c for c in components or [] if isinstance(c, dict) and isinstance(c.get("masterIr"), dict)]
    if not components:
        return []
    walker = _walk_all(components)
    traits, examples = walker.traits, walker.examples
    out: list[dict] = []
    if walker.mono_labels:
        family = Counter(item["family"] for item in walker.mono_labels).most_common(1)[0][0]
        sizes = sorted(item["size"] for item in walker.mono_labels)
        upper = sum(1 for item in walker.mono_labels if item["upper"]) >= len(walker.mono_labels) / 2
        tracked = sum(1 for item in walker.mono_labels if item["tracked"]) >= len(walker.mono_labels) / 2
        span = f"{_fmt(sizes[0])}–{_fmt(sizes[-1])}px" if sizes[0] != sizes[-1] else f"{_fmt(sizes[0])}px"
        rule = (f"Служебные лейблы, метаданные и цифры набираются {family} {span}"
                + (", uppercase" if upper else "") + (", с разрядкой" if tracked else "")
                + "; основной текст этим шрифтом не набирать")
        out.append(_signature("sig-mono-labels", "Mono labels", rule, examples.get("mono-label", []),
                              0.9 if len(walker.mono_labels) >= 3 else 0.7))
    if walker.pills:
        with_dot = [p for p in walker.pills if p["dot"]]
        heights = sorted(p["height"] for p in walker.pills if p["height"])
        height = _fmt(heights[len(heights) // 2]) if heights else "?"
        rule = f"Статус и категория — пилюля высотой ~{height}px с мелким текстом ({walker.pills[0]['type']})"
        if with_dot:
            rule += ", перед текстом цветная точка 4px (статус-индикатор)"
        out.append(_signature("sig-status-pill", "Status pill", rule,
                              [p["label"] for p in (with_dot or walker.pills)], 0.85))
    if traits.get("arrow-cta"):
        out.append(_signature("sig-arrow-cta", "Arrow CTA",
                              "Направляющие действия и ссылки заканчиваются стрелкой «→»",
                              examples.get("arrow-cta", []), 0.85))
    separators = examples.get("dot-separator", []) + examples.get("slash-separator", [])
    if separators:
        marks = [mark for mark, key in (("·", "dot-separator"), ("/", "slash-separator")) if traits.get(key)]
        out.append(_signature("sig-label-separators", "Label separators",
                              "Составные лейблы делятся разделителями " + " и ".join(f"«{m}»" for m in marks)
                              + " вместо тире и запятых", separators, 0.8))
    if traits.get("numbered-label") or traits.get("numbered-pill"):
        rule = "Шаги и дни нумеруются коротким моно-лейблом («DAY 1», «2 · …»), номер — часть лейбла"
        if traits.get("numbered-pill"):
            rule += "; у шага процесса номер стоит в круглой пилюле цвета акцента"
        out.append(_signature("sig-numbered-steps", "Numbered steps", rule,
                              examples.get("numbered-label", []) + examples.get("numbered-pill", []), 0.8))
    if traits.get("inline-form") or traits.get("input-prefix"):
        prefix = examples.get("input-prefix", [])
        rule = "Форма — одна строка: поле с квадратными углами"
        if prefix:
            rule += f" и префиксом «{prefix[0]}»"
        rule += ", справа кнопка-пилюля"
        if traits.get("mono-input"):
            rule += "; поле набрано моноширинным шрифтом"
        out.append(_signature("sig-inline-form", "Inline form", rule, prefix + examples.get("inline-form", []), 0.8))
    if walker.borders:
        width = Counter(round(w, 1) for w, _color in walker.borders).most_common(1)[0][0]
        colors = Counter(color.lower() for _w, color in walker.borders if str(color).startswith("#"))
        if width <= 1.5 and colors:
            color = colors.most_common(1)[0][0]
            out.append(_signature("sig-hairline-borders", "Hairline borders",
                                  f"Рамки {_fmt(width)}px приглушённого цвета ({color}): поверхности отделяются тонкой линией, а не контрастом заливки",
                                  [], 0.8))
    colored = [s for s in walker.shadows if "rgba(" in s and not re.search(r"rgba\(0,\s*0,\s*0", s)]
    if colored:
        out.append(_signature("sig-glow-shadow", "Accent glow",
                              "Тени только цветные и мягкие, в цвете акцента, под кнопками и активными элементами; чёрных теней нет",
                              [colored[0][:60]], 0.75))
    if traits.get("avatar-initial"):
        out.append(_signature("sig-avatar-initial", "Initial avatar",
                              "Идентификатор компании — квадрат ~30px со скруглением и моно-буквой вместо логотипа",
                              examples.get("avatar-initial", []), 0.7))
    if traits.get("gradient-bg") or traits.get("image-bg"):
        out.append(_signature("sig-background-pattern", "Background pattern",
                              "Фоновые поверхности несут градиент или паттерн из источника, а не плоскую заливку",
                              examples.get("gradient-bg", []) + examples.get("image-bg", []), 0.7))
    return out[:MAX_SIGNATURES]


def signature_lines(signatures: list[dict]) -> list[tuple[str, str]]:
    lines = []
    for item in signatures:
        examples = item.get("examples") or []
        suffix = (" Примеры: " + " | ".join(f"«{e}»" for e in examples)) if examples else ""
        lines.append((str(item["id"]), f"- Decor signature: {item['rule']}.{suffix}"))
    return lines
