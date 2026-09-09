"""Deterministic, budgeted compiler from Design System to AI context.

Порядок строк — это приоритет при нехватке бюджета: сначала то, что задаёт
характер (душа, профиль атмосферы, декоративные сигнатуры, бриф сайта,
ревью стиль-гайда с DO/DON'T), затем числовые шкалы, затем реестр мастеров.
Реестр идёт двумя слоями: компактные сводки всех мастеров (анатомия,
типографика ролей, декор — ~200 токенов каждая) и, в strict-режиме или для
пиннутого референса, точный masterIr целиком.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from . import master_summary
from .identity import ensure_identity

STRICT_DEFAULT_BUDGET = 32_000
EXTEND_DEFAULT_BUDGET = 8_000
MIN_BUDGET = 320
MAX_BUDGET = 32_000
_PAGE_WORDS = re.compile(r"лендинг|landing|страниц|\bpage\b|сайт|\bsite\b|homepage|главн", re.I)
_SCALE_NAMED = ("display", "h1", "h2", "h3", "h4", "body", "caption", "small", "label", "lead")
_ARCHETYPE_SYNONYMS = {
    "pricing": ("тариф", "цен", "price", "pricing", "план"),
    "footer": ("футер", "подвал", "footer"),
    "header": ("хедер", "шапк", "навигац", "header", "navbar"),
    "hero": ("hero", "первый экран", "главный экран", "обложк"),
    "cta": ("cta", "призыв", "форма подписки", "заявк"),
    "trust": ("довер", "trust", "логотип", "клиент", "proof"),
    "how it works": ("как это работает", "how it works", "процесс", "шаг", "steps"),
    "services grid": ("услуг", "service", "сервис", "возможност", "features"),
    "gallery": ("галере", "gallery", "портфолио", "примеры работ", "showcase"),
    "faq": ("faq", "вопрос"),
    "testimonials": ("отзыв", "testimonial"),
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def default_budget(mode: str) -> int:
    """Бюджет контекста по режиму: strict должен вместить exact masters,
    extend/style-only — сводки всех мастеров, ревью и сигнатуры."""
    return STRICT_DEFAULT_BUDGET if str(mode or "strict") == "strict" else EXTEND_DEFAULT_BUDGET


def component_master_hash(component: dict) -> str:
    master = component.get("masterIr") if isinstance(component.get("masterIr"), dict) else component.get("templateIr")
    return "sha256:" + hashlib.sha256(_json(master or {}).encode("utf-8")).hexdigest()


_INSTANCE_KEYS = {"id", "sourceKey"}
_PLACEMENT_KEYS = {"x", "y"}
_CONTENT_KEYS = {
    "text", "title", "placeholder", "value", "label", "name", "alt",
    "ariaLabel", "href", "src", "imagePrompt",
}


def _shape_value(value: Any, *, in_props: bool = False) -> Any:
    if isinstance(value, dict):
        shaped = {}
        for key, child in value.items():
            if key in _INSTANCE_KEYS or key == "componentRef":
                continue
            if key == "sourceMeta" and isinstance(child, dict):
                source_meta = {meta_key: meta_value for meta_key, meta_value in child.items()
                               if meta_key != "componentRef"}
                if not source_meta or set(source_meta) == {"kind"}:
                    continue
                shaped[key] = _shape_value(source_meta)
                continue
            if key in _CONTENT_KEYS:
                shaped[key] = f"<{type(child).__name__}>"
            elif key == "frame" and isinstance(child, dict):
                # Положение экземпляра (x/y) — не форма: точная копия мастера,
                # поставленная в другое место (обёртка превью обнуляет x/y), остаётся exact.
                shaped[key] = _shape_value({k: v for k, v in child.items() if k not in _PLACEMENT_KEYS},
                                           in_props=in_props)
            elif in_props and not isinstance(child, (dict, list)):
                shaped[key] = f"<{type(child).__name__}>"
            else:
                shaped[key] = _shape_value(child, in_props=in_props or key == "props")
        return shaped
    if isinstance(value, list):
        return [_shape_value(item, in_props=in_props) for item in value]
    return f"<{type(value).__name__}>" if in_props else value


def component_shape_hash(node: dict) -> str:
    """Hash immutable visual/structural fields while allowing instance content."""
    return "sha256:" + hashlib.sha256(_json(_shape_value(node)).encode("utf-8")).hexdigest()


def component_handle(component: dict, system_ref: dict) -> dict:
    return {
        "systemId": system_ref.get("systemId"),
        "revision": system_ref.get("revision"),
        "componentKey": component.get("componentKey"),
        "masterHash": component_master_hash(component),
    }


def compact_variants(component: dict) -> list[dict]:
    """Prompt-safe variant choices without duplicating their master IR."""
    return [
        {
            "key": str(key),
            "label": str(variant.get("label") or key),
            "origin": str(variant.get("origin") or component.get("origin") or "observed"),
        }
        for key, variant in (component.get("variants") or {}).items()
        if isinstance(variant, dict)
    ]


def _has_masters(components) -> bool:
    return any(isinstance(c, dict) and isinstance(c.get("masterIr"), dict)
               for c in components or [])


# ---------- компактные шкалы ----------

def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _tidy(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 2)


def compact_steps(values, limit: int = 12) -> list:
    """Различимые значения шкалы по убыванию; при избытке — края и равномерная выборка середины."""
    distinct = sorted({number for number in (_as_number(v) for v in values or []) if number is not None}, reverse=True)
    if len(distinct) <= limit:
        return [_tidy(v) for v in distinct]
    edge = max(2, limit // 3)
    head, tail, middle = distinct[:edge], distinct[-edge:], distinct[edge:-edge]
    room = max(1, limit - 2 * edge)
    step = max(1, math.ceil(len(middle) / room))
    return [_tidy(v) for v in head + middle[::step][:room] + tail]


def compact_typography(typography: dict) -> dict:
    """Семейства, веса, именованные ступени и короткая выборка остальных кеглей —
    вместо 27 строк «size6…size27», которые только шумят."""
    scale = typography.get("scale") if isinstance(typography.get("scale"), dict) else {}
    named = {key: value for key, value in scale.items() if key in _SCALE_NAMED}
    other = [value for key, value in scale.items() if key not in _SCALE_NAMED]
    out: dict[str, Any] = {"families": typography.get("families") or [], "weights": typography.get("weights") or []}
    for role in ("display", "body"):
        if isinstance(typography.get(role), dict):
            out[role] = typography[role]
    if named:
        out["scale"] = named
    steps = compact_steps(other)
    if steps:
        out["otherSizes"] = steps
    return out


def compact_geometry(foundations: dict) -> dict:
    spacing = foundations.get("spacing")
    out: dict[str, Any] = {}
    if isinstance(spacing, dict):
        named = {key: value for key, value in spacing.items() if not re.match(r"^space\d+$", str(key))}
        steps = compact_steps([value for key, value in spacing.items() if re.match(r"^space\d+$", str(key))])
        if named:
            out["spacing"] = named
        if steps:
            out["spacingSteps"] = sorted(steps)
    elif spacing:
        out["spacing"] = spacing
    radii = foundations.get("radii") or []
    if radii:
        out["radii"] = sorted(compact_steps(radii, limit=14))
    shadows = [str(item) for item in (foundations.get("shadows") or []) if isinstance(item, str) and item.strip()]
    if shadows:
        out["shadowSamples"] = [item[:90] for item in shadows[:2]]
    return out


def compact_site_brief_levels(brief: dict) -> list[dict]:
    """Варианты брифа сайта от полного к минимальному: строка не режется посреди
    JSON, а ужимается по смыслу, пока не влезет в остаток бюджета."""
    full = {key: brief[key] for key in ("summary", "audience", "offer", "tone", "sections") if brief.get(key)}
    if not full:
        return []
    levels = [full]
    sections = full.get("sections")
    if isinstance(sections, list) and len(sections) > 6:
        levels.append({**full, "sections": sections[:6]})
    levels.append({key: value for key, value in full.items() if key != "sections"})
    levels.append({key: value for key, value in full.items() if key in ("summary", "tone")})
    summary = str(full.get("summary") or "")
    if summary:
        words = summary.split()
        clipped = " ".join(words[:40]) + ("…" if len(words) > 40 else "")
        levels.append({"summary": clipped})
    seen: list[dict] = []
    for level in levels:
        if level and level not in seen:
            seen.append(level)
    return seen


def _mentions(archetype: dict, brief_l: str) -> bool:
    name = str(archetype.get("name") or "").strip().lower()
    if not name:
        return False
    if name in brief_l:
        return True
    if any(synonym in brief_l for synonym in _ARCHETYPE_SYNONYMS.get(name, ())):
        return True
    structure = [str(item).lower() for item in archetype.get("structure") or []]
    return any(item and item in brief_l for item in structure)


def select_archetypes(archetypes: list, *, archetype_id: str = "", brief: str = "",
                      surface: str = "") -> tuple[list[dict], str]:
    """Явный id → упоминание в брифе → для страницы все секции → ничего.

    Раньше брался archetypes[0] — самый частый вид блока источника («Gallery»),
    и лендинг собирался вокруг галереи."""
    items = [item for item in archetypes or [] if isinstance(item, dict)]
    if archetype_id:
        exact = [item for item in items if str(item.get("id") or "") == archetype_id]
        if exact:
            return exact, "explicit"
    brief_l = str(brief or "").lower()
    mentioned = [item for item in items if _mentions(item, brief_l)]
    page_like = str(surface or "") in ("landing", "page", "website", "site") or bool(_PAGE_WORDS.search(brief_l))
    if mentioned and not (page_like and len(mentioned) > 3):
        return mentioned[:3], "brief"
    if page_like:
        return items, "page"
    return [], "none"


def compile_profile(context: dict, *, brief: str = "", archetype_id: str = "", token_budget: int = 1200,
                    pinned_keys=None, surface: str = "") -> dict:
    token_budget = max(MIN_BUDGET, min(int(token_budget or 1200), MAX_BUDGET))
    document = {
        "identity": context.get("identity") or {},
        "identityTests": context.get("identityTests") or [],
        "reconstruction": context.get("reconstruction") or {},
    }
    ensure_identity(document)
    identity = document["identity"]
    mode = str((context.get("constraints") or {}).get("usageMode") or "strict")
    foundations = context.get("foundations") or {}
    included: list[str] = []
    omitted: list[str] = []
    lines = ["DESIGN SYSTEM COMPILED PROFILE (source of truth):"]
    used = _tokens(lines[0])
    pinned_order = [str(key) for key in (pinned_keys or []) if key]
    pinned_set = set(pinned_order)
    components = [item for item in (context.get("components") or []) if isinstance(item, dict)]
    components.sort(key=lambda item: (
        str(item.get("componentKey") or "") not in pinned_set,
        pinned_order.index(str(item.get("componentKey") or ""))
        if str(item.get("componentKey") or "") in pinned_set else 0,
    ))

    def master_line(component: dict) -> tuple[str, str]:
        key = str(component.get("componentKey") or "")
        payload = {
            "componentRef": component_handle(component, context.get("systemRef") or {}),
            "masterIr": component["masterIr"],
            "variants": compact_variants(component),
        }
        return key, f"- Exact master {key}: {_json(payload)}"

    pinned_master_lines = [master_line(component) for component in components
                           if str(component.get("componentKey") or "") in pinned_set
                           and isinstance(component.get("masterIr"), dict)]
    pinned_reserve = sum(_tokens(line) for _, line in pinned_master_lines)

    def limit_now() -> int:
        return max(used, token_budget - pinned_reserve)

    def add(rule_id: str, line: str, *, required: bool = False, consume_reserve: int = 0) -> bool:
        nonlocal used, pinned_reserve
        if consume_reserve:
            pinned_reserve = max(0, pinned_reserve - consume_reserve)
        cost = _tokens(line)
        limit = limit_now()
        if used + cost <= limit:
            lines.append(line)
            included.append(rule_id)
            used += cost
            return True
        elif required and used < limit:
            # Hard cap is part of the provider contract. Keep the rule marker
            # and as much deterministic content as fits; never overrun budget.
            remaining = limit - used
            clipped = line[:max(1, remaining * 4)]
            lines.append(clipped)
            included.append(rule_id)
            used += _tokens(clipped)
            return True
        else:
            omitted.append(rule_id)
            return False

    def add_fitting(rule_id: str, prefix: str, levels: list[dict], *, required: bool = False) -> bool:
        """Первый уровень, который целиком влезает в остаток; иначе — обычная строка."""
        for level in levels:
            line = prefix + _json(level)
            if used + _tokens(line) <= limit_now():
                return add(rule_id, line, required=required)
        return add(rule_id, prefix + _json(levels[-1]), required=required) if levels else False

    ref = context.get("systemRef") or {}
    add("system.ref", f"- System: {ref.get('systemId')}@{ref.get('revision')} ({ref.get('contentHash') or 'draft'}); mode={mode}", required=True)
    policy = {
        "strict": "STRICT: registered tokens/components and hard identity rules are mandatory; do not invent replacements.",
        "extend": "EXTEND: preserve identity; provisional additions need an explicit reason.",
        "style-only": "STYLE ONLY: preserve foundations, soul, signatures and bans; registry is optional.",
    }.get(mode, "Preserve the compiled identity.")
    add("policy.usage-mode", f"- {policy}", required=True)
    soul = ((identity.get("soul") or {}).get("oneLine") or {}).get("value")
    if soul:
        add("identity.soul", f"- Soul: {soul}", required=True)
    exception = identity.get("signatureException")
    if isinstance(exception, dict) and exception.get("rule"):
        add("identity.signature-exception", f"- Signature exception: {exception['rule']}", required=True)
    for ban in sorted(identity.get("bans") or [], key=lambda x: (x.get("severity") != "hard", -float(x.get("confidence") or 0))):
        add(str(ban.get("id") or "identity.ban"), f"- {str(ban.get('severity') or 'soft').upper()} BAN: {ban.get('rule')}", required=ban.get("severity") == "hard")

    # Профиль атмосферы — короткий и обязательный: именно он, а не hex-карта,
    # заставляет новый компонент «звучать» как сайт (тема/углы/плотность/тип/голос).
    style_guide = context.get("styleGuide") or {}
    profile = style_guide.get("profile") or {}
    if profile:
        compact_profile = {key: profile[key] for key in
                           ("mode", "cornerCharacter", "density", "shadowUsage", "paletteCharacter", "accent",
                            "typographyCharacter", "labelStyle", "monoFamily", "imageDirection", "iconStyle")
                           if profile.get(key)}
        voice = profile.get("copyVoice") or {}
        if voice.get("heading") or voice.get("cta"):
            compact_profile["copyVoice"] = {key: (voice.get(key) or [])[:3] for key in ("heading", "eyebrow", "cta", "badge") if voice.get(key)}
        add("styleguide.profile", f"- Style profile (match this atmosphere): {_json(compact_profile)}", required=True)

    # Декоративные сигнатуры считаются из мастеров в контексте: моно-лейблы,
    # статус-пилюли, стрелки, разделители, однострочная форма, тонкие рамки.
    decor = master_summary.decorative_signatures(components)
    decor_ids: list[str] = []
    for sig_id, line in master_summary.signature_lines(decor):
        if add(sig_id, line, required=True):
            decor_ids.append(sig_id)
    for signature in sorted(identity.get("signatures") or [], key=lambda x: -float(x.get("confidence") or 0)):
        add(str(signature.get("id") or "identity.signature"), f"- Signature: {signature.get('rule')}")

    archetypes = identity.get("archetypes") or []
    selected_archetypes, archetype_reason = select_archetypes(
        archetypes, archetype_id=archetype_id, brief=brief, surface=surface)
    if archetype_reason == "page" and selected_archetypes:
        names = [str(item.get("name") or item.get("id")) for item in selected_archetypes]
        add("identity.archetypes",
            "- Page archetypes (section kinds observed in the source; compose the page from them, "
            "ordered as in the Site brief sections): " + ", ".join(names))
    else:
        for item in selected_archetypes:
            add(str(item.get("id")), f"- Archetype: {item.get('name')} · structure={_json(item.get('structure') or [])}")

    # Описание сайта (что это, для кого, оффер, секции) — обязательная строка:
    # генератор встраивает компонент в существующий сайт, а не рисует с нуля.
    site = context.get("siteBrief") or {}
    if site:
        levels = compact_site_brief_levels(site)
        if levels:
            add_fitting("site.brief", "- Site brief (embed target): ", levels, required=True)
        usage = site.get("componentUsage") or {}
        if usage:
            add("site.component-usage", f"- Where components live on the site: {_json(dict(list(usage.items())[:12]))}")

    # Ревью стиль-гайда и DO/DON'T — обязательны во всех режимах: это язык
    # дизайна словами, без него модель собирает «ещё один тёмный лендинг».
    review = style_guide.get("review") or {}
    if review:
        traits = {key: review[key] for key in
                  ("tone", "density", "cornerCharacter", "colorUsage", "typographyCharacter", "imageryStyle")
                  if review.get(key)}
        if traits:
            add("styleguide.review", f"- Design language: {_json(traits)}", required=True)
        for index, rule in enumerate((review.get("doRules") or [])[:12]):
            add(f"styleguide.do.{index}", f"- DO: {rule}", required=True)
        for index, rule in enumerate((review.get("dontRules") or [])[:12]):
            add(f"styleguide.dont.{index}", f"- DON'T: {rule}", required=True)
        notes = review.get("componentNotes") or {}
        if isinstance(notes, dict) and notes:
            add("styleguide.component-notes", f"- Component notes: {_json(dict(list(notes.items())[:10]))}")

    colors = ((foundations.get("colors") or {}).get("semantic") or {})
    typography = foundations.get("typography") or {}
    add("foundations.colors", f"- Semantic colors: {_json(colors)}", required=True)
    add("foundations.typography", f"- Type: {_json(compact_typography(typography))}", required=True)
    geometry = compact_geometry(foundations)
    if geometry:
        add("foundations.geometry", f"- Geometry: {_json(geometry)}")
    # Style Guide: семантические UI-токены и дизайн-язык сайта. Именно эта
    # секция заставляет НОВЫЕ компоненты стилистически вписываться в уже
    # работающий сайт, а не просто использовать те же hex-значения.
    ui_tokens = style_guide.get("tokens") or {}
    if ui_tokens:
        add("styleguide.tokens", f"- UI tokens (use these roles, shadcn-style): {_json(ui_tokens)}", required=True)
    measured_character = style_guide.get("measured") or {}
    if measured_character:
        add("styleguide.character", f"- Measured character: {_json(measured_character)}", required=True)
    coverage = identity.get("paletteCoverage") or {}
    roles = coverage.get("roles") or {}
    if roles:
        top_roles = dict(sorted(roles.items(), key=lambda pair: -float(pair[1] or 0))[:6])
        add("identity.palette-coverage", f"- Palette role coverage target: {_json(top_roles)}; method={coverage.get('method')}")

    component_handles = [component_handle(c, ref) for c in components if isinstance(c, dict)]
    included_master_keys: list[str] = []
    summarized_master_keys: list[str] = []
    if components:
        add(
            "registry.variant-selection-contract",
            "- COMPONENT VARIANTS: choose the variant whose label and meaning best fit the brief; do not default blindly when a semantically closer variant is available.",
            required=mode == "strict",
        )
        if mode == "strict":
            add(
                "registry.component-ref-contract",
                "- STRICT COMPONENT CONTRACT: copy geometry, styles, responsive overrides and hierarchy from an exact master below. Content values/instance ids may change. Every copied master root MUST include its componentRef in sourceMeta.componentRef; missing, stale, invented or visually mutated refs are blocking errors.",
                required=True,
            )
        # Слой 1: сводки всех мастеров — анатомия, роли, декор. Дёшево и
        # достаточно, чтобы новые секции наследовали характер, а не общий шаблон.
        with_masters = [c for c in components if isinstance(c.get("masterIr"), dict)]
        if with_masters:
            add("registry.summary-contract",
                "- MASTER ANATOMY: each master below is described by root surface, child roles with font/size/weight/color "
                "samples and decorative traits. Reuse these anatomies and traits for matching roles (badges, steps, "
                "stats, forms, links) instead of generic cards; copy character, not the sample content.",
                required=True)
        for component in with_masters:
            key = str(component.get("componentKey") or "")
            if add(f"registry.summary.{key}", master_summary.summary_line(component)):
                summarized_master_keys.append(key)
        # Слой 2: точный masterIr — strict копирует его как строительный блок,
        # в остальных режимах он нужен только для пиннутого референса.
        exact_targets = with_masters if mode == "strict" else [
            c for c in with_masters if str(c.get("componentKey") or "") in pinned_set]
        for component in exact_targets:
            key, line = master_line(component)
            reserved_cost = _tokens(line) if key in pinned_set else 0
            if add(f"registry.master.{key}", line, consume_reserve=reserved_cost):
                included_master_keys.append(key)
        compact = [{
            "key": c.get("componentKey"),
            "category": c.get("category"),
            "props": list((c.get("propsSchema") or {}).keys()),
            "componentRef": component_handle(c, ref),
            "shapeHash": component_shape_hash(((c.get("masterIr") or {}).get("tree") or [{}])[0]),
            "variants": compact_variants(c),
        } for c in components if str(c.get("componentKey") or "") in included_master_keys]
        if compact or mode == "strict":
            add("registry.components", f"- Masters available in this prompt: {_json(compact)}", required=mode == "strict")

    tests = context.get("identityTests") or []
    if tests:
        add("identity.test-plan", "- Application will independently validate: " + ", ".join(str(t.get("id")) for t in tests), required=True)
    fixture = context.get("fixture")
    if fixture:
        add("fixture.selected", f"- Mock fixture ({fixture.get('profile')}): {_json(fixture.get('data'))[:500]}")

    canonical = _json({"lines": lines, "included": included, "omitted": omitted, "budget": token_budget})
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "promptBlock": "\n".join(lines),
        "compiledContextHash": digest,
        "includedRuleIds": included,
        "omittedRuleIds": omitted,
        "estimatedTokens": used,
        "tokenBudget": token_budget,
        "archetypeId": selected_archetypes[0].get("id") if len(selected_archetypes) == 1 else None,
        "archetypeIds": [str(item.get("id")) for item in selected_archetypes],
        "archetypeSelection": archetype_reason,
        "decorSignatureIds": decor_ids,
        "validationPlan": [str(t.get("id")) for t in tests],
        "componentHandles": component_handles,
        "includedMasterKeys": included_master_keys,
        "summarizedMasterKeys": summarized_master_keys,
        "pinnedMasterKeys": [key for key in pinned_order if key in included_master_keys],
        # Пустой реестр в strict — не провал бюджета: копировать нечего,
        # обязательными остаются foundations/токены. Провал — только когда
        # мастера СУЩЕСТВУЮТ, но ни один не поместился в контекст.
        "strictReady": mode != "strict" or not _has_masters(components) or (
            all(key in included_master_keys for key in pinned_order) if pinned_order else bool(included_master_keys)
        ),
    }
