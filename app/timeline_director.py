"""AI-режиссёр видео-таймлайна: промпт -> план -> детерминированные операции.

Дисциплина та же, что у остальных AI-поверхностей продукта: модель лишь
предлагает план (пресеты, слои, тайминги), все кейфреймы генерируются
детерминированным кодом, а результат оформляется как обратимый
TimelineChangeSet (preview → atomic apply → undo).

Два уровня:
1. ``plan_from_llm`` — LLM предлагает JSON-план (роль ``timeline_director``,
   включается флагом DESIGNAI_FLAG_AIDIRECTOR=1);
2. ``plan_from_prompt`` — детерминированный разбор ключевых слов; работает
   всегда, включая полное отсутствие подключённых аккаунтов.
"""
from __future__ import annotations

import json
import re

import llm_client as llm
from ir.timeline import (
    PRESET_NAMES,
    build_change_set,
    preset_operations,
)

SYSTEM_PROMPT = (
    "Ты — режиссёр монтажа продуктового ролика. По промпту пользователя составь план "
    "анимации слоёв таймлайна. Ответ — СТРОГО JSON без пояснений: "
    '{"steps":[{"preset":"<preset>","layers":"<слово-маркер слоя или *>", '
    '"start":0.0,"duration":0.2,"staggerMs":0}]. '
    "preset один из: " + ", ".join(PRESET_NAMES) + ". "
    "start и duration — доли длительности ролика (0..1). "
    "layers — подстрока имени слоя ('*', 'все' — все секции). "
    "Не более 6 шагов. Тайминги не должны перекрываться бессмысленно."
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
    return out or [layer for layer in layers if isinstance(layer, dict)]


def _match_layers(timeline: dict, query: str) -> list[str]:
    query_norm = str(query or "").strip().lower()
    layers = timeline.get("layers") if isinstance(timeline.get("layers"), list) else []
    if query_norm in {"*", "", "все", "all"}:
        return [layer["id"] for layer in _section_layers(timeline)]
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
        "заголов": "heading", "текст": "text",
    }
    for key, marker in aliases.items():
        if key in query_norm:
            for layer in layers:
                if isinstance(layer, dict) and marker in str(layer.get("ref") or "").lower() + str(layer.get("name") or "").lower():
                    matched.append(str(layer["id"]))
            if matched:
                return matched
    return []


def _step_operations(timeline: dict, step: dict) -> list[dict]:
    preset = str(step.get("preset") or "")
    if preset not in PRESET_NAMES:
        raise ValueError(f"неизвестный пресет в плане: {preset!r}")
    duration = _duration(timeline)
    raw_layers = step.get("layers")
    if isinstance(raw_layers, list):
        # план уже вернул конкретные id (plan_from_prompt) — проверяем их наличие
        known = {str(layer.get("id")) for layer in (timeline.get("layers") or []) if isinstance(layer, dict)}
        layer_ids = [str(item) for item in raw_layers if str(item) in known]
    else:
        layer_ids = _match_layers(timeline, str(raw_layers or "*"))
    if not layer_ids:
        raise ValueError("план не ссылается ни на один слой")
    start = max(0.0, min(1.0, float(step.get("start") or 0)))
    share = max(0.02, min(1.0, float(step.get("duration") or 0.2)))
    params = {
        "start": int(start * duration),
        "duration": max(150, int(share * duration)),
        "staggerMs": max(0, min(2000, int(step.get("staggerMs") or 0))),
    }
    return preset_operations(preset, layer_ids, params)


def plan_from_prompt(timeline: dict, prompt: str) -> list[dict]:
    """Детерминированный план по ключевым словам (работает без LLM)."""
    text = str(prompt or "").lower()
    sections = _section_layers(timeline)
    section_ids = [str(layer["id"]) for layer in sections]
    steps: list[dict] = []

    def add(preset: str, layers: list[str], start: float, share: float, stagger: int = 0) -> None:
        if layers:
            steps.append({"preset": preset, "layers": layers,
                          "start": start, "duration": share, "staggerMs": stagger})

    has_intro = any(word in text for word in ("интро", "появлен", "появ", "выход", "intro", "fade"))
    has_zoom = any(word in text for word in ("наезд", "зум", "приближ", "камер", "zoom", "крупн"))
    has_pulse = any(word in text for word in ("пульс", "акцент", "кнопк", "cta", "pulse"))
    has_pan = any(word in text for word in ("провлёт", "пролет", "панорам", "скролл", "листание", "pan"))
    has_stagger = any(word in text for word in ("каскад", "по очереди", "очеред", "последовательн", "stagger"))

    if not (has_intro or has_zoom or has_pulse or has_pan or has_stagger):
        # разумный монтаж по умолчанию: каскадное появление + наезд на финал
        add("fade-in-up", section_ids, 0.0, 0.3, stagger=180)
        if section_ids:
            add("zoom-spotlight", [section_ids[-1]], 0.55, 0.4)
        return steps

    if has_intro or has_stagger:
        add("fade-in-up", section_ids, 0.0, 0.25, stagger=200 if has_stagger else 120)
    if has_pan:
        add("pan-down", section_ids[:1], 0.2, 0.5)
    if has_zoom and section_ids:
        target = section_ids[min(1, len(section_ids) - 1)]
        add("zoom-spotlight", [target], 0.45, 0.35)
    if has_pulse:
        buttons = _match_layers(timeline, "button") or _match_layers(timeline, "кнопк")
        add("cta-pulse", buttons or (section_ids[-1:] if section_ids else []), 0.75, 0.2)
    # гарантируем финал: последний блок всегда появляется, если план пустоват
    if not steps and section_ids:
        add("fade-in-up", section_ids, 0.0, 0.3, stagger=150)
    return steps


def plan_from_llm(timeline: dict, prompt: str) -> list[dict]:
    """LLM-план (роль timeline_director). Бросает исключение при недоступности."""
    layers = timeline.get("layers") if isinstance(timeline.get("layers"), list) else []
    layer_names = [str(layer.get("name") or layer.get("id")) for layer in layers if isinstance(layer, dict)][:40]
    composition = timeline.get("composition") if isinstance(timeline.get("composition"), dict) else {}
    user = (
        f"## Промпт пользователя\n{prompt.strip()}\n\n"
        f"## Таймлайн\nduration: {composition.get('duration')}ms, fps: {composition.get('fps')}\n"
        f"Слои: {json.dumps(layer_names, ensure_ascii=False)}\n"
    )
    raw = llm.chat(None, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ], 0.4, timeout=60, role="timeline_director")
    data = json.loads(llm.extract_json(raw))
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not steps:
        raise ValueError("LLM вернула пустой план")
    return [step for step in steps[:6] if isinstance(step, dict)]


def direct(timeline: dict, prompt: str, allow_llm: bool | None = None) -> tuple[dict, dict]:
    """Промпт -> применённый таймлайн + change-set (атомарно, обратимо)."""
    from config import FEATURE_FLAGS
    if not str(prompt or "").strip():
        raise ValueError("пустой промпт")
    use_llm = FEATURE_FLAGS.is_enabled("aiDirector") if allow_llm is None else allow_llm
    steps: list[dict] | None = None
    if use_llm:
        try:
            steps = plan_from_llm(timeline, prompt)
        except Exception:
            steps = None  # деградация на детерминированный разбор без потери функции
    if not steps:
        steps = plan_from_prompt(timeline, prompt)
    operations: list[dict] = []
    for step in steps:
        operations.extend(_step_operations(timeline, step))
    if not operations:
        raise ValueError("не удалось собрать ни одной операции по промпту")
    change_set = build_change_set(timeline, str(prompt)[:500], operations, actor="timeline-director")
    from ir.timeline import apply_change_set
    applied = apply_change_set(timeline, change_set)
    return applied, change_set
