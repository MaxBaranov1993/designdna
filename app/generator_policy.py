"""Versioned, provider-neutral design knowledge and deterministic acceptance helpers.

This module selects a small applicable context. It does not install UI kits, invent
IR node types, call a model, mutate a design system, or certify unseen behavior.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

POLICY_VERSION = "generator-design/1.0"
KNOWLEDGE_PATH = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent) / "prompts" / "generator-policy.json"
SURFACES = ("auto", "landing", "catalog", "detail", "checkout", "dashboard", "form",
            "editor", "ai-workspace", "article", "feed", "component")
STYLE_IDS = ("auto", "minimal", "enterprise", "marketplace", "editorial", "swiss",
             "product-led", "luxury", "organic", "playful", "brutal", "industrial",
             "soft-pastel", "bento", "glass", "immersive", "retro")
_cache: tuple[tuple[int, int], dict] | None = None


def knowledge() -> dict:
    global _cache
    stat = KNOWLEDGE_PATH.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _cache is None or _cache[0] != stamp:
        value = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
        if value.get("version") != POLICY_VERSION:
            raise ValueError("Unsupported generator policy version")
        _cache = stamp, value
    return _cache[1]


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def fingerprint() -> str:
    return digest(knowledge())


def surface_for(brief: str, requested: str = "auto", ir: dict | None = None) -> str:
    if requested not in SURFACES:
        raise ValueError("Неизвестный тип экрана")
    if requested != "auto":
        return requested
    text = brief.casefold()
    # Explicit surfaces win over incidental domain words (a property search landing).
    for surface, pattern in (
        ("landing", r"лендинг|landing|промо.?страниц|hero"),
        ("component", r"компонент|component|(?:^|\s)(?:кнопк|button|badge|tooltip|modal)\w*"),
        ("ai-workspace", r"ai.workspace|ai.assistant|чат.?бот|ai.?чат|ии.?ассистент|ai.?ассистент"),
        ("editor", r"редактор|canvas|editor\b"),
        ("checkout", r"checkout|бронирован|оформлени[ея] заказ|оплат|booking|запис[ьи] на"),
        ("form", r"форм[аыуе]|настройк|settings|реквизит|уведомлен|form\b|login|регистрац"),
        ("dashboard", r"dashboard|дашборд|кабинет|аналитик|таблиц|table\b"),
        ("article", r"стать[яию]|журнал|article|editorial|блог|blog"),
        ("detail", r"карточк[аиу]\s+(?:товар|объект|услуг|квартир)|product.detail|detail.page"),
        ("catalog", r"каталог|поиск|выдач|marketplace|catalog|search|маркетплейс"),
        ("feed", r"лент[ауы]|feed\b|социальн"),
    ):
        if re.search(pattern, text):
            return surface
    if ir:
        tree = ir.get("tree") or []
        if len(tree) == 1 and tree[0].get("type") == "source-block":
            return "component"
    return "landing"


def mode_for(ds: dict | None, locked: bool = False) -> str:
    if ds is not None:
        if not ds.get("systemId"):
            raise ValueError("Выбранная дизайн-система не содержит systemId")
        mode = ds.get("usageMode") or "strict"
        if mode not in {"strict", "extend", "style-only"}:
            raise ValueError("Неизвестный режим дизайн-системы")
        return mode
    return "tokens-only" if locked else "freeform"


def context(brief: str, *, surface: str = "auto", style: str = "auto",
            ds: dict | None = None, locked: bool = False, edit: bool = False) -> dict:
    if style not in STYLE_IDS:
        raise ValueError("Неизвестное стилевое направление")
    resolved = surface_for(brief, surface)
    mode = mode_for(ds, locked)
    return {"version": POLICY_VERSION, "policyHash": fingerprint(), "surface": resolved,
            "surfaceLabel": knowledge()["patterns"][resolved]["label"],
            "requestedMode": mode, "effectiveMode": mode, "style": style,
            "edit": edit, "foundationsLocked": mode != "freeform",
            "requiredStates": knowledge()["patterns"][resolved]["states"],
            "checks": {"keyboard": "unknown", "screenReader": "unknown",
                       "performance": "unknown", "visual": "unknown"}}


def prompt(ctx: dict) -> str:
    data = knowledge()
    mode = ctx["requestedMode"]
    blocks = [f"## Generator policy {POLICY_VERSION}", data["core"],
              data["modes"].get(mode, data["modes"]["tokens-only"])]
    if ctx.get("edit"):
        blocks.append("EDIT SCOPE: reproduce the reference and apply only the requested change. "
                      "Do not add sections, recopy facts or change direction.")
    else:
        pattern = data["patterns"][ctx["surface"]]
        blocks.append("## Applicable surface recipe\n" + json.dumps(pattern, ensure_ascii=False))
    if ctx["style"] != "auto" and not ctx["foundationsLocked"] and not ctx.get("edit"):
        blocks.append("## Selected style\n" + json.dumps(data["styles"][ctx["style"]], ensure_ascii=False))
    elif ctx["style"] != "auto":
        blocks.append("The style preference applies only to free composition axes; DS foundations and masters win.")
    blocks.append(data["quality"])
    # Retrieval includes only methods applicable to this surface, never company skins.
    for item in data["sources"]:
        if ctx["surface"] in item["surfaces"] or "all" in item["surfaces"]:
            blocks.append(f"Method ({item['name']}): {item['rule']} Source: {item['url']}")
    return "\n\n".join(blocks)


def directions(ctx: dict) -> list[dict]:
    """Composition plans for utility screens/locked systems, without fake marketing fields."""
    surface = ctx["surface"]
    pattern = knowledge()["patterns"][surface]
    plans = [
        ("task-first", "Задача на первом месте", "Основное действие и нужные для него данные видны сразу", "Второстепенные сведения раскрываются позже"),
        ("compare-first", "Сравнение и контекст", "Связанные данные сгруппированы для проверки перед действием", "Больше информации на первом экране"),
        ("guided", "Последовательное решение", "Сложное решение разделено на понятные связанные группы", "Меньше данных видно одновременно"),
    ]
    if ctx["requestedMode"] == "strict":
        plans = [("registered", "Композиция дизайн-системы", "Точные мастера и допустимые слоты", "Новые компоненты требуют расширения системы")]
    return [{"id": key, "label": label, "motivation": why, "tradeoff": tradeoff,
             "plan": {"schemaVersion": "generator-plan/1.0", "surface": surface,
                      "composition": pattern["structure"], "emphasis": why,
                      "requiredStates": pattern["states"], "foundationsLocked": ctx["foundationsLocked"]}}
            for key, label, why, tradeoff in plans]


def lint(ir: dict, surface: str, *, locked: bool = False) -> list[dict]:
    import qualitygate
    excluded = {"grid-8"}  # A brand spacing system is not necessarily an 8px grid.
    if surface == "component":
        excluded |= {"single-h1", "frame-overflow"}
    rules = [r for r in qualitygate.RULES if r["id"] not in excluded]
    return qualitygate.check(ir, rules=rules)


def has_masters(ir: dict) -> bool:
    def walk(node):
        return isinstance(node, dict) and (bool((node.get("sourceMeta") or {}).get("componentRef"))
            or any(walk(child) for child in node.get("children") or []))
    return any(walk(node) for node in ir.get("tree") or [])


def repair_guard(before: dict, after: dict, surface: str, ds: dict | None = None, *, brief: str = "") -> str | None:
    """Reject new defects, changed foundations and changed/removed exact instances."""
    if before.get("tokens") != after.get("tokens"):
        return "Quality Pass: repair изменил зафиксированные foundations"
    def referenced(value):
        out = []
        if isinstance(value, dict):
            ref = (value.get("sourceMeta") or {}).get("componentRef")
            if ref:
                from design_system.compiler import component_shape_hash
                out.append((digest(ref), component_shape_hash(value)))
            for child in value.get("children") or []:
                out.extend(referenced(child))
        return out
    def refs(ir):
        return sorted(item for node in ir.get("tree") or [] for item in referenced(node))
    if refs(before) != refs(after):
        return "Quality Pass: repair изменил или удалил exact master"
    old = {(x["rule"], x.get("path")) for x in lint(before, surface)}
    added = [x for x in lint(after, surface) if (x["rule"], x.get("path")) not in old]
    if added:
        return "Quality Pass: repair добавил дефекты: " + "; ".join(x["rule"] for x in added[:5])
    if ds:
        from design_system import resolver, store
        document, error = store.resolve_ref(ds)
        if error:
            return "Design System: " + str(error)
        check = resolver.validate_generation(after, resolver.resolve_context(
            document, brief, usage_mode=ds.get("usageMode") or "strict"))
        if check["errors"]:
            return "Design System: " + "; ".join(x["message"] for x in check["errors"][:4])
    return None


def report(*, passed: bool, visual: bool, surface: str, ds_check: dict | None = None) -> dict:
    return {"policyVersion": POLICY_VERSION, "surface": surface,
            "status": "preview-ready" if passed and visual else "needs-work" if not passed else "unverified",
            "checks": {"schema": "pass", "designSystem": "fail" if ds_check and ds_check.get("errors") else "pass" if ds_check else "not-applicable",
                       "visual": "pass" if passed and visual else "fail" if visual else "unknown",
                       "keyboard": "unknown", "screenReader": "unknown", "performance": "unknown"}}


def judge_rules(brief: str, ir: dict, surface: str = "auto") -> str:
    surface = surface_for(brief, surface, ir)
    return ("\n\n## Applicable quality policy\n" + knowledge()["quality"]
            + "\nSurface: " + surface + "\n" + json.dumps(knowledge()["patterns"][surface], ensure_ascii=False)
            + "\nDo not request a hero/proof/section count outside a landing page. "
              "Never change locked tokens or exact masters in repair. Report unavailable evidence as unknown.")
