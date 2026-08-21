"""Context Resolver + валидация генерации (ТЗ §20, §22, §25.2, §17)."""
from __future__ import annotations

import re
from typing import Any

MAX_COMPONENTS_IN_CONTEXT = 12

_RELEVANT_WORDS = {
    "button": ("кнопк", "cta", "button", "действ", "добавить", "купить", "подписа"),
    "actions": ("кнопк", "cta", "действ", "форма", "отправить"),
    "forms": ("форм", "поле", "ввод", "input", "логин", "регистрац"),
    "content": ("карточк", "card", "товар", "продукт", "контент", "список", "профил"),
    "typography": ("заголов", "текст", "типограф", "heading", "абзац"),
    "media": ("изображ", "картин", "фото", "галере", "image"),
    "navigation": ("меню", "навигац", "шапк", "header", "хедер", "таб", "ссылк"),
    "surfaces": ("панел", "модал", "блок", "карточк", "section"),
    "feedback": ("уведомлен", "статус", "сообщен", "алерт", "toast"),
}


def resolve_context(document: dict, brief: str, *, usage_mode: str = "strict",
                    fixture_profile: str = "typical") -> dict:
    """Компактный resolved context (§20): без сериализации полного registry в промпт."""
    components = [c for c in (document.get("components") or {}).values() if isinstance(c, dict)]
    brief_l = str(brief or "").lower()

    def relevance(comp: dict) -> int:
        category = str(comp.get("category") or "")
        name_l = str(comp.get("name") or "").lower()
        key_l = str(comp.get("componentKey") or "").lower()
        score = 0
        for word in _RELEVANT_WORDS.get(category, ()):
            if word in brief_l:
                score += 2
        for token in re.findall(r"[a-zа-яё]{4,}", brief_l):
            if token in name_l or token in key_l:
                score += 3
        if comp.get("origin") == "observed":
            score += 1
        return score

    ranked = sorted(components, key=relevance, reverse=True)[:MAX_COMPONENTS_IN_CONTEXT]
    selected_keys = {c.get("componentKey") or "" for c in ranked}

    # замыкание зависимостей
    by_key = {c.get("componentKey") or k: c for k, c in (document.get("components") or {}).items() if isinstance(c, dict)}
    closure = list(ranked)
    seen = set(selected_keys)
    for comp in ranked:
        for dep in comp.get("dependencies") or []:
            if dep in by_key and dep not in seen:
                seen.add(dep)
                closure.append(by_key[dep])

    fixture = None
    for fix in ((document.get("mockData") or {}).get("fixtures") or {}).values():
        if isinstance(fix, dict) and fix.get("profile") == fixture_profile:
            fixture = fix
            break

    return {
        "systemRef": {"systemId": document.get("id"), "revision": document.get("revision"), "contentHash": document.get("contentHash")},
        "foundations": document.get("foundations") or {},
        "components": closure,
        "patterns": list((document.get("patterns") or {}).keys()),
        "fixture": fixture,
        "constraints": {"usageMode": usage_mode},
    }


def compact_prompt_block(context: dict) -> str:
    """Компактное текстовое представление для системного промпта (не весь документ)."""
    foundations = context.get("foundations") or {}
    colors = (foundations.get("colors") or {}).get("semantic") or {}
    typo = foundations.get("typography") or {}
    spacing = foundations.get("spacing") or {}
    radii = foundations.get("radii") or []
    mode = (context.get("constraints") or {}).get("usageMode") or "strict"

    lines = [
        "DESIGN SYSTEM CONTEXT (use it as the source of truth):",
        f"- Semantic colors: {json_compact(colors)}",
        f"- Font families: {', '.join(typo.get('families') or []) or 'as in tokens'}; weights {typo.get('weights')}",
        f"- Spacing scale: {json_compact(spacing)}; radii: {radii}",
        f"- Usage mode: {mode}",
    ]
    comps = context.get("components") or []
    if comps:
        lines.append(f"- Registered components ({len(comps)}):")
        for comp in comps[:MAX_COMPONENTS_IN_CONTEXT]:
            props = ", ".join((comp.get("propsSchema") or {}).keys()) or "-"
            lines.append(f"  * {comp.get('componentKey')} [{comp.get('category')}] props: {props}")
    if mode == "strict":
        lines.append("- STRICT: compose ONLY from the registered components above; new colors/fonts/radii are FORBIDDEN; adapt content through props.")
    elif mode == "extend":
        lines.append("- EXTEND: prefer registered components; a missing one may be created locally (mark it provisional); new tokens need a reason.")
    else:
        lines.append("- STYLE ONLY: follow foundations (colors/type/spacing/radii); component registry is optional.")
    fixture = context.get("fixture")
    if fixture:
        lines.append(f"- Mock fixture ({fixture.get('profile')}): {json_compact(fixture.get('data'))[:600]}")
    return "\n".join(lines)


def json_compact(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def validate_generation(ir: dict, context: dict) -> dict:
    """Пост-валидация результата (§25.2). Возвращает {errors, warnings, componentRefs}."""
    mode = (context.get("constraints") or {}).get("usageMode") or "strict"
    errors: list[dict] = []
    warnings: list[dict] = []

    foundations = context.get("foundations") or {}
    semantic = (foundations.get("colors") or {}).get("semantic") or {}
    primitives = (foundations.get("colors") or {}).get("primitives") or {}
    allowed_colors = {str(v).lower() for v in {**semantic, **primitives}.values() if isinstance(v, str)}
    families = {f.lower() for f in (foundations.get("typography") or {}).get("families") or []}
    radii = {round(float(r)) for r in (foundations.get("radii") or [])}
    registered = {str(c.get("componentKey")) for c in context.get("components") or []}

    def walk(node: dict, section: str):
        style = node.get("style") or {}
        if isinstance(style, dict):
            for color_key in ("color", "background", "borderColor"):
                value = style.get(color_key)
                if isinstance(value, str) and value.startswith("#") and len(value) >= 7:
                    hexv = value.lower()[:7]
                    if allowed_colors and hexv not in allowed_colors and hexv != "#ffffff" and hexv != "#000000":
                        (errors if mode == "strict" else warnings).append(
                            {"code": "off-system-color", "message": f"Цвет {value} вне палитры системы ({section})"})
            fam = str(style.get("fontFamily") or "").split(",")[0].strip().strip("'\"").lower()
            if families and fam and fam not in families and fam not in ("inter", "system-ui", "sans-serif", "serif", "monospace"):
                (errors if mode == "strict" else warnings).append(
                    {"code": "off-system-font", "message": f"Шрифт «{fam}» не входит в систему"})
            radius = style.get("borderRadius")
            if isinstance(radius, (int, float)) and radii and round(float(radius)) not in radii:
                warnings.append({"code": "off-system-radius", "message": f"Радиус {radius} вне шкалы системы"})
        if mode == "strict" and node.get("type") in ("card", "button") and node.get("sourceMeta", {}).get("componentRole"):
            pass  # строгая проверка компонентов — по componentRef ниже
        for child in node.get("children") or []:
            walk(child, section)

    for i, section in enumerate(ir.get("tree") or []):
        walk(section, str(section.get("id") or i))

    refs = []
    for section in ir.get("tree") or []:
        stack = [section]
        while stack:
            node = stack.pop()
            ref = ((node.get("sourceMeta") or {}).get("componentRef")) if isinstance(node.get("sourceMeta"), dict) else None
            if ref:
                refs.append(ref)
                if mode == "strict" and str(ref.get("componentKey")) not in registered:
                    errors.append({"code": "unregistered-component", "message": f"Компонент {ref.get('componentKey')} не зарегистрирован в системе (Strict)"})
            stack.extend(node.get("children") or [])

    if mode == "strict" and not refs and (context.get("components") or []):
        warnings.append({"code": "no-component-refs", "message": "Результат не ссылается на компоненты системы — композиция не из registry"})
    return {"errors": errors[:20], "warnings": warnings[:20], "componentRefs": refs}
