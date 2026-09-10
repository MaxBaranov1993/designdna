"""Сводки мастеров, декоративные сигнатуры и приоритеты компилятора ДС."""
import json
from copy import deepcopy

from design_system import compiler, master_summary, resolver


def _text(text, family="Hanken Grotesk", size=14, weight=400, color="#f2f0ea", **style):
    return {"type": "text", "text": text, "frame": {"width": 100, "height": size + 4},
            "style": {"fontFamily": f"{family}, sans-serif", "fontSize": size, "fontWeight": weight, "color": color, **style}}


def _card(width, height, children=None, **style):
    return {"type": "card", "frame": {"width": width, "height": height}, "style": style, "children": children or []}


TRUST_CARD = {
    "componentKey": "trust-card", "name": "Trust card", "category": "surfaces", "origin": "user", "confirmed": True,
    "variants": {"default": {"label": "Default"}, "standard": {"label": "Standard"}},
    "masterIr": {"version": "1.1", "tree": [{
        "type": "card",
        "frame": {"width": 334, "height": 118, "direction": "column", "gap": 8, "padding": [12, 14, 12, 14]},
        "style": {"background": "#100f15", "borderColor": "#ffffff12", "borderWidth": 1, "borderRadius": 13},
        "styleBindings": {"background": {"token": "semantic.surface"}},
        "children": [
            _card(30, 30, [_text("E", family="JetBrains Mono", size=13, weight=700, color="#9aa6ff")],
                  background="#1c1c24", borderRadius=8),
            _text("ETOSO", family="Bricolage Grotesque", size=14.5, weight=700),
            _card(98, 19, [_card(4, 4, background="#a8e0c2", borderRadius=2),
                           _text("Warming inboxes", size=9.5, weight=600, color="#a8e0c2")],
                  background="#a8e0c214", borderColor="#a8e0c226", borderWidth=1, borderRadius=999),
            _text("etoso.ai", family="JetBrains Mono", size=11, color="#6e6c7a"),
            _text("Traceable AI intelligence from messy enterprise data", size=12, color="#908da0"),
            _text("enterprise data", size=12, color="#908da0"),  # перенос строки в захвате — дубликат
            {"type": "image", "frame": {"width": 14, "height": 14}},
            _text("4,000", size=11.5, weight=600),
        ],
    }]},
}

SEARCH_FIELD = {
    "componentKey": "search-field", "name": "Search field", "category": "forms", "origin": "user", "confirmed": True,
    "masterIr": {"version": "1.1", "tree": [{
        "type": "card", "frame": {"width": 600, "height": 72, "direction": "row", "gap": 10, "padding": [6, 6, 6, 20]},
        "style": {"background": "#13131a", "borderColor": "#1b1b1f", "borderWidth": 1, "borderRadius": 16},
        "children": [
            _text("https://", family="JetBrains Mono", size=17, color="#6e6c7a"),
            {"type": "input", "placeholder": "yourcompany.com", "frame": {"width": 345, "height": 58},
             "style": {"fontFamily": "JetBrains Mono, monospace", "fontSize": 17, "borderRadius": 0}},
            {"type": "button", "text": "Prove it →", "frame": {"width": 124, "height": 52},
             "style": {"fontFamily": "Hanken Grotesk", "fontSize": 16, "fontWeight": 600, "color": "#ffffff",
                       "background": "#5b6cff", "borderRadius": 26,
                       "boxShadow": "rgba(91, 108, 255, 0.6) 0px 12px 30px -8px"},
             "children": [_text("Prove it →", size=16, weight=600, color="#ffffff")]},
        ],
    }]},
}

PROCESS_STEP = {
    "componentKey": "process-step", "name": "Process step", "category": "content", "origin": "user", "confirmed": True,
    "masterIr": {"version": "1.1", "tree": [{
        "type": "card", "frame": {"width": 200, "height": 185, "direction": "column", "gap": 0},
        "style": {},
        "children": [
            _text("DAY 1", family="JetBrains Mono", size=10, color="#6e6c7a", letterSpacing=1),
            _card(32, 32, [_text("1", family="Bricolage Grotesque", size=15, weight=700, color="#ffffff")],
                  background="#5b6cff", borderRadius=16),
            _card(120, 1, background="#1b1b1f"),
            _text("Your market", family="Bricolage Grotesque", size=16, weight=700),
            _text("AI reads your site and scans", size=13, color="#9d9aab"),
            _text("the market.", size=13, color="#9d9aab"),
            _text("site and scans", size=13, color="#9d9aab"),
            _text("2 · Turn it on when ready", family="JetBrains Mono", size=10.5, weight=700, color="#a8e0c2",
                  textTransform="uppercase", letterSpacing=1),
            _text("$3K / month", family="JetBrains Mono", size=9.5, color="#7e7c8a"),
        ],
    }]},
}

KIT = [TRUST_CARD, SEARCH_FIELD, PROCESS_STEP]


def test_summary_line_is_compact_and_describes_anatomy() -> None:
    line = master_summary.summary_line(TRUST_CARD)
    assert line.startswith("- Master trust-card [surfaces]: ")
    assert len(line) <= master_summary.MAX_SUMMARY_CHARS
    payload = json.loads(line.split(": ", 1)[1])
    assert payload["variants"] == ["default", "standard"]
    assert payload["root"]["size"] == "334×118"
    assert "bg #100f15" in payload["root"]["surface"] and "border 1px #ffffff12" in payload["root"]["surface"]
    assert payload["root"]["layout"] == "column gap 8 pad 12/14/12/14"
    assert payload["root"]["tokens"] == {"background": "semantic.surface"}
    anatomy = payload["anatomy"]
    assert any(item.startswith('pill "Warming inboxes"') and "+ dot 4px" in item for item in anatomy)
    assert any(item.startswith('initial "E"') for item in anatomy)
    assert any('text "etoso.ai" JetBrains Mono 11/400 #6e6c7a' == item for item in anatomy)
    assert any(item.startswith('text "ETOSO" Bricolage Grotesque 14.5/700') for item in anatomy)
    # перенос строки склеен, а не выдан отдельной записью
    assert not any(item.startswith('text "enterprise data"') for item in anatomy)
    assert sum(1 for item in anatomy if "Traceable AI" in item) == 1
    assert "status-dot" in payload["decor"] and "pill-badge" in payload["decor"] and "avatar-initial" in payload["decor"]


def test_summary_line_merges_wrapped_lines_and_counts_repeats() -> None:
    payload = json.loads(master_summary.summary_line(PROCESS_STEP).split(": ", 1)[1])
    anatomy = payload["anatomy"]
    merged = [item for item in anatomy if item.startswith('text "AI reads your site and scans the market."')]
    assert len(merged) == 1
    assert not any(item.startswith('text "site and scans"') for item in anatomy)
    assert any(item.startswith('pill "1"') for item in anatomy)
    assert "divider 1px" in anatomy
    assert "numbered-pill" in payload["decor"] and "mono-label" in payload["decor"]


def test_summary_line_stays_within_budget_for_huge_masters() -> None:
    huge = deepcopy(TRUST_CARD)
    huge["masterIr"]["tree"][0]["children"] = [
        _text(f"Row number {index} with a distinct sentence about it", size=13 + (index % 3)) for index in range(200)
    ]
    line = master_summary.summary_line(huge)
    assert len(line) <= master_summary.MAX_SUMMARY_CHARS
    payload = json.loads(line.split(": ", 1)[1])
    assert payload["anatomy"][-1].startswith("…")
    assert len(master_summary.summarize_master(huge)["anatomy"]) <= master_summary.MAX_ANATOMY + 1


def test_decorative_signatures_detect_kit_traits() -> None:
    signatures = master_summary.decorative_signatures(KIT)
    by_id = {item["id"]: item for item in signatures}
    assert {"sig-mono-labels", "sig-status-pill", "sig-arrow-cta", "sig-inline-form", "sig-numbered-steps",
            "sig-hairline-borders", "sig-glow-shadow"} <= set(by_id)
    assert len(signatures) <= master_summary.MAX_SIGNATURES
    assert "JetBrains Mono" in by_id["sig-mono-labels"]["rule"]
    assert "Prove it →" in by_id["sig-arrow-cta"]["examples"]
    assert "https://" in by_id["sig-inline-form"]["rule"] and "моноширинным" in by_id["sig-inline-form"]["rule"]
    assert "точка 4px" in by_id["sig-status-pill"]["rule"] and "Warming inboxes" in by_id["sig-status-pill"]["examples"]
    assert "2 · Turn it on when ready" in by_id["sig-numbered-steps"]["examples"]
    assert all(item["provenance"] == "measured" and item["confirmed"] is False for item in signatures)
    assert master_summary.decorative_signatures([]) == []
    assert master_summary.decorative_signatures([{"componentKey": "x"}]) == []
    lines = master_summary.signature_lines(signatures)
    assert lines[0][0] == signatures[0]["id"]
    assert all(line.startswith("- Decor signature: ") for _id, line in lines)
    assert any("Примеры: «Prove it →»" in line for _id, line in lines)


# ---------- компилятор: приоритеты и бюджет ----------

def _heavy_master(index: int) -> dict:
    children = [_text(f"Row {index}-{row} of a long observed section with many words", size=12 + row % 5)
                for row in range(60)]
    return {"version": "1.1", "tree": [{"type": "card", "frame": {"width": 840, "height": 400},
                                        "style": {"background": "#0a0a0e", "borderColor": "#1b1b1f", "borderWidth": 1,
                                                  "borderRadius": 18},
                                        "children": children}]}


def _context(mode: str, count: int = 15) -> dict:
    components = []
    for index in range(count):
        components.append({"componentKey": f"block-{index}", "name": f"Block {index}", "category": "content",
                           "origin": "user", "confirmed": True, "masterIr": _heavy_master(index)})
    components[:0] = deepcopy(KIT)
    review = {
        "tone": "Dark technical sales interface with a restrained periwinkle accent.",
        "colorUsage": "Near-black canvas, warm off-white text, periwinkle only for actions.",
        "typographyCharacter": "Heavy Bricolage Grotesque display, Hanken Grotesk body, tiny JetBrains Mono labels.",
        "doRules": [f"Do rule {index} about pills, labels and generous dark negative space." for index in range(10)],
        "dontRules": [f"Dont rule {index} about bright accents, light surfaces and serif type." for index in range(10)],
        "componentNotes": {"search-field": "Square corners, mono text, periwinkle focus ring."},
    }
    return {
        "systemRef": {"systemId": "ds-kit", "revision": 3, "contentHash": "sha256:kit"},
        "foundations": {
            "colors": {"semantic": {"primary": "#5b6cff", "background": "#0a0a0e", "surface": "#0a0a0e",
                                    "text": "#f2f0ea", "textMuted": "#9d9aab", "border": "#1b1b1f"}},
            "typography": {"families": ["Hanken Grotesk", "JetBrains Mono", "Bricolage Grotesque"],
                           "scale": {"display": 66, "h2": 58, "body": 16, **{f"size{i}": 40 - i for i in range(6, 30)}},
                           "weights": [400, 600, 700]},
            "spacing": {**{f"space{i}": i * 2 for i in range(1, 35)}, "section": 56},
            "radii": [0, 8, 13, 16, 999],
            "shadows": ["rgba(91, 108, 255, 0.6) 0px 12px 30px -8px"],
        },
        "styleGuide": {
            "tokens": {"background": "#0a0a0e", "primary": "#5b6cff", "radius-button": 999, "radius-input": 0},
            "measured": {"mode": "dark", "cornerCharacter": "pill", "density": "comfortable"},
            "profile": {"mode": "dark", "cornerCharacter": "pill", "density": "comfortable",
                        "labelStyle": "моноширинный JetBrains Mono, uppercase, с разрядкой, кегль ~9px",
                        "copyVoice": {"heading": ["Everything's done for you."], "cta": ["Prove it →"]}},
            "review": review,
        },
        "siteBrief": {
            "summary": "Slsbmb is an AI sales-automation site that interviews a company and runs a sending engine.",
            "audience": "Companies that want automated outbound sales.",
            "offer": "Subscribe, and about three weeks later, the replies start.",
            "tone": "Direct, confident and conversational.",
            "sections": [f"Section heading number {index} of the source landing" for index in range(9)],
            "componentUsage": {"trust-card": "Companies already selling with the service."},
        },
        "identity": {
            "status": "extracted",
            "soul": {"oneLine": {"value": "выразительный контраст крупной и основной типографики"}},
            "signatures": [{"id": "sig-type-contrast", "rule": "Display около 4× body", "confidence": 0.86}],
            "bans": [],
            "archetypes": [
                {"id": "archetype-gallery", "name": "Gallery", "structure": ["gallery"]},
                {"id": "archetype-header", "name": "Header", "structure": ["header"]},
                {"id": "archetype-cta", "name": "Cta", "structure": ["cta"]},
                {"id": "archetype-how-it-works", "name": "How It Works", "structure": ["how-it-works"]},
                {"id": "archetype-pricing", "name": "Pricing", "structure": ["pricing"]},
                {"id": "archetype-footer", "name": "Footer", "structure": ["footer"]},
            ],
        },
        "identityTests": [{"id": "identity.type.display-body-ratio"}],
        "components": components,
        "constraints": {"usageMode": mode},
    }


def test_extend_budget_carries_summaries_review_and_signatures() -> None:
    context = _context("extend")
    compiled = compiler.compile_profile(context, brief="Лендинг для сервиса автоматизации продаж",
                                        token_budget=compiler.default_budget("extend"), surface="landing")
    assert compiled["estimatedTokens"] <= compiled["tokenBudget"] == compiler.EXTEND_DEFAULT_BUDGET
    assert compiled["omittedRuleIds"] == []
    keys = [str(c["componentKey"]) for c in context["components"]]
    assert compiled["summarizedMasterKeys"] == keys
    assert compiled["includedMasterKeys"] == []  # точный IR в extend не нужен, сводки покрывают все мастера
    included = compiled["includedRuleIds"]
    for rule in ("styleguide.profile", "styleguide.review", "site.brief", "styleguide.component-notes",
                 "registry.summary-contract", "identity.archetypes", "sig-mono-labels", "sig-status-pill",
                 "sig-inline-form", "policy.usage-mode"):
        assert rule in included, rule
    assert all(f"styleguide.do.{index}" in included and f"styleguide.dont.{index}" in included for index in range(10))
    block = compiled["promptBlock"]
    # характер раньше числовых шкал, шкалы компактные
    assert block.index("Style profile") < block.index("Decor signature") < block.index("Site brief") \
        < block.index("Design language") < block.index("Semantic colors") < block.index("Master trust-card")
    assert "size27" not in block and '"otherSizes"' in block and '"spacingSteps"' in block
    assert compiled["decorSignatureIds"][0] == "sig-mono-labels"
    assert compiled["archetypeSelection"] == "page" and compiled["archetypeId"] is None
    assert "Page archetypes" in block and "Gallery" in block and "Pricing" in block


def test_style_only_gets_the_same_profile_as_extend() -> None:
    context = _context("style-only")
    compiled = compiler.compile_profile(context, brief="Секция тарифов", token_budget=compiler.default_budget("style-only"))
    assert len(compiled["summarizedMasterKeys"]) == len(context["components"])
    assert "styleguide.review" in compiled["includedRuleIds"] and "site.brief" in compiled["includedRuleIds"]
    assert "STYLE ONLY" in compiled["promptBlock"]
    assert compiled["archetypeSelection"] == "brief" and compiled["archetypeId"] == "archetype-pricing"


def test_strict_keeps_exact_masters_after_summaries() -> None:
    context = _context("strict", count=4)
    compiled = compiler.compile_profile(context, brief="unrelated", token_budget=compiler.default_budget("strict"))
    assert compiled["strictReady"] is True
    assert len(compiled["summarizedMasterKeys"]) == len(context["components"])
    assert compiled["includedMasterKeys"]  # точные мастера по-прежнему уходят в strict
    assert "registry.component-ref-contract" in compiled["includedRuleIds"]
    assert "registry.components" in compiled["includedRuleIds"]
    assert compiled["promptBlock"].index("Master trust-card") < compiled["promptBlock"].index("Exact master")


def test_pinned_master_reserve_survives_summaries() -> None:
    context = _context("strict", count=6)
    pinned_line = next(line for line in compiler.compile_profile(
        context, token_budget=32_000, pinned_keys=["block-5"])["promptBlock"].split("\n")
        if line.startswith("- Exact master block-5:"))
    budget = compiler._tokens(pinned_line) + 400
    compiled = compiler.compile_profile(context, brief="unrelated", token_budget=budget, pinned_keys=["block-5"])
    assert compiled["includedMasterKeys"][0] == "block-5"
    assert compiled["pinnedMasterKeys"] == ["block-5"]
    assert compiled["strictReady"] is True
    assert compiled["estimatedTokens"] <= budget


def test_site_brief_is_shrunk_by_meaning_not_clipped() -> None:
    context = _context("extend", count=0)
    compiled = compiler.compile_profile(context, brief="Карточка", token_budget=900)
    line = next(line for line in compiled["promptBlock"].split("\n") if line.startswith("- Site brief (embed target): "))
    payload = json.loads(line.split(": ", 1)[1])
    assert payload.get("summary")
    assert "site.brief" in compiled["includedRuleIds"]
    levels = compiler.compact_site_brief_levels(context["siteBrief"])
    assert levels[0]["sections"] and len(levels[1]["sections"]) == 6 and "sections" not in levels[2]
    assert set(levels[-1]) == {"summary"}


def test_select_archetypes_prefers_explicit_then_brief_then_page() -> None:
    archetypes = _context("extend")["identity"]["archetypes"]
    explicit, reason = compiler.select_archetypes(archetypes, archetype_id="archetype-footer", brief="лендинг")
    assert reason == "explicit" and [a["id"] for a in explicit] == ["archetype-footer"]
    by_brief, reason = compiler.select_archetypes(archetypes, brief="Секция «как это работает» с шагами")
    assert reason == "brief" and [a["id"] for a in by_brief] == ["archetype-how-it-works"]
    page, reason = compiler.select_archetypes(archetypes, brief="Собери лендинг", surface="component")
    assert reason == "page" and len(page) == len(archetypes)
    page, reason = compiler.select_archetypes(archetypes, brief="Промо", surface="landing")
    assert reason == "page"
    none, reason = compiler.select_archetypes(archetypes, brief="Карточка отзыва", surface="component")
    assert reason == "none" and none == []


def test_compact_scales_keep_extremes_and_drop_generated_names() -> None:
    typography = compiler.compact_typography(_context("extend")["foundations"]["typography"])
    assert typography["scale"] == {"display": 66, "h2": 58, "body": 16}
    assert len(typography["otherSizes"]) <= 12
    assert typography["otherSizes"][0] == 34 and typography["otherSizes"][-1] == 11
    geometry = compiler.compact_geometry(_context("extend")["foundations"])
    assert geometry["spacing"] == {"section": 56}
    assert len(geometry["spacingSteps"]) <= 12 and geometry["spacingSteps"][0] == 2 and geometry["spacingSteps"][-1] == 68
    assert geometry["radii"] == [0, 8, 13, 16, 999]
    assert geometry["shadowSamples"][0].startswith("rgba(91, 108, 255")
    assert compiler.compact_steps([]) == []
    assert compiler.compact_steps([1, 2, 3], limit=12) == [3, 2, 1]


def test_default_budgets_and_resolver_passthrough() -> None:
    assert compiler.default_budget("strict") == compiler.STRICT_DEFAULT_BUDGET == 32_000
    assert compiler.default_budget("extend") == compiler.default_budget("style-only") == 8_000
    document = {"id": "ds-kit", "revision": 1, "contentHash": "x", "foundations": {}, "styleGuide": {},
                "identity": _context("extend")["identity"],
                "components": {item["componentKey"]: item for item in deepcopy(KIT)}}
    context = resolver.resolve_context(document, "лендинг", usage_mode="extend")
    compiled = resolver.compiled_context(context, brief="лендинг", token_budget=8000, surface="landing")
    assert compiled["archetypeSelection"] == "page"
    assert set(compiled["summarizedMasterKeys"]) == {"trust-card", "search-field", "process-step"}


def test_direction_digest_is_compact_and_locks_the_system() -> None:
    context = _context("extend")
    digest = compiler.direction_digest(context, brief="Лендинг для сервиса", surface="landing")
    assert digest["locked"] == compiler.DIRECTION_LOCK
    assert digest["soul"].startswith("выразительный контраст")
    assert digest["styleProfile"]["labelStyle"].startswith("моноширинный")
    assert digest["decor"] and any("JetBrains Mono" in rule for rule in digest["decor"])
    assert digest["do"][0].startswith("Do rule 0") and len(digest["do"]) == 6 and len(digest["dont"]) == 6
    assert digest["site"]["summary"].startswith("Slsbmb") and len(digest["siteSections"]) == 8
    assert digest["copyVoice"] == {"heading": ["Everything's done for you."], "cta": ["Prove it →"]}
    assert "Pricing" in digest["sectionArchetypes"] and "Gallery" in digest["sectionArchetypes"]
    assert digest["families"] == ["Hanken Grotesk", "JetBrains Mono", "Bricolage Grotesque"]
    assert len(digest["masters"]) == compiler.DIRECTION_DIGEST_MASTERS
    assert digest["masters"][0]["key"] == "trust-card" and len(digest["masters"][0]["anatomy"]) <= 4
    assert len(json.dumps(digest, ensure_ascii=False)) < 7000
    component_digest = compiler.direction_digest(context, brief="Карточка тарифа", surface="component")
    assert component_digest["sectionArchetypes"] == ["Pricing"]
    assert "masters" not in compiler.direction_digest({"components": []})
