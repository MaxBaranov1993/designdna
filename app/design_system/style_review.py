"""Style Guide дизайн-системы: семантические токены + AI-ревью стилистики.

Две части:

1. Детерминированная — всегда присутствует. Измеренные значения Source
   раскладываются в стандартную семантическую карту токенов в духе shadcn/ui
   (background/foreground/primary/muted/border/radius/...) плюс «характер»
   стиля (скругления, плотность, тени), посчитанный из фактических величин.

2. AI-ревью — опциональный проход. Модель получает компактный дайджест
   (токены, характер, состав компонентов, образцы текста) и возвращает
   СТРОГО ограниченный JSON: тон, правила Do/Don't, заметки по компонентам.
   Ревью не может менять мастера, токены или fidelity — только описывать
   дизайн-язык, который потом попадает в промпт генерации, чтобы новые
   компоненты стилистически вписывались в существующий сайт.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.lower() if _HEX.match(text) else None


def _luminance(color: str) -> float:
    rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _foreground_for(color: str | None, dark: str, light: str) -> str:
    if not color:
        return dark
    return dark if _luminance(color) > 0.55 else light


def _reddish(colors: list[str]) -> str | None:
    """Найти «деструктивный» красный среди измеренных цветов."""
    for color in colors:
        value = _hex(color)
        if not value:
            continue
        r = int(value[1:3], 16)
        g = int(value[3:5], 16)
        b = int(value[5:7], 16)
        if r > 150 and r > g * 1.6 and r > b * 1.6:
            return value
    return None


def semantic_tokens(foundations: dict) -> dict:
    """Измеренные foundations → стандартная семантическая карта токенов.

    Имена сознательно повторяют соглашение shadcn/ui: это lingua franca
    современных дизайн-систем, и генератору проще следовать знакомой карте,
    чем сырому списку measured1..16.
    """
    colors = (foundations.get("colors") or {})
    semantic = colors.get("semantic") or {}
    primitives = colors.get("primitives") or {}
    background = _hex(semantic.get("background")) or "#ffffff"
    text = _hex(semantic.get("text")) or "#111827"
    surface = _hex(semantic.get("surface")) or background
    primary = _hex(semantic.get("primary")) or text
    accent = _hex(semantic.get("accent")) or primary
    muted_fg = _hex(semantic.get("textMuted")) or text
    # Рамка: захват схлопывает rgba в непрозрачный цвет; приглушаем, иначе
    # и кит, и AI-ревью описывают «белые рамки», которых на сайте нет.
    border = soften_border({"background": background,
                            "border": _hex(semantic.get("border")) or "#e5e7eb"})["border"]
    secondary = _hex(semantic.get("secondary")) or surface

    radius_px = foundations.get("radius") or {}
    typography = foundations.get("typography") or {}
    display = (typography.get("display") or {})
    body = (typography.get("body") or {})

    tokens = {
        "background": background,
        "foreground": text,
        "card": surface,
        "card-foreground": text,
        "primary": primary,
        "primary-foreground": _foreground_for(primary, text, "#ffffff"),
        "secondary": secondary,
        "secondary-foreground": _foreground_for(secondary, text, "#ffffff"),
        "muted": surface,
        "muted-foreground": muted_fg,
        "accent": accent,
        "accent-foreground": _foreground_for(accent, text, "#ffffff"),
        "border": border,
        "input": border,
        "ring": primary,
        "radius": radius_px.get("card"),
        "radius-button": radius_px.get("button"),
        "radius-input": radius_px.get("input"),
        "font-display": display.get("family"),
        "font-body": body.get("family"),
    }
    destructive = _reddish(list(primitives.values()))
    if destructive:
        tokens["destructive"] = destructive
        tokens["destructive-foreground"] = _foreground_for(destructive, text, "#ffffff")
    return {key: value for key, value in tokens.items() if value is not None}


def measured_character(foundations: dict) -> dict:
    """Характер стиля из фактических величин — без участия модели."""
    radius_px = foundations.get("radius") or {}
    button_radius = float(radius_px.get("button") or 0)
    if button_radius <= 2:
        corner = "sharp"
    elif button_radius <= 8:
        corner = "subtle"
    elif button_radius <= 18:
        corner = "rounded"
    else:
        corner = "pill"

    spacings = [value for value in (foundations.get("spacing") or {}).values()
                if isinstance(value, (int, float))]
    if spacings:
        spacings.sort()
        median = spacings[len(spacings) // 2]
        density = "compact" if median < 12 else "comfortable" if median < 24 else "airy"
    else:
        density = "comfortable"

    shadows = foundations.get("shadows") or []
    shadow_usage = "none" if not shadows else "subtle" if len(shadows) <= 2 else "layered"

    primitives = ((foundations.get("colors") or {}).get("primitives") or {})
    return {
        "mode": foundations.get("mode") or "light",
        "cornerCharacter": corner,
        "density": density,
        "shadowUsage": shadow_usage,
        "paletteSize": len(primitives),
    }


_SHADCN_TO_IR = {
    "background": "background", "card": "surface", "foreground": "text",
    "muted-foreground": "textMuted", "primary": "primary", "secondary": "secondary",
    "accent": "accent", "border": "border",
}
_IR_TOKEN_KEYS = ("mode", "color", "font", "radius", "spacing", "shadow")


def ir_tokens(foundations: dict) -> dict:
    """Foundations дизайн-системы → полные Design IR tokens v1 (schema-валидные).

    Генератор лочит именно эту форму; foundations хранят px и measured-списки,
    поэтому идём через normalize_dna (px → enum, дефолты для пропусков)."""
    from .builder import _shadow_enum, _tokens_for_ir, normalize_dna  # noqa: WPS433 — циклический импорт

    foundations = foundations if isinstance(foundations, dict) else {}
    colors = (foundations.get("colors") or {}).get("semantic") or {}
    typography = foundations.get("typography") or {}
    shadows = foundations.get("shadows") or []
    raw = {
        "mode": foundations.get("mode"),
        "color": soften_border(dict(colors)),
        "font": {
            "display": typography.get("display") or {},
            "body": typography.get("body") or {},
        },
        "radius": dict(foundations.get("radius") or {}),
        "spacing": {
            "section": (foundations.get("spacing") or {}).get("section"),
            "container": (foundations.get("containers") or {}).get("content"),
        },
        "shadow": "none" if not shadows else _shadow_enum("sm" if len(shadows) <= 2 else "md"),
    }
    return _tokens_for_ir(normalize_dna(raw))


def coerce_ir_tokens(tokens: Any) -> dict | None:
    """Любая форма style-DNA с порта → полные IR tokens v1, либо None.

    Порт Design System отдавал плоскую shadcn-карту (background/foreground/…),
    а сервер лочил из неё единственный совпавший ключ ``radius`` — IR падал на
    схеме «tokens: 'color' is a required property». Принимаем три формы:
    tokens v1 (в т.ч. частичные), плоскую карту style guide и foundations."""
    from .builder import _tokens_for_ir, normalize_dna  # noqa: WPS433

    if not isinstance(tokens, dict) or not tokens:
        return None
    if isinstance(tokens.get("colors"), dict) or isinstance(tokens.get("typography"), dict):
        return ir_tokens(tokens)
    if isinstance(tokens.get("color"), dict) or isinstance(tokens.get("font"), dict):
        softened = dict(tokens, color=soften_border(dict(tokens.get("color") or {})))
        full = _tokens_for_ir(normalize_dna(softened))
        for key in ("primitives", "semantic", "provenance", "v2"):
            if key in tokens:
                full[key] = copy.deepcopy(tokens[key])
        return full
    flat_colors = {ir_key: _hex(tokens.get(flat_key))
                   for flat_key, ir_key in _SHADCN_TO_IR.items() if _hex(tokens.get(flat_key))}
    if not flat_colors:
        return None
    font: dict[str, Any] = {}
    if tokens.get("font-display"):
        font["display"] = {"family": str(tokens["font-display"]), "weight": 700}
    if tokens.get("font-body"):
        font["body"] = {"family": str(tokens["font-body"]), "weight": 400}
    radius = {
        "card": tokens.get("radius"),
        "button": tokens.get("radius-button", tokens.get("radius")),
        "input": tokens.get("radius-input", tokens.get("radius")),
    }
    background = flat_colors.get("background")
    mode = ("dark" if background and _luminance(background) < 0.45 else "light")
    return _tokens_for_ir(normalize_dna({"mode": mode, "color": soften_border(flat_colors), "font": font, "radius": radius}))


def _is_mono(family: Any) -> bool:
    return "mono" in str(family or "").lower() or "code" in str(family or "").lower()


def _classify_text(node: dict) -> str:
    """Роль текста мастера Source Import: по типу узла и измеренному стилю.
    Захват отдаёт почти всё как `text`, поэтому заголовки узнаём по кеглю,
    надзаголовки — по моно/uppercase/разрядке, CTA — по кнопке."""
    kind = str(node.get("type") or "")
    if kind == "button":
        return "cta"
    if kind == "heading":
        return "heading"
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    size = float(style.get("fontSize") or 0)
    tracking = float(style.get("letterSpacing") or 0)
    upper = str(style.get("textTransform") or "") == "uppercase"
    text = str(node.get("text") or "")
    if size >= 22:
        return "heading"
    if size <= 13 and (upper or tracking >= 0.5 or (_is_mono(style.get("fontFamily")) and text.isupper())):
        return "eyebrow"
    if node.get("size") in ("xs", "sm"):
        return "eyebrow"
    return "text"


def _walk_text(node: Any, out: dict[str, list[str]], depth: int = 0) -> None:
    if depth > 12 or not isinstance(node, dict):
        return
    text = node.get("text")
    if isinstance(text, str) and text.strip() and len(text.strip()) > 1:
        out[_classify_text(node)].append(" ".join(text.split())[:90])
    props = node.get("props")
    if isinstance(props, dict):
        for key in ("heading", "subheading", "eyebrow", "title"):
            value = props.get(key)
            if isinstance(value, str) and value.strip():
                out["eyebrow" if key == "eyebrow" else "heading" if key in ("heading", "title") else "text"].append(" ".join(value.split())[:90])
        for key in ("cta", "ctaPrimary", "ctaSecondary"):
            value = props.get(key)
            if isinstance(value, dict) and isinstance(value.get("text"), str) and value["text"].strip():
                out["cta"].append(value["text"].strip()[:60])
    for child in node.get("children") or []:
        _walk_text(child, out, depth + 1)


def _default_content_values() -> set[str]:
    """Значения мок-контента по умолчанию (builder._DEFAULT_CONTENT*): они попадают
    в referenceContent, когда на сайте нет категории/цены/FAQ, и не должны
    выдаваться за копирайт сайта («Electronics | Home | Accessories»)."""
    from .builder import _DEFAULT_CONTENT, _DEFAULT_CONTENT_EN  # noqa: WPS433

    values: set[str] = set()
    for table in (_DEFAULT_CONTENT, _DEFAULT_CONTENT_EN):
        for value in table.values():
            if isinstance(value, list):
                values.update(str(v) for v in value)
            elif isinstance(value, str):
                values.add(value)
    return values


def real_reference_content(document: dict) -> dict[str, list[str]]:
    """referenceContent без дефолтных мок-значений."""
    reference = document.get("referenceContent") if isinstance(document.get("referenceContent"), dict) else {}
    defaults = _default_content_values()
    out: dict[str, list[str]] = {}
    for key, value in reference.items():
        items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        kept = [" ".join(str(item).split()) for item in items if str(item).strip() and str(item) not in defaults]
        if kept:
            out[str(key)] = kept
    return out


def _copy_voice(document: dict) -> dict[str, list[str]]:
    """Образцы текста сайта: заголовки, надзаголовки, CTA, бейджи — голос бренда.

    Сначала referenceContent (собран со всей страницы), затем тексты мастеров
    (включая review-пул: компонентов с verified-статусом может не быть)."""
    out: dict[str, list[str]] = {"heading": [], "eyebrow": [], "cta": [], "badge": [], "text": []}
    reference = real_reference_content(document)
    for key, bucket in (("heading", "heading"), ("title", "heading"), ("cta", "cta"), ("badge", "badge"),
                        ("category", "eyebrow"), ("price", "badge")):
        out[bucket].extend(v[:90] for v in reference.get(key) or [])
    for pool in ("components", "reviewComponents"):
        for component in (document.get(pool) or {}).values():
            master = component.get("masterIr") if isinstance(component, dict) else None
            for section in ((master or {}).get("tree") or []):
                _walk_text(section, out)
    return {key: list(dict.fromkeys(values))[:6] for key, values in out.items() if values}


def _label_style(document: dict) -> str:
    """Стиль лейблов/надзаголовков и цифр из измеренных стилей мастеров."""
    samples: list[dict] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 12 or not isinstance(node, dict):
            return
        if isinstance(node.get("text"), str) and isinstance(node.get("style"), dict):
            samples.append(node)
        for child in node.get("children") or []:
            walk(child, depth + 1)

    for pool in ("components", "reviewComponents"):
        for component in (document.get(pool) or {}).values():
            for section in (((component or {}).get("masterIr") or {}).get("tree") or []):
                walk(section)
    eyebrows = [n for n in samples if _classify_text(n) == "eyebrow"]
    if not eyebrows:
        return ""
    mono = sum(1 for n in eyebrows if _is_mono(n["style"].get("fontFamily")))
    upper = sum(1 for n in eyebrows if str(n["style"].get("textTransform")) == "uppercase" or str(n.get("text")).isupper())
    tracked = sum(1 for n in eyebrows if float(n["style"].get("letterSpacing") or 0) >= 0.5)
    family = next((str(n["style"].get("fontFamily")).split(",")[0].strip() for n in eyebrows
                   if _is_mono(n["style"].get("fontFamily"))), "")
    parts = []
    if mono >= len(eyebrows) / 2:
        parts.append(f"моноширинный {family or 'mono'}".strip())
    if upper >= len(eyebrows) / 2:
        parts.append("uppercase")
    if tracked >= len(eyebrows) / 2:
        parts.append("с разрядкой")
    sizes = sorted(float(n["style"].get("fontSize") or 0) for n in eyebrows)
    if sizes:
        parts.append(f"кегль ~{int(sizes[len(sizes) // 2])}px")
    return ", ".join(parts)


def _typography_character(foundations: dict) -> str:
    typography = foundations.get("typography") or {}
    display = str((typography.get("display") or {}).get("family") or "")
    body = str((typography.get("body") or {}).get("family") or "")
    weight = int((typography.get("display") or {}).get("weight") or 700)
    serif_markers = ("Serif", "Playfair", "Prata", "Cormorant", "Garamond", "Lora", "Vollkorn",
                     "Merriweather", "Literata", "Georgia", "Times")
    mono_markers = ("Mono", "Code", "Courier")
    kind = ("моноширинный" if any(m in display for m in mono_markers)
            else "серифный" if any(m in display for m in serif_markers) else "гротеск")
    heaviness = "тяжёлый" if weight >= 700 else "средний" if weight >= 500 else "лёгкий"
    pairing = "одна гарнитура на всё" if display and display == body else f"пара {display} + {body}"
    return f"{kind} display ({display or '—'}, {heaviness} {weight}); {pairing}"


def style_profile(document: dict) -> dict:
    """Детерминированный профиль стиля сайта: атмосфера без участия модели.

    Это то, что генератор должен «помнить» о сайте помимо hex-значений:
    тема, характер углов и плотности, типографика, использование теней и
    палитры, направление картинок и иконок, голос текста (образцы копирайта)."""
    foundations = document.get("foundations") or {}
    measured = measured_character(foundations)
    primitives = ((foundations.get("colors") or {}).get("primitives") or {})
    semantic = ((foundations.get("colors") or {}).get("semantic") or {})
    brand = [value for key, value in primitives.items() if str(key).startswith("brand")]
    profile = {
        "mode": measured["mode"],
        "cornerCharacter": measured["cornerCharacter"],
        "density": measured["density"],
        "shadowUsage": measured["shadowUsage"],
        "paletteCharacter": (
            "монохром с одним акцентом" if len(brand) <= 1
            else f"{len(brand)} брендовых цвета" if len(brand) <= 3 else "многоцветная палитра"
        ),
        "accent": semantic.get("accent") or semantic.get("primary"),
        "typographyCharacter": _typography_character(foundations),
        "labelStyle": _label_style(document),
        "monoFamily": next((str(f) for f in ((foundations.get("typography") or {}).get("families") or []) if _is_mono(f)), ""),
        "imageDirection": foundations.get("imageDirection") or "",
        "iconStyle": foundations.get("iconStyle") or "",
        "copyVoice": _copy_voice(document),
    }
    return {key: value for key, value in profile.items() if value not in ("", None, [], {})}


def _mix_hex(color: str, into: str, amount: float) -> str:
    """color, смешанный с into на amount (0..1)."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(into[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - amount) + y * amount):02x}" for x, y in zip(a, b))


def soften_border(colors: dict) -> dict:
    """Захват схлопывает rgba-рамки в непрозрачный цвет: на тёмном сайте
    border=#ffffff, и каждая сгенерированная карточка получала яркую белую
    рамку (судья: «яркие контрастные рамки — провал»). Если рамка контрастнее
    фона, чем 0.5 по светлоте, приглушаем её до ~14% поверх фона."""
    background = _hex(colors.get("background"))
    border = _hex(colors.get("border"))
    if not background or not border:
        return colors
    if abs(_luminance(border) - _luminance(background)) > 0.5:
        return {**colors, "border": _mix_hex(border, background, 0.86)}
    return colors


def profile_prompt(document: dict) -> str:
    """Блок промпта «стиль и атмосфера» для генератора: профиль + AI-ревью, если есть."""
    guide = document.get("styleGuide") if isinstance(document.get("styleGuide"), dict) else {}
    profile = guide.get("profile") or style_profile(document)
    voice = profile.get("copyVoice") or {}
    brief = document.get("siteBrief") if isinstance(document.get("siteBrief"), dict) else site_brief(document)
    lines = ["## Сайт, в который встраивается результат"]
    if brief.get("summary"):
        lines.append(f"- {brief['summary']}")
    else:
        if brief.get("brand") or brief.get("url"):
            lines.append(f"- {brief.get('brand') or ''} {brief.get('url') or ''}".strip())
        if brief.get("headings"):
            lines.append("- Заголовки сайта: " + " | ".join(brief["headings"][:5]))
    for key, label in (("audience", "Аудитория"), ("offer", "Оффер"), ("tone", "Голос текста")):
        if brief.get(key):
            lines.append(f"- {label}: {brief[key]}")
    if brief.get("sections"):
        lines.append("- Секции сайта по порядку: " + " → ".join(brief["sections"][:10]))
    usage = brief.get("componentUsage") or {}
    if usage:
        lines.append("- Где живут компоненты: " + "; ".join(f"{key} — {note}" for key, note in list(usage.items())[:8]))
    lines += [
        "",
        "## Стиль и атмосфера исходного сайта (компонент обязан встраиваться, а не выделяться)",
        f"- Тема: {profile.get('mode')}; углы: {profile.get('cornerCharacter')}; плотность: {profile.get('density')}; "
        f"тени: {profile.get('shadowUsage')}; палитра: {profile.get('paletteCharacter')}.",
        f"- Типографика: {profile.get('typographyCharacter')}.",
    ]
    if profile.get("labelStyle"):
        lines.append(f"- Лейблы, надзаголовки и служебные цифры: {profile['labelStyle']} — используй такой же стиль "
                     f"для eyebrow/бейджей/цен, а не body-шрифт.")
    elif profile.get("monoFamily"):
        lines.append(f"- Служебный шрифт сайта: {profile['monoFamily']} (лейблы, цифры, коды).")
    if profile.get("mode") == "dark":
        lines.append("- Тёмная тема исходника: поверхности карточек лишь чуть светлее фона (surface/border из токенов), "
                     "рамки тонкие и приглушённые, никаких светлых плашек и белых карточек.")
    if profile.get("imageDirection"):
        lines.append(f"- Изображения: {profile['imageDirection']}.")
    if profile.get("iconStyle"):
        lines.append(f"- Иконки: {profile['iconStyle']}.")
    if voice.get("heading"):
        lines.append("- Голос заголовков (образцы): " + " | ".join(voice["heading"][:4]))
    if voice.get("eyebrow"):
        lines.append("- Надзаголовки/лейблы: " + " | ".join(voice["eyebrow"][:4]))
    if voice.get("cta"):
        lines.append("- CTA: " + " | ".join(voice["cta"][:4]))
    if voice.get("badge"):
        lines.append("- Бейджи/цены: " + " | ".join(voice["badge"][:4]))
    review = guide.get("review") or {}
    for key, label in (("tone", "Тон"), ("colorUsage", "Цвет"), ("typographyCharacter", "Типографика (ревью)"),
                       ("imageryStyle", "Имиджи")):
        if review.get(key):
            lines.append(f"- {label}: {review[key]}")
    for rule in (review.get("doRules") or [])[:6]:
        lines.append(f"- DO: {rule}")
    for rule in (review.get("dontRules") or [])[:6]:
        lines.append(f"- DON'T: {rule}")
    lines.append("- Пиши копирайт в том же голосе и регистре, что образцы; те же семейства шрифтов, "
                 "те же радиусы и тени; новые цвета не вводить.")
    return "\n".join(lines)


def ensure_style_guide(document: dict) -> dict:
    """Детерминированная часть Style Guide — присутствует в каждом документе."""
    foundations = document.get("foundations") or {}
    existing = document.get("styleGuide") if isinstance(document.get("styleGuide"), dict) else {}
    guide = {
        **existing,
        "tokens": semantic_tokens(foundations),
        "measured": measured_character(foundations),
        # Полные IR-токены и профиль атмосферы: порт ноды и промпт генератора
        # берут их отсюда, а не восстанавливают из плоской карты.
        "irTokens": ir_tokens(foundations),
        "profile": style_profile(document),
    }
    guide.setdefault("origin", "deterministic")
    document["styleGuide"] = guide
    return document


def _component_digest(document: dict, limit: int = 30) -> list[dict]:
    out = []
    for key, component in (document.get("components") or {}).items():
        if not isinstance(component, dict):
            continue
        out.append({
            "key": key,
            "name": component.get("name"),
            "category": component.get("category"),
            "variants": len(component.get("variants") or {}),
        })
        if len(out) >= limit:
            break
    return out


_REVIEW_TEXT_FIELDS = ("tone", "density", "cornerCharacter", "colorUsage",
                       "typographyCharacter", "imageryStyle")


def build_style_review_prompt(document: dict) -> list[dict]:
    """Сообщения для LLM-ревью. Дайджест компактный: полный IR не уходит."""
    guide = (document.get("styleGuide") or {})
    foundations = document.get("foundations") or {}
    typography = foundations.get("typography") or {}
    source_url = ""
    for ref in document.get("sourceRefs") or []:
        if isinstance(ref, dict) and ref.get("url"):
            source_url = str(ref["url"])
            break
    reference = real_reference_content(document)
    digest = {
        "url": source_url,
        "semanticTokens": guide.get("tokens") or semantic_tokens(foundations),
        "measuredCharacter": guide.get("measured") or measured_character(foundations),
        "styleProfile": guide.get("profile") or style_profile(document),
        "typography": {
            "families": typography.get("families") or [],
            "scale": typography.get("scale") or {},
            "weights": typography.get("weights") or [],
        },
        "components": _component_digest(document),
        # Копирайт сайта: по нему модель понимает, ЧТО это за сайт и для кого
        "siteCopy": {key: reference[key][:12]
                     for key in ("brand", "nav", "heading", "title", "cta", "category", "badge", "price", "question")
                     if reference.get(key)},
    }
    schema = {
        "siteBrief": {
            "summary": "2–3 sentences: what the site is, what it sells/does, for whom",
            "audience": "who uses it",
            "offer": "the core offer / value proposition in the site's own words",
            "tone": "voice of the copy (register, length, punctuation habits)",
            "sections": ["ordered list of page sections as the site has them"],
            "componentUsage": {"<componentKey>": "where on the site it is used and for what"},
        },
        "styleGuide": {
            "tone": "how the site feels in one sentence",
            "density": "spacing / whitespace character",
            "cornerCharacter": "how corners and shapes behave",
            "colorUsage": "how colors are applied (primary vs accent vs neutrals)",
            "typographyCharacter": "type pairing and hierarchy behaviour",
            "imageryStyle": "photography / illustration / icon character",
            "doRules": ["up to 10 short imperative rules for NEW components"],
            "dontRules": ["up to 10 short prohibitions"],
            "componentNotes": {"<componentKey>": "short styling note"},
        },
    }
    system = (
        "You are a senior design-system reviewer. Study the measured design language "
        "and the copy of an existing website and write (1) a short brief of the site "
        "itself and (2) the style guide that future generated components must follow "
        "so they blend into the site perfectly. Write the brief and rules in the same "
        "language as the site copy (Russian if the copy is Russian). "
        "Ground every statement in the supplied data; never invent brand values that "
        "are not present. Return ONE JSON object exactly matching the requested shape, no prose."
    )
    user = json.dumps({"task": "Write the style guide", "output": schema, "data": digest},
                      ensure_ascii=False)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _clean_text(value: Any, limit: int = 400) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate_review(parsed: Any, document: dict) -> dict:
    """Строгая валидация ответа модели: только описательные поля."""
    if not isinstance(parsed, dict):
        raise ValueError("Style review must be a JSON object")
    review = parsed.get("styleGuide") if isinstance(parsed.get("styleGuide"), dict) else parsed
    if not isinstance(review, dict):
        raise ValueError("styleGuide object is missing")
    out: dict[str, Any] = {}
    for field in _REVIEW_TEXT_FIELDS:
        text = _clean_text(review.get(field))
        if text:
            out[field] = text
    for field in ("doRules", "dontRules"):
        rules = review.get(field)
        if isinstance(rules, list):
            cleaned = [_clean_text(rule, 240) for rule in rules[:10]]
            out[field] = [rule for rule in cleaned if rule]
    notes = review.get("componentNotes")
    if isinstance(notes, dict):
        known = set((document.get("components") or {}).keys())
        out["componentNotes"] = {
            str(key): _clean_text(value, 240)
            for key, value in list(notes.items())[:20]
            if str(key) in known and _clean_text(value, 240)
        }
    if not out:
        raise ValueError("Style review contained no usable fields")
    return out


_BRIEF_TEXT_FIELDS = ("summary", "audience", "offer", "tone")


def validate_site_brief(parsed: Any, document: dict) -> dict:
    """Описание сайта из ответа модели: только текстовые поля, ограниченные по длине."""
    brief = parsed.get("siteBrief") if isinstance(parsed, dict) and isinstance(parsed.get("siteBrief"), dict) else None
    if not brief:
        return {}
    out: dict[str, Any] = {}
    for field in _BRIEF_TEXT_FIELDS:
        text = _clean_text(brief.get(field), 600)
        if text:
            out[field] = text
    sections = brief.get("sections")
    if isinstance(sections, list):
        out["sections"] = [s for s in (_clean_text(item, 120) for item in sections[:16]) if s]
    usage = brief.get("componentUsage")
    if isinstance(usage, dict):
        known = set((document.get("components") or {}).keys()) | set((document.get("reviewComponents") or {}).keys())
        out["componentUsage"] = {
            str(key): _clean_text(value, 240)
            for key, value in list(usage.items())[:40]
            if str(key) in known and _clean_text(value, 240)
        }
    return out


def site_brief(document: dict) -> dict:
    """Детерминированная часть описания сайта — из копирайта источника."""
    reference = real_reference_content(document)
    source_url = ""
    for ref in document.get("sourceRefs") or []:
        if isinstance(ref, dict) and ref.get("url"):
            source_url = str(ref["url"])
            break
    brief = {
        "url": source_url,
        "brand": _clean_text((reference.get("brand") or [""])[0], 80),
        "nav": [_clean_text(item, 40) for item in (reference.get("nav") or [])[:8] if _clean_text(item, 40)],
        "headings": [_clean_text(item, 120) for item in (reference.get("heading") or [])[:8] if _clean_text(item, 120)],
        "ctas": [_clean_text(item, 60) for item in (reference.get("cta") or [])[:6] if _clean_text(item, 60)],
    }
    return {key: value for key, value in brief.items() if value}


def apply_style_review(document: dict, raw_output: str, *, provider: str = "openai") -> dict:
    """Применить AI-ревью: document["styleGuide"]["review"] и document["siteBrief"]."""
    match = re.search(r"\{.*\}", str(raw_output or ""), re.S)
    if not match:
        raise ValueError("Style review response contains no JSON object")
    parsed = json.loads(match.group(0))
    review = validate_review(parsed, document)
    updated = copy.deepcopy(document)
    ensure_style_guide(updated)
    brief = validate_site_brief(parsed, updated)
    if brief:
        updated["siteBrief"] = {**site_brief(updated), **brief, "origin": "ai", "provider": str(provider)[:40]}
    updated["styleGuide"]["review"] = review
    updated["styleGuide"]["origin"] = "ai"
    updated["styleGuide"]["provider"] = str(provider)[:40]
    updated["status"] = "draft"
    from .document import content_hash
    updated["contentHash"] = content_hash(updated)
    return updated


def review_with_ai(document: dict, *, provider: str = "openai", reasoning_effort: str = "high", llm_module=None) -> dict:
    """Серверный путь (browser/dev): ревью через выбранную модель."""
    if reasoning_effort not in ("medium", "high", "max"):
        raise ValueError("reasoningEffort must be medium, high or max")
    if llm_module is None:
        import llm_client as llm_module
    messages = build_style_review_prompt(document)
    provider = provider if provider in ("openai", "astra", "codex", "claude") else "openai"
    model = "opus" if provider == "claude" else "gpt-6-astra" if provider == "astra" else "gpt-5.6-sol"
    raw = llm_module.chat(
        provider, messages, 0.0, timeout=180,
        role="mechanics", model=None if provider == "codex" else model, reasoning_effort=reasoning_effort,
    )
    return apply_style_review(document, raw, provider=provider)
