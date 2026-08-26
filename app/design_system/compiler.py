"""Deterministic, budgeted compiler from Design System to AI context."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .identity import ensure_identity


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def component_master_hash(component: dict) -> str:
    master = component.get("masterIr") if isinstance(component.get("masterIr"), dict) else component.get("templateIr")
    return "sha256:" + hashlib.sha256(_json(master or {}).encode("utf-8")).hexdigest()


_INSTANCE_KEYS = {"id", "sourceKey"}
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


def compile_profile(context: dict, *, brief: str = "", archetype_id: str = "", token_budget: int = 1200) -> dict:
    token_budget = max(320, min(int(token_budget or 1200), 4000))
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

    def add(rule_id: str, line: str, *, required: bool = False) -> bool:
        nonlocal used
        cost = _tokens(line)
        if used + cost <= token_budget:
            lines.append(line)
            included.append(rule_id)
            used += cost
            return True
        elif required and used < token_budget:
            # Hard cap is part of the provider contract. Keep the rule marker
            # and as much deterministic content as fits; never overrun budget.
            remaining = token_budget - used
            clipped = line[:max(1, remaining * 4)]
            lines.append(clipped)
            included.append(rule_id)
            used += _tokens(clipped)
            return True
        else:
            omitted.append(rule_id)
            return False

    ref = context.get("systemRef") or {}
    add("system.ref", f"- System: {ref.get('systemId')}@{ref.get('revision')} ({ref.get('contentHash') or 'draft'}); mode={mode}", required=True)
    soul = ((identity.get("soul") or {}).get("oneLine") or {}).get("value")
    if soul:
        add("identity.soul", f"- Soul: {soul}", required=True)
    exception = identity.get("signatureException")
    if isinstance(exception, dict) and exception.get("rule"):
        add("identity.signature-exception", f"- Signature exception: {exception['rule']}", required=True)
    for ban in sorted(identity.get("bans") or [], key=lambda x: (x.get("severity") != "hard", -float(x.get("confidence") or 0))):
        add(str(ban.get("id") or "identity.ban"), f"- {str(ban.get('severity') or 'soft').upper()} BAN: {ban.get('rule')}", required=ban.get("severity") == "hard")
    for signature in sorted(identity.get("signatures") or [], key=lambda x: -float(x.get("confidence") or 0)):
        add(str(signature.get("id") or "identity.signature"), f"- Signature: {signature.get('rule')}")
    archetypes = identity.get("archetypes") or []
    selected = next((item for item in archetypes if item.get("id") == archetype_id), None)
    if selected is None and archetypes:
        brief_l = brief.lower()
        selected = next((item for item in archetypes if str(item.get("name") or "").lower() in brief_l), archetypes[0])
    if selected:
        add(str(selected.get("id")), f"- Archetype: {selected.get('name')} · structure={_json(selected.get('structure') or [])}")
    colors = ((foundations.get("colors") or {}).get("semantic") or {})
    typography = foundations.get("typography") or {}
    add("foundations.colors", f"- Semantic colors: {_json(colors)}", required=True)
    add("foundations.typography", f"- Type: families={_json(typography.get('families') or [])}; scale={_json(typography.get('scale') or {})}; weights={_json(typography.get('weights') or [])}", required=True)
    add("foundations.geometry", f"- Geometry: spacing={_json(foundations.get('spacing') or {})}; radii={_json(foundations.get('radii') or [])}")
    coverage = identity.get("paletteCoverage") or {}
    if coverage.get("roles"):
        add("identity.palette-coverage", f"- Palette role coverage target: {_json(coverage.get('roles'))}; method={coverage.get('method')}")
    components = context.get("components") or []
    component_handles = [component_handle(c, ref) for c in components if isinstance(c, dict)]
    included_master_keys: list[str] = []
    if components:
        if mode == "strict":
            add(
                "registry.component-ref-contract",
                "- STRICT COMPONENT CONTRACT: copy geometry, styles, responsive overrides and hierarchy from an exact master below. Content values/instance ids may change. Every copied master root MUST include its componentRef in sourceMeta.componentRef; missing, stale, invented or visually mutated refs are blocking errors.",
                required=True,
            )
        for component in components:
            if not isinstance(component, dict) or not isinstance(component.get("masterIr"), dict):
                continue
            key = str(component.get("componentKey") or "")
            payload = {
                "componentRef": component_handle(component, ref),
                "masterIr": component["masterIr"],
            }
            if add(f"registry.master.{key}", f"- Exact master {key}: {_json(payload)}"):
                included_master_keys.append(key)
        compact = [{
            "key": c.get("componentKey"),
            "category": c.get("category"),
            "props": list((c.get("propsSchema") or {}).keys()),
            "componentRef": component_handle(c, ref),
            "shapeHash": component_shape_hash(((c.get("masterIr") or {}).get("tree") or [{}])[0]),
        } for c in components if str(c.get("componentKey") or "") in included_master_keys]
        add("registry.components", f"- Masters available in this prompt: {_json(compact)}", required=mode == "strict")
    policy = {
        "strict": "STRICT: registered tokens/components and hard identity rules are mandatory; do not invent replacements.",
        "extend": "EXTEND: preserve identity; provisional additions need an explicit reason.",
        "style-only": "STYLE ONLY: preserve foundations, soul, signatures and bans; registry is optional.",
    }.get(mode, "Preserve the compiled identity.")
    add("policy.usage-mode", f"- {policy}", required=True)
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
        "archetypeId": selected.get("id") if selected else None,
        "validationPlan": [str(t.get("id")) for t in tests],
        "componentHandles": component_handles,
        "includedMasterKeys": included_master_keys,
        "strictReady": mode != "strict" or bool(included_master_keys),
    }
