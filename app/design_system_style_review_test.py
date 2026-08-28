"""Style Guide: семантические токены и границы AI-ревью.

Ключевая гарантия — ревью описательное: модель не может тронуть мастера,
токены, fidelity или каталог. Всё, что она возвращает сверх разрешённых
описательных полей, отбрасывается валидатором.
"""
from __future__ import annotations

import json

import pytest

from design_system import style_review
from design_system.compiler import compile_profile


def _foundations() -> dict:
    return {
        "mode": "light",
        "colors": {
            "semantic": {
                "primary": "#7018e6", "accent": "#f1e8fc", "background": "#ffffff",
                "surface": "#f8fafc", "text": "#111827", "textMuted": "#6b7280",
                "border": "#e5e7eb", "secondary": "#374151",
            },
            "primitives": {"brand1": "#7018e6", "measured1": "#d92626"},
        },
        "typography": {"families": ["Inter"], "scale": {"display": 44, "body": 16},
                       "weights": [400, 700],
                       "display": {"family": "Inter", "weight": 700},
                       "body": {"family": "Inter", "weight": 400}},
        "radius": {"card": 12, "button": 999, "input": 8},
        "spacing": {"space1": 8, "space2": 16, "space3": 24},
        "shadows": ["0 1px 2px rgba(0,0,0,.06)"],
        "radii": [8, 12, 999],
    }


def _document() -> dict:
    doc = {
        "id": "ds-test", "foundations": _foundations(),
        "sourceRefs": [{"url": "https://example.com"}],
        "components": {
            "button": {"componentKey": "button", "name": "Button", "category": "actions", "variants": {"default": {}}},
            "service-card": {"componentKey": "service-card", "name": "Service card", "category": "surfaces", "variants": {}},
        },
    }
    return style_review.ensure_style_guide(doc)


def test_semantic_tokens_follow_the_shadcn_convention():
    tokens = _document()["styleGuide"]["tokens"]
    for role in ("background", "foreground", "primary", "primary-foreground",
                 "muted", "muted-foreground", "border", "ring", "radius"):
        assert role in tokens, role
    assert tokens["primary"] == "#7018e6"
    # Тёмный primary → белый foreground; светлый accent → тёмный foreground.
    assert tokens["primary-foreground"] == "#ffffff"
    assert tokens["accent-foreground"] == "#111827"
    # Красный из measured-палитры распознан как destructive.
    assert tokens["destructive"] == "#d92626"


def test_measured_character_is_derived_from_real_values():
    measured = _document()["styleGuide"]["measured"]
    assert measured["cornerCharacter"] == "pill"      # button radius 999
    assert measured["density"] == "comfortable"       # медиана spacing = 16
    assert measured["shadowUsage"] == "subtle"


def test_review_accepts_only_descriptive_fields():
    doc = _document()
    raw = json.dumps({"styleGuide": {
        "tone": "Confident dark SaaS with electric violet accents",
        "doRules": ["Use pill buttons", ""],
        "dontRules": ["No flat grey wireframes"],
        "componentNotes": {"button": "Always pill", "unknown-key": "dropped"},
        # Попытки выйти за пределы описательного контракта:
        "components": {"button": {"masterIr": {}}},
        "tokens": {"primary": "#ff0000"},
        "fidelity": {"passed": True},
    }})
    updated = style_review.apply_style_review(doc, raw, provider="claude")
    review = updated["styleGuide"]["review"]
    assert review["tone"].startswith("Confident")
    assert review["doRules"] == ["Use pill buttons"]
    assert review["componentNotes"] == {"button": "Always pill"}
    assert "components" not in review and "tokens" not in review and "fidelity" not in review
    # Мастера и токены документа не изменились.
    assert updated["components"] == doc["components"]
    assert updated["styleGuide"]["tokens"]["primary"] == "#7018e6"
    assert updated["styleGuide"]["provider"] == "claude"


def test_review_without_usable_fields_is_rejected():
    with pytest.raises(ValueError):
        style_review.apply_style_review(_document(), json.dumps({"styleGuide": {"tone": "  "}}))
    with pytest.raises(ValueError):
        style_review.apply_style_review(_document(), "no json here")


def test_prompt_is_a_compact_digest_without_master_ir():
    messages = style_review.build_style_review_prompt(_document())
    assert messages[0]["role"] == "system"
    payload = json.loads(messages[1]["content"])
    assert payload["data"]["url"] == "https://example.com"
    assert "semanticTokens" in payload["data"]
    assert "masterIr" not in messages[1]["content"]


def test_style_guide_reaches_the_generation_prompt():
    doc = _document()
    doc = style_review.apply_style_review(doc, json.dumps({"styleGuide": {
        "tone": "Electric violet SaaS",
        "doRules": ["Pill buttons only"],
        "dontRules": ["Never plain grey"],
    }}))
    context = {
        "systemRef": {"systemId": "ds-test", "revision": 1, "contentHash": "x"},
        "foundations": doc["foundations"],
        "styleGuide": doc["styleGuide"],
        "components": [],
        "constraints": {"usageMode": "style-only"},
    }
    block = compile_profile(context, token_budget=4000)["promptBlock"]
    assert "UI tokens" in block and "shadcn-style" in block
    assert "Electric violet SaaS" in block
    assert "DO: Pill buttons only" in block
    assert "DON'T: Never plain grey" in block
