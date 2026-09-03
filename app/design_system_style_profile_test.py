"""Style profile / IR-tokens дизайн-системы и приведение style-DNA с порта."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_system import style_review
from ir import validate_ir


def _foundations() -> dict:
    return {
        "mode": "dark",
        "colors": {
            "primitives": {"brand1": "#7018e6", "measured1": "#0b0b12"},
            "semantic": {"primary": "#7018e6", "secondary": "#2a2a3a", "accent": "#a06bff",
                         "background": "#0b0b12", "surface": "#15151f", "text": "#f5f5ff",
                         "textMuted": "#9a9ab0", "border": "#26263a"},
        },
        "typography": {"families": ["Space Mono", "Inter"], "scale": {"display": 48, "body": 16},
                       "weights": [400, 700], "display": {"family": "Space Mono", "weight": 700},
                       "body": {"family": "Inter", "weight": 400}},
        "spacing": {"space1": 8, "space2": 16, "space3": 32, "section": 96},
        "radii": [4, 8], "radius": {"card": 8, "button": 4, "input": 4},
        "shadows": [], "breakpoints": {}, "containers": {"content": 1120},
        "imageDirection": "тёмные скриншоты интерфейса с неоновыми акцентами",
    }


def _document() -> dict:
    return {
        "id": "ds-test", "revision": 1, "foundations": _foundations(),
        "components": {"hero": {"componentKey": "hero", "masterIr": {"tree": [{
            "type": "section", "children": [
                {"type": "text", "size": "sm", "text": "2 · TURN IT ON WHEN READY"},
                {"type": "heading", "text": "Sending Engine"},
                {"type": "button", "text": "Start free"},
            ]}]}}},
    }


def _valid(tokens: dict) -> list[str]:
    return validate_ir({"version": "1.1", "tokens": tokens, "tree": [
        {"id": "s", "type": "hero", "variant": "centered",
         "props": {"heading": "x", "ctaPrimary": {"text": "Go"}}}]})


def test_ir_tokens_from_foundations_are_schema_valid_and_keep_source_values():
    tokens = style_review.ir_tokens(_foundations())
    assert _valid(tokens) == []
    assert tokens["mode"] == "dark"
    assert tokens["color"]["background"] == "#0b0b12"
    assert tokens["font"]["display"]["family"] == "Space Mono"
    assert tokens["radius"]["button"] == "sm"
    assert tokens["shadow"] == "none"


def test_coerce_accepts_flat_shadcn_map_partial_v1_and_foundations():
    flat = style_review.semantic_tokens(_foundations())
    coerced = style_review.coerce_ir_tokens(flat)
    assert coerced and _valid(coerced) == []
    assert coerced["color"]["primary"] == "#7018e6" and coerced["mode"] == "dark"
    assert coerced["font"]["display"]["family"] == "Space Mono"

    partial = style_review.coerce_ir_tokens({"color": {"primary": "#ff0000"}})
    assert partial and _valid(partial) == [] and partial["color"]["primary"] == "#ff0000"

    from_foundations = style_review.coerce_ir_tokens(_foundations())
    assert from_foundations and _valid(from_foundations) == []
    assert style_review.coerce_ir_tokens({"radius": 8}) is None
    assert style_review.coerce_ir_tokens(None) is None


def test_style_profile_and_prompt_carry_atmosphere_and_copy_voice():
    doc = style_review.ensure_style_guide(_document())
    guide = doc["styleGuide"]
    assert _valid(guide["irTokens"]) == []
    profile = guide["profile"]
    assert profile["mode"] == "dark" and profile["cornerCharacter"] == "subtle"
    assert "моноширинный" in profile["typographyCharacter"]
    assert profile["copyVoice"]["heading"] == ["Sending Engine"]
    assert profile["copyVoice"]["eyebrow"] == ["2 · TURN IT ON WHEN READY"]
    assert profile["copyVoice"]["cta"] == ["Start free"]
    prompt = style_review.profile_prompt(doc)
    assert "атмосфера" in prompt and "Sending Engine" in prompt and "неоновыми" in prompt


def test_compiled_profile_includes_style_profile_as_required_line():
    from design_system import resolver
    doc = style_review.ensure_style_guide(_document())
    doc.setdefault("identity", {})
    context = resolver.resolve_context(doc, "карточка тарифа", usage_mode="style-only")
    compiled = resolver.compiled_context(context, brief="карточка тарифа", token_budget=600)
    assert "styleguide.profile" in compiled["includedRuleIds"]
    assert "Style profile" in compiled["promptBlock"]
    assert json.dumps(compiled["promptBlock"], ensure_ascii=False)
