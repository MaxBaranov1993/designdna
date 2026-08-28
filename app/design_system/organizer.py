"""Semantic catalog organization for Source-derived Design Systems.

The organizer is intentionally metadata-only. Exact ``masterIr`` values,
variant identities, fidelity evidence and component pools are never rewritten
by an AI result.
"""
from __future__ import annotations

import copy
import json
from typing import Any


CATALOG_VERSION = "semantic-catalog/1.0"
SECTION_SPECS = (
    ("header-navigation", "Header & navigation", "Global navigation, search and page chrome"),
    ("actions", "Actions", "Buttons, links and compact interactive controls"),
    ("forms", "Forms", "Inputs, search controls and form groups"),
    ("cards", "Cards", "Product, service, editorial and support cards"),
    ("content", "Content", "Headings, tiles and reusable content blocks"),
    ("disclosure", "Disclosure", "Accordions and expandable controls"),
    ("patterns", "Patterns", "Larger reusable page compositions"),
    ("footer", "Footer", "Footer navigation and footer-specific controls"),
    ("other", "Other", "Unclassified observed components"),
)
SECTION_KEYS = {key for key, _, _ in SECTION_SPECS}

ROLE_SECTION = {
    "header-actions": "header-navigation",
    "navigation-group": "header-navigation",
    "mobile-navigation-item": "header-navigation",
    "listing-section-header": "header-navigation",
    "button": "actions",
    "text-link": "actions",
    "filter-bar": "actions",
    "search-field": "forms",
    "service-card": "cards",
    "trust-card": "cards",
    "article-card": "cards",
    "support-card": "cards",
    "content-card": "cards",
    "hero-slide": "content",
    "category-tile": "content",
    "section-header": "content",
    "process-step": "content",
    "accordion-item": "disclosure",
    "article-section": "patterns",
    "footer-navigation": "footer",
}
CATEGORY_SECTION = {
    "navigation": "header-navigation",
    "actions": "actions",
    "forms": "forms",
    "surfaces": "cards",
    "content": "content",
    "disclosure": "disclosure",
    "patterns": "patterns",
}

# Уровни атомарного дизайна — принятый способ читать UI kit: неделимые
# элементы, их сочетания и собранные из них блоки. Без этой оси каталог
# выглядит плоской свалкой карточек, по которой непонятно, с чего начинать.
ATOMIC_LEVELS = (
    ("atoms", "Атомы", "Неделимые элементы: кнопки, поля, метки, иконки"),
    ("molecules", "Молекулы", "Сочетания атомов: поле поиска, пункт меню, заголовок секции"),
    ("organisms", "Организмы", "Собранные блоки: карточки, навигация, футер, секции"),
)
ROLE_ATOMIC = {
    "button": "atoms",
    "text-link": "atoms",
    "form-field": "atoms",
    "badge": "atoms",
    "icon": "atoms",
    "avatar": "atoms",
    "list-item": "atoms",
    "search-field": "molecules",
    "form-group": "molecules",
    "section-header": "molecules",
    "listing-section-header": "molecules",
    "mobile-navigation-item": "molecules",
    "process-step": "molecules",
    "accordion-item": "molecules",
    "category-tile": "molecules",
    "filter-bar": "molecules",
    "header-actions": "molecules",
    "navigation-group": "organisms",
    "footer-navigation": "organisms",
    "service-card": "organisms",
    "article-card": "organisms",
    "trust-card": "organisms",
    "support-card": "organisms",
    "content-card": "organisms",
    "nested-surface": "organisms",
    "hero-slide": "organisms",
    "article-section": "organisms",
}
CATEGORY_ATOMIC = {
    "actions": "atoms",
    "forms": "molecules",
    "content": "molecules",
    "disclosure": "molecules",
    "navigation": "organisms",
    "surfaces": "organisms",
    "patterns": "organisms",
}


def atomic_level(component: dict) -> str:
    """Уровень компонента: атом, молекула или организм.

    Роль важнее категории: категория говорит, куда положить в каталоге, а
    уровень — насколько элемент сложен. Неизвестное считаем организмом:
    лучше показать как сборный блок, чем выдать за примитив.
    """
    role = str(component.get("canonicalRole") or "").lower()
    if role in ROLE_ATOMIC:
        return ROLE_ATOMIC[role]
    category = str(component.get("category") or "").lower()
    return CATEGORY_ATOMIC.get(category, "organisms")


def _catalog_components(document: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for pool_name in ("components", "reviewComponents"):
        pool = document.get(pool_name)
        if not isinstance(pool, dict):
            continue
        for key, component in pool.items():
            if isinstance(component, dict) and str(key) not in result:
                result[str(key)] = component
    # Legacy drafts kept exact observed review masters in suggestions.
    suggestions = document.get("suggestions")
    if isinstance(suggestions, dict):
        for key, component in suggestions.items():
            if (isinstance(component, dict) and component.get("origin") == "observed"
                    and str(key) not in result):
                result[str(key)] = component
    return result


def _fallback_section(component: dict) -> str:
    role = str(component.get("canonicalRole") or component.get("componentKey") or "").lower()
    if role in ROLE_SECTION:
        return ROLE_SECTION[role]
    category = str(component.get("category") or "").lower()
    return CATEGORY_SECTION.get(category, "other")


def _quality_action(component: dict) -> tuple[str, list[str]]:
    if component.get("status") == "verified":
        return "keep", []
    review = component.get("review") if isinstance(component.get("review"), dict) else {}
    fidelity = component.get("fidelity") if isinstance(component.get("fidelity"), dict) else {}
    reasons = [str(value) for value in (review.get("reasons") or fidelity.get("reasons") or []) if value]
    return "review-source-fidelity", reasons or ["Exact master has not passed the fidelity gate"]


def deterministic_catalog(document: dict) -> dict:
    components = _catalog_components(document)
    meta: dict[str, dict] = {}
    section_members: dict[str, list[str]] = {key: [] for key, _, _ in SECTION_SPECS}
    for key, component in components.items():
        section = _fallback_section(component)
        quality_action, reasons = _quality_action(component)
        meta[key] = {
            "role": str(component.get("canonicalRole") or key),
            "family": str(component.get("canonicalRole") or key),
            "label": str(component.get("name") or key.replace("-", " ").title()),
            "sectionKey": section,
            "confidence": 1.0,
            "rationale": "Deterministic Source semantics",
            "qualityAction": quality_action,
            "qualityReasons": reasons,
            "atomicLevel": atomic_level(component),
            "variantCount": len(component.get("variants") or {}),
            "stateCount": len(component.get("states") or {}),
        }
        section_members[section].append(key)
    sections = []
    for section_key, label, description in SECTION_SPECS:
        keys = sorted(section_members[section_key], key=lambda item: (meta[item]["label"].lower(), item))
        if keys:
            sections.append({"key": section_key, "label": label, "description": description,
                             "componentKeys": keys})
    # Ось атомарного дизайна рядом с секциями: секция отвечает «где искать»,
    # уровень — «с чего начинать читать кит».
    levels = []
    for level_key, label, description in ATOMIC_LEVELS:
        keys = sorted((key for key, item in meta.items() if item["atomicLevel"] == level_key),
                      key=lambda item: (meta[item]["label"].lower(), item))
        if keys:
            levels.append({"key": level_key, "label": label, "description": description,
                           "componentKeys": keys})
    return {
        "version": CATALOG_VERSION,
        "organizer": {"kind": "deterministic", "model": None, "reasoningEffort": None},
        "sections": sections,
        "levels": levels,
        "componentMeta": meta,
        "rules": {
            "variantsStayWithFamily": True,
            "exactMastersImmutable": True,
            "fidelityGateAuthoritative": True,
        },
    }


def _descriptor(key: str, component: dict, baseline: dict) -> dict:
    variants = []
    for variant_key, variant in (component.get("variants") or {}).items():
        variant = variant if isinstance(variant, dict) else {}
        variants.append({
            "key": str(variant_key),
            "label": str(variant.get("label") or variant_key),
            "semanticKey": str(variant.get("semanticKey") or ""),
            "observedCount": int(variant.get("observedCount") or 1),
        })
    return {
        "key": key,
        "name": str(component.get("name") or key),
        "canonicalRole": str(component.get("canonicalRole") or ""),
        "sourceLabel": str(component.get("sourceLabel") or ""),
        "category": str(component.get("category") or ""),
        "sourceBlocks": list((component.get("provenance") or {}).get("sourceBlocks") or []),
        "accessibilityRole": str((component.get("accessibility") or {}).get("role") or ""),
        "status": str(component.get("status") or "draft"),
        "variants": variants,
        "baselineSectionKey": baseline["componentMeta"][key]["sectionKey"],
    }


def _validate_ai_plan(raw_plan: Any, document: dict, baseline: dict, effort: str) -> dict:
    if not isinstance(raw_plan, dict) or not isinstance(raw_plan.get("components"), list):
        raise ValueError("AI organizer returned no components array")
    components = _catalog_components(document)
    proposed: dict[str, dict] = {}
    for item in raw_plan["components"]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if key not in components or key in proposed:
            continue
        section = str(item.get("sectionKey") or "")
        if section not in SECTION_KEYS:
            section = baseline["componentMeta"][key]["sectionKey"]
        confidence = item.get("confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5
        proposed[key] = {
            "sectionKey": section,
            "label": str(item.get("label") or components[key].get("name") or key)[:80],
            "family": str(item.get("family") or components[key].get("canonicalRole") or key)[:80],
            "role": str(item.get("role") or components[key].get("canonicalRole") or key)[:80],
            "confidence": confidence,
            "rationale": str(item.get("rationale") or "AI semantic classification")[:240],
            "order": int(item.get("order") or 0),
        }

    # Missing or malformed AI entries fall back deterministically. AI never
    # gets permission to drop a Source master from the catalog.
    result = copy.deepcopy(baseline)
    for key, base_meta in result["componentMeta"].items():
        if key in proposed:
            quality = {name: base_meta[name] for name in ("qualityAction", "qualityReasons")}
            result["componentMeta"][key] = {**base_meta, **proposed[key], **quality}
    members: dict[str, list[str]] = {key: [] for key, _, _ in SECTION_SPECS}
    for key, item in result["componentMeta"].items():
        members[item["sectionKey"]].append(key)
    result["sections"] = []
    for section_key, label, description in SECTION_SPECS:
        keys = sorted(members[section_key], key=lambda key: (
            int(result["componentMeta"][key].get("order") or 0),
            result["componentMeta"][key]["label"].lower(), key,
        ))
        if keys:
            result["sections"].append({"key": section_key, "label": label,
                                       "description": description, "componentKeys": keys})
    # Уровень атомарного дизайна модель не переопределяет: это измеренное
    # свойство компонента, а не вопрос вкуса — она решает только раскладку
    # по секциям и подписи. Пересобираем ось из baseline.
    level_members: dict[str, list[str]] = {key: [] for key, _, _ in ATOMIC_LEVELS}
    for key, item in result["componentMeta"].items():
        level = str(baseline["componentMeta"].get(key, {}).get("atomicLevel") or "organisms")
        item["atomicLevel"] = level
        level_members.setdefault(level, []).append(key)
    result["levels"] = [
        {"key": level_key, "label": label, "description": description,
         "componentKeys": sorted(level_members[level_key],
                                 key=lambda key: (result["componentMeta"][key]["label"].lower(), key))}
        for level_key, label, description in ATOMIC_LEVELS if level_members.get(level_key)
    ]
    result["organizer"] = {"kind": "ai", "model": "gpt-5.6-sol", "reasoningEffort": effort}
    return result


def organize_with_ai(document: dict, *, reasoning_effort: str = "high", llm_module=None) -> dict:
    if reasoning_effort not in ("medium", "high", "max"):
        raise ValueError("reasoningEffort must be medium, high or max")
    if llm_module is None:
        import llm_client as llm_module
    baseline = deterministic_catalog(document)
    descriptors = [
        _descriptor(key, component, baseline)
        for key, component in _catalog_components(document).items()
    ]
    prompt = {
        "task": "Organize exact Source-derived UI masters into a coherent design-system catalog",
        "allowedSectionKeys": [key for key, _, _ in SECTION_SPECS],
        "rules": [
            "Return every input key exactly once; never invent or drop keys.",
            "Put the complete header/navigation family together in header-navigation.",
            "Keep all button treatments in the single button family; variants already belong to their family.",
            "Put product, service, editorial and support cards together in cards.",
            "Do not claim visual correctness and do not alter master IR, variants, status or fidelity.",
            "Use order to place global/page structure before primitives, then cards and content.",
        ],
        "output": {"components": [{"key": "input key", "sectionKey": "allowed key",
                                     "family": "canonical family", "role": "semantic role",
                                     "label": "short catalog label", "order": 10,
                                     "confidence": 0.0, "rationale": "short reason"}]},
        "components": descriptors,
    }
    raw = llm_module.chat(
        "openai",
        [
            {"role": "system", "content": (
                "You are a design-system information architect. Return JSON only. "
                "Organize observed components; never redesign, merge masters, or override fidelity evidence."
            )},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        0.0,
        timeout=180,
        role="mechanics",
        model="gpt-5.6-sol",
        reasoning_effort=reasoning_effort,
    )
    parsed = json.loads(llm_module.extract_json(raw))
    return _validate_ai_plan(parsed, document, baseline, reasoning_effort)


def apply_catalog(document: dict, catalog: dict) -> dict:
    updated = copy.deepcopy(document)
    updated["catalog"] = copy.deepcopy(catalog)
    updated["status"] = "draft"
    return updated
