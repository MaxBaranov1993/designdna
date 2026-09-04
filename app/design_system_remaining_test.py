from __future__ import annotations

import copy
import json
from pathlib import Path

from design_system import compiler, document, resolver
from ir.validate import validate_ir


ROOT = Path(__file__).resolve().parent
TYPE_ROLES = {"display", "h1", "h2", "h3", "lead", "body", "small", "eyebrow"}
INLINE_TYPE_FIELDS = {"fontSize", "lineHeight", "fontWeight", "letterSpacing"}


def _master(background: str) -> dict:
    return {
        "version": "1.1",
        "tokens": {},
        "tree": [{
            "type": "card",
            "style": {"background": background},
            "children": [{"type": "text", "typeRole": "body", "text": "Copy"}],
        }],
    }


def test_compiler_exposes_compact_variant_choices_in_both_registry_views() -> None:
    component = {
        "componentKey": "promo-card",
        "origin": "observed",
        "masterIr": _master("#ffffff"),
        "variants": {
            "default": {"label": "Default", "origin": "observed", "masterRef": "self"},
            "dark": {"label": "Dark campaign", "origin": "user", "masterIr": _master("#111111")},
        },
    }
    result = compiler.compile_profile({
        "systemRef": {"systemId": "ds-1", "revision": 4},
        "components": [component],
        "constraints": {"usageMode": "strict"},
    }, token_budget=32_000)

    prompt = result["promptBlock"]
    assert "registry.variant-selection-contract" in result["includedRuleIds"]
    assert "choose the variant whose label and meaning best fit the brief" in prompt
    assert prompt.count('"key":"dark","label":"Dark campaign","origin":"user"') == 2


def test_strict_validation_accepts_an_exact_user_variant_hash() -> None:
    base_master = _master("#ffffff")
    variant_master = _master("#111111")
    variant_hash = compiler.component_master_hash({"masterIr": variant_master})
    component = {
        "componentKey": "promo-card",
        "origin": "user",
        "confirmed": True,
        "masterIr": base_master,
        "variants": {
            "dark": {
                "label": "Dark",
                "origin": "user",
                "masterIr": variant_master,
                "masterHash": variant_hash,
            },
        },
    }
    context = {
        "systemRef": {"systemId": "ds-1", "revision": 4},
        "components": [component],
        "constraints": {"usageMode": "strict"},
    }
    generated = copy.deepcopy(variant_master)
    generated["tree"][0]["sourceMeta"] = {"componentRef": {
        "systemId": "ds-1",
        "revision": 4,
        "componentKey": "promo-card",
        "masterHash": variant_hash,
    }}

    accepted = resolver.validate_generation(generated, context)
    assert not [error for error in accepted["errors"] if error["code"] in {
        "stale-component-ref", "mutated-exact-master", "unregistered-visual-node",
    }]

    mutated = copy.deepcopy(generated)
    mutated["tree"][0]["style"]["background"] = "#222222"
    rejected = resolver.validate_generation(mutated, context)
    assert any(error["code"] == "mutated-exact-master" for error in rejected["errors"])


def test_summary_counts_user_variants_in_variant_and_origin_totals() -> None:
    result = document.summary({
        "components": {
            "promo-card": {
                "origin": "observed",
                "variants": {
                    "default": {"origin": "observed"},
                    "dark": {"origin": "user"},
                },
            },
        },
    })
    assert result["variants"] == 2
    assert result["origins"]["user"] == 1


def test_exemplars_use_semantic_type_roles_and_remain_schema_valid() -> None:
    seen_roles: set[str] = set()
    for path in sorted((ROOT / "exemplars").glob("*.json")):
        ir = json.loads(path.read_text(encoding="utf-8"))
        assert not [error for error in validate_ir(ir) if error.severity == "error"], path.name

        def walk(node: dict) -> None:
            if node.get("type") in {"heading", "text"}:
                role = node.get("typeRole")
                assert role in TYPE_ROLES, (path.name, node.get("text"), role)
                assert not INLINE_TYPE_FIELDS.intersection(node.get("style") or {}), (path.name, node.get("text"))
                seen_roles.add(role)
            for child in node.get("children") or []:
                walk(child)

        for section in ir.get("tree") or []:
            walk(section)
    assert seen_roles == TYPE_ROLES
