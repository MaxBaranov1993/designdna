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
    border = _hex(semantic.get("border")) or "#e5e7eb"
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


def ensure_style_guide(document: dict) -> dict:
    """Детерминированная часть Style Guide — присутствует в каждом документе."""
    foundations = document.get("foundations") or {}
    existing = document.get("styleGuide") if isinstance(document.get("styleGuide"), dict) else {}
    guide = {
        **existing,
        "tokens": semantic_tokens(foundations),
        "measured": measured_character(foundations),
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
    digest = {
        "url": source_url,
        "semanticTokens": guide.get("tokens") or semantic_tokens(foundations),
        "measuredCharacter": guide.get("measured") or measured_character(foundations),
        "typography": {
            "families": typography.get("families") or [],
            "scale": typography.get("scale") or {},
            "weights": typography.get("weights") or [],
        },
        "components": _component_digest(document),
    }
    schema = {
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
        "of an existing website and write the style guide that future generated "
        "components must follow so they blend into the site perfectly. "
        "Ground every statement in the supplied measured data; never invent brand "
        "values that are not present. Return ONE JSON object exactly matching the "
        "requested shape, no prose."
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


def apply_style_review(document: dict, raw_output: str, *, provider: str = "openai") -> dict:
    """Применить AI-ревью. Меняется только document["styleGuide"]["review"]."""
    match = re.search(r"\{.*\}", str(raw_output or ""), re.S)
    if not match:
        raise ValueError("Style review response contains no JSON object")
    review = validate_review(json.loads(match.group(0)), document)
    updated = copy.deepcopy(document)
    ensure_style_guide(updated)
    updated["styleGuide"]["review"] = review
    updated["styleGuide"]["origin"] = "ai"
    updated["styleGuide"]["provider"] = str(provider)[:40]
    updated["status"] = "draft"
    from .document import content_hash
    updated["contentHash"] = content_hash(updated)
    return updated


def review_with_ai(document: dict, *, reasoning_effort: str = "high", llm_module=None) -> dict:
    """Серверный путь (browser/dev): ревью через Sol, как organizer."""
    if reasoning_effort not in ("medium", "high", "max"):
        raise ValueError("reasoningEffort must be medium, high or max")
    if llm_module is None:
        import llm_client as llm_module
    messages = build_style_review_prompt(document)
    raw = llm_module.chat(
        "openai", messages, 0.0, timeout=180,
        role="mechanics", model="gpt-5.6-sol", reasoning_effort=reasoning_effort,
    )
    return apply_style_review(document, raw, provider="openai")
