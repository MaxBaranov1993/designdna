"""AI-режиссёр видео-таймлайна: промпт -> план -> детерминированные операции.

Дисциплина та же, что у остальных AI-поверхностей продукта: модель лишь
предлагает план (шаблон, пресеты, слои, тайминги), все кейфреймы генерируются
детерминированным кодом, а результат оформляется как обратимый
TimelineChangeSet (preview → atomic apply → undo).

Три пути:
1. ``plan_from_llm`` — LLM предлагает JSON-план (роль ``timeline_director``);
2. ``plan_from_prompt`` — детерминированный разбор ключевых слов и шаблонов;
   работает всегда, включая полное отсутствие подключённых аккаунтов;
3. сценарный таймлайн (story) с запросом про взаимодействие уходит в
   ``video_story.direct_story``; чисто моушн-запросы по story-таймлайну идут
   коротким путём (один вызов модели, без vision-анализа страниц).
"""
from __future__ import annotations

import json
import re

import llm_client as llm
from ir.timeline import MAX_PROMPT_CHARS, build_change_set
from timeline_choreography import (
    MAX_LAYERS_PER_STEP,  # noqa: F401 — реэкспорт для тестов и совместимости
    MAX_STEPS,
    TEMPLATE_NAMES,
    describe_vocabulary,
    is_motion_request,
    layer_roles,
    normalize_steps,
    plan_operations,
    template_steps,
)

SYSTEM_PROMPT = (
    "You are the motion director of a product/presentation video built from a real web page. "
    "The page is split into layers (sections and their child elements with roles). Your job is to choreograph "
    "smooth, premium motion in the spirit of high-end product films: one clear focus per beat, calm camera, "
    "expo/quart easing, short staggers, nothing jittery. Reply with STRICT JSON only: "
    '{"template":"<template or null>","steps":[{"preset":"<preset>","layers":["<layer id>", ...] | "*" | "role:button" | "section:2",'
    '"start":0.0,"duration":0.15,"staggerMs":90,"travel":120}],"summary":"one short sentence"}. '
    + describe_vocabulary() + " "
    "Rules: start and duration are fractions of the video length (0..1). A template is expanded first, then your steps "
    "are layered on top as accents (max 6 accents with a template, max 12 steps without). "
    "Reveals last 0.45–1.6 s with staggerMs 60–160 between siblings; camera moves span at least half of the video; "
    "every block that fades in stays visible at the end; use dim only around a clear focus block and never on the hero. "
    "Elements appear in reading order: heading → text → media → button. Prefer camera-push or camera-pan over "
    "moving many sections. If the user asks for a product/launch feel use product-showcase; slides or narrative → "
    "presentation; a walkthrough of features → feature-tour; minimal → clean-reveal; cinematic → cinematic-camera."
)


def _duration(timeline: dict) -> int:
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    return max(250, int(composition.get("duration") or 6000))


def _section_layers(timeline: dict) -> list[dict]:
    """Секционные слои (целые блоки), по порядку документа."""
    layers = timeline.get("layers") if isinstance(timeline.get("layers"), list) else []
    out = []
    for layer in layers:
        if not isinstance(layer, dict) or layer.get("type") != "component":
            continue
        # слой секции: его суффикс совпадает с именем группы без префикса "grp-"
        parent = layer.get("parent")
        if parent and str(layer.get("id", "")).endswith(str(parent)[4:]):
            out.append(layer)
    return out or [layer for layer in layers if isinstance(layer, dict) and layer.get("type") == "component"]


def _match_layers(timeline: dict, query: str) -> list[str]:
    query_norm = str(query or "").strip().lower()
    layers = timeline.get("layers") if isinstance(timeline.get("layers"), list) else []
    if query_norm in {"*", "", "все", "all"}:
        return [layer["id"] for layer in _section_layers(timeline)]
    roles = layer_roles(timeline)
    if query_norm.startswith("role:"):
        wanted = query_norm[5:].strip()
        return [item["id"] for item in roles if item["role"] == wanted]
    if query_norm.startswith("section:"):
        try:
            index = int(query_norm[8:].strip())
        except ValueError:
            return []
        sections = [item["id"] for item in roles if item["role"] == "section"]
        return [sections[index]] if 0 <= index < len(sections) else []
    matched = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        haystack = " ".join(str(layer.get(key) or "") for key in ("name", "ref", "id")).lower()
        if query_norm and query_norm in haystack:
            matched.append(str(layer["id"]))
    if matched:
        return matched
    # маркеры типов: кнопка/ктА, картинка, заголовок
    aliases = {
        "кнопк": "button", "cta": "button", "button": "button",
        "картин": "image", "image": "image", "изображ": "image",
        "заголов": "heading", "heading": "heading", "текст": "text", "text": "text",
    }
    for key, role in aliases.items():
        if key in query_norm:
            matched = [item["id"] for item in roles if item["role"] == role]
            if matched:
                return matched
    return []


def _step_operations(timeline: dict, step: dict) -> list[dict]:
    """Совместимая обёртка над хореографией (тесты и старые вызовы)."""
    from timeline_choreography import step_operations
    return step_operations(timeline, step, _match_layers)


def template_for_prompt(prompt: str) -> str | None:
    text = str(prompt or "").lower()
    if any(word in text for word in ("cinemat", "кинемат", "атмосфер", "epic", "эпич")):
        return "cinematic-camera"
    if any(word in text for word in ("presentation", "презентац", "slide", "слайд", "pitch", "питч", "рассказ", "story")):
        return "presentation"
    if any(word in text for word in ("tour", "тур", "feature", "фич", "функци", "обзор", "walkthrough")):
        return "feature-tour"
    if any(word in text for word in ("minimal", "минимал", "clean", "чист", "спокойн", "calm", "quiet")):
        return "clean-reveal"
    if any(word in text for word in ("product", "продукт", "showcase", "launch", "запуск", "промо", "promo", "реклам")):
        return "product-showcase"
    return None


def plan_from_prompt(timeline: dict, prompt: str, page_heights: dict[str, float] | None = None) -> list[dict]:
    """Детерминированный план по ключевым словам и шаблонам (работает без LLM)."""
    text = str(prompt or "").lower()
    sections = _section_layers(timeline)
    section_ids = [str(layer["id"]) for layer in sections]
    steps: list[dict] = []

    def add(preset: str, layers: list[str], start: float, share: float, stagger: int = 0) -> None:
        if layers:
            steps.append({"preset": preset, "layers": layers,
                          "start": start, "duration": share, "staggerMs": stagger})

    has_intro = any(word in text for word in ("интро", "появлен", "появ", "выход", "intro", "fade", "reveal"))
    has_zoom = any(word in text for word in ("наезд", "зум", "приближ", "zoom", "крупн"))
    has_pulse = any(word in text for word in ("пульс", "акцент", "кнопк", "cta", "pulse"))
    has_pan = any(word in text for word in ("провлёт", "пролет", "панорам", "скролл", "листание", "pan"))
    has_stagger = any(word in text for word in ("каскад", "по очереди", "очеред", "последовательн", "stagger"))
    template = template_for_prompt(text)

    if template and not (has_intro or has_zoom or has_pulse or has_pan or has_stagger):
        return template_steps(timeline, template, prompt=text, page_heights=page_heights)
    if not (has_intro or has_zoom or has_pulse or has_pan or has_stagger):
        # разумный монтаж по умолчанию: продуктовый шаблон
        return template_steps(timeline, "product-showcase", prompt=text, page_heights=page_heights)

    if template:
        steps.extend(template_steps(timeline, template, prompt=text, page_heights=page_heights))
    elif has_intro or has_stagger:
        add("fade-in-up", section_ids, 0.0, 0.25, stagger=200 if has_stagger else 120)
    if has_pan:
        add("camera-pan", ["camera"], 0.2, 0.6)
    if has_zoom and section_ids:
        target = section_ids[min(1, len(section_ids) - 1)]
        add("zoom-spotlight", [target], 0.45, 0.35)
    if has_pulse:
        buttons = _match_layers(timeline, "role:button")
        add("cta-pulse", buttons or (section_ids[-1:] if section_ids else []), 0.75, 0.2)
    # гарантируем финал: последний блок всегда появляется, если план пустоват
    if not steps and section_ids:
        add("fade-in-up", section_ids, 0.0, 0.3, stagger=150)
    return normalize_steps(timeline, steps)


def director_context(timeline: dict, prompt: str) -> str:
    """Компактный контекст для модели: длительность, секции и роли элементов."""
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    roles = layer_roles(timeline)
    sections: list[dict] = []
    for item in roles:
        if item["role"] == "section":
            sections.append({"index": item["section"], "id": item["id"], "name": item["name"], "children": []})
    by_index = {section["index"]: section for section in sections}
    for item in roles:
        if item["role"] != "section" and item["section"] in by_index:
            children = by_index[item["section"]]["children"]
            if len(children) < 16:
                children.append({"id": item["id"], "role": item["role"], "name": item["name"][:48]})
    return (
        f"## User request\n{prompt.strip()}\n\n"
        f"## Video\nduration: {composition.get('duration')}ms, fps: {composition.get('fps')}, "
        f"frame: {composition.get('width')}x{composition.get('height')}\n"
        f"## Layers (document order; use exact ids)\n{json.dumps(sections[:24], ensure_ascii=False)}\n"
    )


def plan_from_llm(timeline: dict, prompt: str, provider: str | None = None, effort: str = "medium", model: str | None = None,
                  page_heights: dict[str, float] | None = None) -> list[dict]:
    """LLM-план (роль timeline_director). Бросает исключение при недоступности."""
    raw = llm.chat(provider, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": director_context(timeline, prompt)},
    ], 0.4, timeout=120, role="timeline_director", reasoning_effort=effort, model=model)
    data = json.loads(llm.extract_json(raw))
    if not isinstance(data, dict):
        raise ValueError("LLM returned an invalid plan")
    steps: list[dict] = []
    template = data.get("template")
    accents = [step for step in (data.get("steps") if isinstance(data.get("steps"), list) else []) if isinstance(step, dict)]
    if template not in TEMPLATE_NAMES:
        # The prompt names a choreography (presentation, cinematic, showcase…) but
        # the model answered with loose accents only: keep the requested
        # baseline (camera pan across a long page included) and layer accents on top.
        implied = template_for_prompt(prompt)
        wants_camera = bool(re.search(r"camera|pan\b|pans\b|камер|панорам|пролёт|пролет", prompt, re.IGNORECASE))
        has_camera = any(str(step.get("preset") or "").startswith("camera-") for step in accents)
        if implied and (wants_camera and not has_camera or len(accents) < 3):
            template = implied
    if template in TEMPLATE_NAMES:
        steps.extend(template_steps(timeline, str(template), prompt=prompt, page_heights=page_heights))
    limit = 6 if template in TEMPLATE_NAMES else MAX_STEPS
    steps.extend(accents[:limit])
    if not steps:
        raise ValueError("LLM returned an empty plan")
    return steps


def direct(timeline: dict, prompt: str, allow_llm: bool | None = None, *, provider: str | None = None, effort: str = "medium", require_llm: bool = False, conversation: list[dict] | None = None, model: str | None = None, visual_context: list | None = None, page_heights: dict[str, float] | None = None) -> tuple[dict, dict, dict]:
    """Промпт -> применённый таймлайн + change-set + мета (атомарно, обратимо).

    Мета возвращает ``planSource`` ("llm" | "deterministic") и ``warning`` —
    его видно в UI, когда LLM-провайдер недоступен и сработал фолбэк на
    детерминированный разбор промпта.
    """
    from config import FEATURE_FLAGS
    text = str(prompt or "")
    if not text.strip():
        raise ValueError("empty prompt")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"prompt exceeds {MAX_PROMPT_CHARS} characters — shorten it to the key editing techniques")
    if timeline.get("story") and allow_llm is not False and not is_motion_request(text, conversation):
        from video_story import direct_story
        return direct_story(timeline, text, provider or "codex", effort, conversation=conversation, model=model, visual_context=visual_context, page_heights=page_heights)
    use_llm = require_llm or (FEATURE_FLAGS.is_enabled("aiDirector") if allow_llm is None else allow_llm)
    steps: list[dict] | None = None
    plan_source = "deterministic"
    warning: str | None = None
    if use_llm:
        try:
            context_text = ("Previous conversation (context only):\n" + json.dumps(conversation, ensure_ascii=False) + "\nCurrent request:\n" + text) if conversation else text
            steps = plan_from_llm(timeline, context_text, provider=provider, effort=effort, model=model, page_heights=page_heights)
            plan_source = "llm"
        except Exception as exc:  # noqa: BLE001 — фолбэк не должен терять функцию
            if require_llm:
                raise ValueError("The selected AI account did not prepare timeline changes. Check Agents → Connections. " + str(exc)[:200]) from exc
            steps = None  # деградация на детерминированный разбор без потери функции
            warning = (
                "LLM provider unavailable (" + (str(exc) or "no response")[:200]
                + ") — used a deterministic keyword-based plan")
    if not steps:
        if require_llm:
            raise ValueError("AI returned an empty timeline plan. Refine the prompt and run again.")
        steps = plan_from_prompt(timeline, text, page_heights)
    steps = normalize_steps(timeline, steps)
    from timeline_choreography import extend_for_long_page
    planned_on, lengthen = extend_for_long_page(timeline, steps, page_heights)
    operations = lengthen + plan_operations(planned_on, steps, _match_layers)
    if not operations:
        raise ValueError("could not build any operations from the prompt")
    change_set = build_change_set(timeline, text[:500], operations, actor="timeline-director")
    from ir.timeline import apply_change_set
    applied = apply_change_set(timeline, change_set)
    meta = {"planSource": plan_source, "warning": warning, "steps": len(steps)}
    return applied, change_set, meta
