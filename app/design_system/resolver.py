"""Context Resolver + валидация генерации (ТЗ §20, §22, §25.2, §17)."""
from __future__ import annotations

import re
from typing import Any

from .compiler import compile_profile, component_master_hash, component_shape_hash
from .identity import ensure_identity, evaluate_identity

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

_COMPONENT_INTENT_WORDS = {
    "service-card": ("service card", "service-card", "карточк", "услуг", "listing card"),
    "button": ("button", "кнопк", "cta", "действи"),
    "category-tile": ("category tile", "category-tile", "категор"),
    "listing-section-header": ("listing header", "заголовок списка", "заголовок секции"),
    "section-header": ("section header", "заголовок раздела"),
    "trust-card": ("trust card", "довер", "безопасн"),
    "process-step": ("process step", "шаг", "этап"),
    "footer-navigation": ("footer", "футер", "подвал"),
    "mobile-navigation-item": ("mobile navigation", "мобильн", "нижняя навигац"),
    "header-actions": ("header actions", "действия шапки", "шапк"),
}

_MASTER_CONTENT_KEYS = {"text", "title", "label", "value"}
_SEMANTIC_SYNONYMS = {
    "pricing": ("тариф", "цена", "стоим", "price", "$", "month", "месяц", "₽", "руб"),
    "card": ("карточ", "card", "tile", "panel", "панел", "плит"),
}


def _master_content(component: dict) -> str:
    values: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif key in _MASTER_CONTENT_KEYS and isinstance(value, (str, int, float)):
            values.append(str(value))

    visit(component.get("masterIr") or {})
    return " ".join(values).lower()


def _semantic_terms(text: str) -> set[str]:
    lowered = str(text or "").lower()
    terms = set(re.findall(r"[a-zа-яё]+|\d+(?:[.,]\d+)?|[$€₽]", lowered))
    for canonical, synonyms in _SEMANTIC_SYNONYMS.items():
        if any(synonym in lowered for synonym in synonyms):
            terms.add(canonical)
    return terms


def component_relevance(component: dict, brief: str) -> int:
    """Rank observed masters by explicit intent before compact prompt packing."""
    brief_l = str(brief or "").lower()
    category = str(component.get("category") or "")
    name_l = str(component.get("name") or "").lower()
    key_l = str(component.get("componentKey") or "").lower()
    score = 0
    for phrase in _COMPONENT_INTENT_WORDS.get(key_l, ()):
        if phrase in brief_l:
            score += 6
    for word in _RELEVANT_WORDS.get(category, ()):
        if word in brief_l:
            score += 2
    for token in re.findall(r"[a-zа-яё]{4,}", brief_l):
        if token in name_l or token in key_l:
            score += 3
    component_terms = _semantic_terms(" ".join((name_l, key_l, category, _master_content(component))))
    brief_terms = _semantic_terms(brief_l)
    for token in brief_terms & component_terms:
        score += 3 if token in _SEMANTIC_SYNONYMS else 2
    if component.get("origin") == "observed":
        score += 1
    return score


def primary_component_for_brief(context: dict, brief: str, *, pinned_keys=None) -> dict | None:
    """Return an unambiguous exact-master target for strict generation recovery."""
    pinned = [str(key) for key in (pinned_keys or []) if key]
    components = [item for item in context.get("components") or [] if isinstance(item, dict)]
    for key in pinned:
        match = next((item for item in components if str(item.get("componentKey") or "") == key), None)
        if match is not None:
            return match
    ranked = sorted(
        components,
        key=lambda item: component_relevance(item, brief),
        reverse=True,
    )
    if not ranked or component_relevance(ranked[0], brief) < 3:
        return None
    return ranked[0]


def _release_component(component: dict) -> bool:
    origin = str(component.get("origin") or "")
    master = component.get("masterIr")
    if not isinstance(master, dict) or component.get("confirmed") is not True:
        return False
    if origin == "observed":
        return component.get("status") == "verified"
    return origin == "user"


def fixture_for_component(document: dict, component: dict | None, profile: str) -> dict:
    selected_profile = str(profile or "source")
    if selected_profile == "source":
        return {"id": "source", "schemaId": "", "profile": "source", "data": {}}
    fixtures = ((document.get("mockData") or {}).get("fixtures") or {})
    if isinstance(component, dict):
        for binding in component.get("mockBindings") or []:
            if not isinstance(binding, dict) or not binding.get("schemaId"):
                continue
            fixture = fixtures.get(f"{binding['schemaId']}:{selected_profile}")
            if isinstance(fixture, dict):
                return fixture
    for fixture in fixtures.values():
        if isinstance(fixture, dict) and fixture.get("profile") == selected_profile:
            return fixture
    return {"id": f"preview:{selected_profile}", "schemaId": "", "profile": selected_profile, "data": {}}


def resolve_context(document: dict, brief: str, *, usage_mode: str = "strict",
                    fixture_profile: str = "typical", component_key: str = "",
                    pinned_keys=None) -> dict:
    """Компактный resolved context (§20): без сериализации полного registry в промпт."""
    ensure_identity(document)
    components = [
        c for c in (document.get("components") or {}).values()
        if isinstance(c, dict) and _release_component(c)
    ]
    requested_pins = [str(key) for key in (pinned_keys or []) if key]
    if component_key and component_key not in requested_pins:
        requested_pins.insert(0, component_key)
    pin_order = {key: index for index, key in enumerate(requested_pins)}
    pinned = sorted(
        [comp for comp in components if str(comp.get("componentKey") or "") in pin_order],
        key=lambda comp: pin_order[str(comp.get("componentKey") or "")],
    )
    remaining = sorted(
        [comp for comp in components if str(comp.get("componentKey") or "") not in pin_order],
        key=lambda comp: component_relevance(comp, brief), reverse=True,
    )
    ranked = (pinned + remaining)[:max(MAX_COMPONENTS_IN_CONTEXT, len(pinned))]
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

    fixture = fixture_for_component(document, ranked[0] if ranked else None, fixture_profile)

    return {
        "systemRef": {"systemId": document.get("id"), "revision": document.get("revision"), "contentHash": document.get("contentHash")},
        "foundations": document.get("foundations") or {},
        "styleGuide": document.get("styleGuide") or {},
        "siteBrief": document.get("siteBrief") or {},
        "components": closure,
        "patterns": list((document.get("patterns") or {}).keys()),
        "identity": document.get("identity") or {},
        "identityTests": document.get("identityTests") or [],
        "reconstruction": document.get("reconstruction") or {},
        "fixture": fixture,
        "constraints": {"usageMode": usage_mode},
        "pinnedKeys": [str(comp.get("componentKey") or "") for comp in pinned],
    }


def compiled_context(context: dict, *, brief: str = "", archetype_id: str = "",
                     token_budget: int = 1200, pinned_keys=None, surface: str = "") -> dict:
    return compile_profile(context, brief=brief, archetype_id=archetype_id,
                           token_budget=token_budget,
                           pinned_keys=pinned_keys if pinned_keys is not None else context.get("pinnedKeys"),
                           surface=surface)


def compact_prompt_block(context: dict) -> str:
    """Compatibility wrapper around the deterministic budgeted compiler."""
    return compiled_context(context)["promptBlock"]


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
    # Пилюля — это «радиус больше половины высоты», а не число из шкалы:
    # 999/1000 при наблюдённых 50/99 и radius-button=999 не считаются отступлением.
    button_radius = ((context.get("styleGuide") or {}).get("tokens") or {}).get("radius-button")
    pill_scale = any(r >= 50 for r in radii) or (
        isinstance(button_radius, (int, float)) and not isinstance(button_radius, bool) and button_radius >= 50)
    registered = {
        str(c.get("componentKey")): c
        for c in context.get("components") or []
        if isinstance(c, dict) and c.get("componentKey")
    }
    system_ref = context.get("systemRef") or {}

    def walk(node: dict, section: str):
        # Точная копия мастера (sourceMeta.componentRef): её измеренные цвета/шрифты —
        # это цвета самой системы, проверять их против палитры нельзя; целостность
        # копии контролирует проверка masterHash/shape ниже.
        source_meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
        if isinstance(source_meta.get("componentRef"), dict):
            return
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
            if (isinstance(radius, (int, float)) and radii and round(float(radius)) not in radii
                    and not (pill_scale and float(radius) >= 50)):
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
                if mode == "strict":
                    key = str(ref.get("componentKey") or "") if isinstance(ref, dict) else ""
                    component = registered.get(key)
                    if component is None:
                        errors.append({"code": "unregistered-component", "message": f"Компонент {key or 'без ключа'} не зарегистрирован в системе (Strict)"})
                    else:
                        ref_hash = str(ref.get("masterHash") or "") if isinstance(ref, dict) else ""
                        matched_master = component.get("masterIr") if isinstance(component.get("masterIr"), dict) else None
                        expected_hash = component_master_hash(component)
                        if ref_hash != expected_hash:
                            matched_master = None
                            for variant in (component.get("variants") or {}).values():
                                if (not isinstance(variant, dict)
                                        or variant.get("origin") != "user"
                                        or not isinstance(variant.get("masterIr"), dict)):
                                    continue
                                variant_hash = component_master_hash({"masterIr": variant["masterIr"]})
                                if ref_hash == variant_hash and str(variant.get("masterHash") or "") == variant_hash:
                                    matched_master = variant["masterIr"]
                                    expected_hash = variant_hash
                                    break
                        expected = {
                            "systemId": str(system_ref.get("systemId") or ""),
                            "revision": int(system_ref.get("revision") or 0),
                            "masterHash": expected_hash,
                        }
                        try:
                            actual_revision = int(ref.get("revision") or 0) if isinstance(ref, dict) else 0
                        except (TypeError, ValueError):
                            actual_revision = -1
                        if (str(ref.get("systemId") or "") != expected["systemId"]
                                or actual_revision != expected["revision"]
                                or ref_hash != expected["masterHash"]
                                or matched_master is None):
                            errors.append({
                                "code": "stale-component-ref",
                                "message": f"Компонент {key}: componentRef не совпадает с закреплённым exact master",
                            })
                        else:
                            master_tree = (matched_master.get("tree") or [])
                            master_root = master_tree[0] if master_tree and isinstance(master_tree[0], dict) else {}
                            if component_shape_hash(node) != component_shape_hash(master_root):
                                errors.append({
                                    "code": "mutated-exact-master",
                                    "message": f"Компонент {key}: изменены geometry/styles/hierarchy exact master",
                                })
            stack.extend(node.get("children") or [])

    if mode == "strict" and not refs and (context.get("components") or []):
        errors.append({"code": "no-component-refs", "message": "Strict-результат не ссылается на exact masters системы"})
    if mode == "strict" and (context.get("components") or []):
        def validate_coverage(node: dict, *, top_level: bool = False) -> None:
            if not isinstance(node, dict):
                return
            source_meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
            if source_meta.get("componentRef"):
                # The referenced subtree is checked against its exact master
                # above, so every descendant is covered by the same instance.
                return
            children = node.get("children") if isinstance(node.get("children"), list) else []
            neutral_wrapper = (
                top_level
                and node.get("type") == "source-block"
                and node.get("variant") == "component-master"
                and not (node.get("props") or {})
                and not (node.get("style") or {})
                and bool(children)
            )
            if neutral_wrapper:
                for child in children:
                    validate_coverage(child)
                return
            errors.append({
                "code": "unregistered-visual-node",
                "message": f"Strict: узел {node.get('type') or 'unknown'} не покрыт exact master",
            })

        for section in ir.get("tree") or []:
            validate_coverage(section, top_level=True)
    identity_report = evaluate_identity(
        ir, context.get("identity") or {}, context.get("identityTests") or [], foundations)
    for failure in identity_report["hardFailures"]:
        errors.append({"code": failure["id"], "message": failure["message"]})
    for failure in identity_report["softFailures"]:
        warnings.append({"code": failure["id"], "message": failure["message"]})
    return {"errors": errors[:20], "warnings": warnings[:20], "componentRefs": refs,
            "identity": identity_report}
