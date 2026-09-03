from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import typography


SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "schema" / "design-brief.schema.json")
    .read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft7Validator(SCHEMA)


def sample() -> dict:
    return {
        "schemaVersion": "design-brief/1.0",
        "audience": {"primary": "Independent restaurant owners", "task": "Book a demo"},
        "tone": "editorial",
        "typePair": "fraunces-newsreader",
        "palette": {
            "background": {"lightness": 0.96, "chroma": 0.015, "hue": 80},
            "accent": {"lightness": 0.62, "chroma": 0.16, "hues": [35, 190]},
        },
        "rhythm": {
            "sections": [
                {"purpose": "promise", "density": "airy"},
                {"purpose": "proof", "density": "dense"},
                {"purpose": "conversion", "density": "balanced"},
            ],
            "risk": "Oversized editorial headline overlaps the hero image edge",
        },
        "copyDeck": {"hero": "A full dining room, before service starts", "cta": "Book a demo",
                     "proofs": ["1,200 weekly reservations"]},
    }


def test_design_brief_schema_accepts_complete_contract() -> None:
    jsonschema.Draft7Validator.check_schema(SCHEMA)
    assert list(VALIDATOR.iter_errors(sample())) == []


def test_schema_rejects_freeform_tone_and_second_risk() -> None:
    value = sample()
    value["tone"] = "generic modern"
    value["rhythm"]["risks"] = ["another risk"]
    messages = [error.message for error in VALIDATOR.iter_errors(value)]
    assert any("is not one of" in message for message in messages)
    assert any("Additional properties" in message for message in messages)


def test_accent_seed_has_one_or_two_shared_tone_hues() -> None:
    value = sample()
    value["palette"]["accent"]["hues"] = [10, 20, 30]
    assert any(error.validator == "maxItems" for error in VALIDATOR.iter_errors(value))


def test_schema_type_pairs_match_distinctive_catalog_with_fallbacks() -> None:
    assert tuple(SCHEMA["properties"]["typePair"]["enum"]) == typography.ART_DIRECTION_PAIR_NAMES
    for name in typography.ART_DIRECTION_PAIR_NAMES:
        pair = typography.PAIRS_BY_NAME[name]
        for role in ("display", "body"):
            assert "system-ui" in pair[role]["stack"]
            assert all(generic not in pair[role]["family"] for generic in ("Inter", "Roboto", "Arial"))
