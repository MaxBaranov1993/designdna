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
CACHE_VERSION = "design-brief/1.0"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_design_brief(value: dict) -> dict:
    """Validate the public contract plus references owned by Python code."""
    jsonschema.Draft7Validator(load_schema()).validate(value)
    if value["typePair"] not in typography.ART_DIRECTION_PAIR_NAMES:
        raise ValueError(f"unknown curated typePair: {value['typePair']}")
    return value


def cache_key(brief: Any, product_type: str) -> str:
    canonical = json.dumps(
        {"version": CACHE_VERSION, "brief": brief, "productType": product_type},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _prompt(brief: Any, product_type: str, style_dna: dict | None) -> list[dict]:
    pair_catalog = [
        {"id": name, "display": typography.PAIRS_BY_NAME[name]["display"],
         "body": typography.PAIRS_BY_NAME[name]["body"]}
        for name in typography.ART_DIRECTION_PAIR_NAMES
    ]
    system = (
        "You are the art-direction stage for a product UI generator. Return JSON only, "
        "matching the supplied DesignBrief schema exactly. Settle one bold, coherent aesthetic. "
        "Use exactly one rhythm.risk. Accent hues share the one accent lightness and chroma."
    )
    payload = {
        "brief": brief, "productType": product_type, "styleDNA": style_dna,
        "typePairs": pair_catalog, "schema": load_schema(),
    }
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def create_design_brief(
    brief: Any,
    product_type: str,
    *,
    style_dna: dict | None = None,
    provider: str | None = None,
) -> dict:
    """Create or load a DesignBrief cached by the source brief and product type."""
    if not isinstance(product_type, str) or not product_type.strip():
        raise ValueError("product_type must be a non-empty string")
    key = cache_key(brief, product_type)
    cached = cache_store.get(CACHE_KIND, key)
    if isinstance(cached, dict):
        return deepcopy(validate_design_brief(cached))

    raw = llm.chat(
        provider, _prompt(brief, product_type, style_dna), 0.2,
        timeout=30, role="art-direction", reasoning_effort="medium",
    )
    try:
        result = json.loads(llm.extract_json(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("art direction returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("art direction must return a JSON object")
    validate_design_brief(result)
    cache_store.put(CACHE_KIND, key, result)
    return deepcopy(result)


generate = create_design_brief
