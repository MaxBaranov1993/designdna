from __future__ import annotations

import json

from design_system.organizer import deterministic_catalog, organize_with_ai


def _component(key: str, category: str, *, status: str = "verified") -> dict:
    return {
        "componentKey": key,
        "canonicalRole": key,
        "name": key.replace("-", " ").title(),
        "category": category,
        "status": status,
        "origin": "observed",
        "variants": {"default": {"label": "Default", "observedCount": 1}},
        "fidelity": {"reasons": ["desktop: bbox p95 8 > 4px"]} if status != "verified" else {},
    }


def _document() -> dict:
    return {
        "components": {
            "button": _component("button", "actions"),
            "header-actions": _component("header-actions", "navigation"),
            "service-card": _component("service-card", "surfaces"),
        },
        "reviewComponents": {
            "footer-navigation": _component("footer-navigation", "navigation", status="needs-review"),
        },
        "suggestions": {},
    }


def test_deterministic_catalog_has_stable_ui_kit_sections():
    catalog = deterministic_catalog(_document())
    sections = {section["key"]: section["componentKeys"] for section in catalog["sections"]}
    assert sections["header-navigation"] == ["header-actions"]
    assert sections["actions"] == ["button"]
    assert sections["cards"] == ["service-card"]
    assert sections["footer"] == ["footer-navigation"]
    assert catalog["componentMeta"]["footer-navigation"]["qualityAction"] == "review-source-fidelity"


def test_ai_plan_cannot_drop_master_or_override_fidelity():
    class FakeLlm:
        @staticmethod
        def chat(*args, **kwargs):
            # Deliberately omit two keys and try to imply a review master is OK.
            return json.dumps({"components": [
                {"key": "header-actions", "sectionKey": "header-navigation", "family": "header",
                 "role": "site header", "label": "Header", "order": 1, "confidence": .95,
                 "rationale": "global navigation"},
                {"key": "footer-navigation", "sectionKey": "header-navigation", "family": "footer",
                 "role": "footer", "label": "Footer", "order": 99, "confidence": .7,
                 "rationale": "model proposal", "qualityAction": "keep"},
                {"key": "invented", "sectionKey": "cards", "label": "Invented"},
            ]})

        @staticmethod
        def extract_json(raw):
            return raw

    catalog = organize_with_ai(_document(), reasoning_effort="max", llm_module=FakeLlm)
    assert set(catalog["componentMeta"]) == {
        "button", "header-actions", "service-card", "footer-navigation",
    }
    assert catalog["componentMeta"]["footer-navigation"]["qualityAction"] == "review-source-fidelity"
    assert catalog["componentMeta"]["button"]["sectionKey"] == "actions"
    assert catalog["organizer"] == {
        "kind": "ai", "model": "gpt-5.6-sol", "reasoningEffort": "max",
    }


def test_only_supported_sol_efforts_are_accepted():
    try:
        organize_with_ai(_document(), reasoning_effort="low", llm_module=object())
    except ValueError as exc:
        assert "medium, high or max" in str(exc)
    else:
        raise AssertionError("unsupported effort was accepted")
