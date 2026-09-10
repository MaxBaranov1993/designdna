"""Fast, cached art-direction stage producing a validated DesignBrief."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema

import cache_store
import llm_client as llm
import typography


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "design-brief.schema.json"
CACHE_KIND = "art_direction"
CACHE_VERSION = "design-directions/1.1"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_design_brief(value: dict) -> dict:
    """Validate the public contract plus references owned by Python code."""
    jsonschema.Draft7Validator(load_schema()).validate(value)
    if value["typePair"] not in typography.ART_DIRECTION_PAIR_NAMES:
        raise ValueError(f"unknown curated typePair: {value['typePair']}")
    return value


def cache_key(
    brief: Any,
    product_type: str,
    style_dna: dict | None = None,
    *,
    count: int = 1,
    provider: str | None = None,
) -> str:
    canonical = json.dumps(
        {
            "version": CACHE_VERSION,
            "brief": brief,
            "productType": product_type,
            "styleDNA": style_dna,
            "count": count,
            "provider": provider,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _prompt(brief: Any, product_type: str, style_dna: dict | None, count: int) -> list[dict]:
    pair_catalog = [
        {"id": name, "display": typography.PAIRS_BY_NAME[name]["display"],
         "body": typography.PAIRS_BY_NAME[name]["body"]}
        for name in typography.ART_DIRECTION_PAIR_NAMES
    ]
    if count == 1:
        system = (
            "You are the fast art-direction stage for a product UI generator. Return JSON only, "
            "matching the supplied DesignBrief schema exactly. Settle one bold, coherent aesthetic. "
            "Use exactly one rhythm.risk. Accent hues share the one accent lightness and chroma."
        )
    else:
        system = (
            "You are the fast art-direction stage for a product UI generator. Return JSON only as "
            "an object with a directions array of exactly the requested count. Each direction must "
            "have id, label, motivation, tradeoff, and designBrief. Make the directions materially "
            "different in composition, rhythm, and hero shape, not merely palette swaps. Each "
            "designBrief must match the supplied DesignBrief schema exactly, use one rhythm.risk, "
            "and keep accent hues on one shared lightness and chroma."
        )
    payload = {
        "brief": brief, "productType": product_type, "styleDNA": style_dna,
        "count": count, "typePairs": pair_catalog, "designBriefSchema": load_schema(),
    }
    if style_dna and style_dna.get("policyHash"):
        import generator_policy
        policy = generator_policy.context(str(brief), surface=style_dna.get("surface", "landing"),
                                          style=style_dna.get("style", "auto"))
        system += "\n" + generator_policy.prompt(policy)
        system += "\nAll alternatives must respect the selected style. The schema's rhythm.risk is a justified composition choice, never obligatory spectacle."
    if isinstance(style_dna, dict) and isinstance(style_dna.get("designSystemDigest"), dict):
        # Дизайн-система задаёт палитру, шрифты, геометрию и декор: направления
        # различаются композицией, порядком секций, ритмом и углом копирайта,
        # а не «другой палитрой», которую генератор всё равно не сможет применить.
        system += (
            "\nA design system is attached as styleDNA.designSystemDigest and it is the source of truth: every "
            "direction keeps its palette, type families, radii, spacing, borders, shadows and decorative language. "
            "Do not propose other palettes or type pairs: fill the palette seeds from the system's colors and pick the "
            "curated typePair closest to its families (the generator locks the real fonts). Differentiate directions "
            "by composition, section order, hero shape, rhythm, density and copy angle; in each motivation name the "
            "masters, section archetypes and decorative traits (mono labels, status pills, arrow CTAs, numbered steps, "
            "inline form) the direction leans on. Copy follows the site's voice samples and language."
        )
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def create_design_brief(
    brief: Any,
    product_type: str,
    *,
    style_dna: dict | None = None,
    provider: str | None = None,
    count: int = 1,
    generate_if_missing: bool = True,
) -> dict | list[dict]:
    """Create cached art direction(s) for a brief, product type and design system.

    The legacy one-direction call returns a DesignBrief directly. ``count > 1``
    returns direction records with public chip copy plus a validated DesignBrief.
    """
    if not isinstance(product_type, str) or not product_type.strip():
        raise ValueError("product_type must be a non-empty string")
    count = max(1, min(int(count), 3))
    key = cache_key(brief, product_type, style_dna, count=count, provider=provider)
    cached = cache_store.get(CACHE_KIND, key)
    if count == 1 and isinstance(cached, dict) and "directions" not in cached:
        return deepcopy(validate_design_brief(cached))
    # cache_store хранит только объекты: список направлений лежит в {"directions": [...]}.
    # Без обёртки запись молча отклонялась, и второй проход десктопа (rawOutputs)
    # не находил направления, под которые был собран промпт.
    cached_directions = cached.get("directions") if isinstance(cached, dict) else cached
    if count > 1 and isinstance(cached_directions, list):
        return deepcopy(_validate_directions(cached_directions, count))
    if not generate_if_missing:
        raise LookupError("art direction is not cached")

    raw = llm.chat(
        provider, _prompt(brief, product_type, style_dna, count), 0.2,
        timeout=30, role="art-direction", reasoning_effort="medium",
    )
    try:
        result = json.loads(llm.extract_json(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("art direction returned invalid JSON") from exc
    if count == 1:
        if not isinstance(result, dict):
            raise ValueError("art direction must return a JSON object")
        validate_design_brief(result)
        cache_store.put(CACHE_KIND, key, result)
        return deepcopy(result)

    directions = result.get("directions") if isinstance(result, dict) else None
    directions = _validate_directions(directions, count)
    cache_store.put(CACHE_KIND, key, {"directions": directions})
    return deepcopy(directions)


def _validate_directions(value: Any, count: int) -> list[dict]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"art direction must return exactly {count} directions")
    result: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"direction {index} must be a JSON object")
        direction_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        motivation = str(item.get("motivation") or "").strip()
        tradeoff = str(item.get("tradeoff") or "").strip()
        design_brief = item.get("designBrief")
        if not direction_id or direction_id in seen:
            raise ValueError(f"direction {index} must have a unique non-empty id")
        if not label or not motivation or not tradeoff:
            raise ValueError(f"direction {index} must have label, motivation, and tradeoff")
        if not isinstance(design_brief, dict):
            raise ValueError(f"direction {index} must have a DesignBrief")
        validate_design_brief(design_brief)
        seen.add(direction_id)
        result.append({
            "id": direction_id,
            "label": label,
            "motivation": motivation,
            "tradeoff": tradeoff,
            "designBrief": design_brief,
        })
    return result


generate = create_design_brief
