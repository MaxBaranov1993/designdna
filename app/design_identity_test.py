from __future__ import annotations

import copy

from design_system.compiler import compile_profile
from design_system.document import new_document, validate_document
from design_system.identity import (
    ensure_identity,
    evaluate_identity,
    extract_identity,
    reconstruction_report,
)
from design_system.api import PromoteRequest, ReconstructionRequest, promote_design_identity, run_reconstruction_proof


def sample_ir(*, with_shadow: bool = False) -> dict:
    children = []
    for index in range(24):
        children.append({
            "id": f"text-{index}", "type": "text", "text": "Identity",
            "style": {
                "fontSize": 48 if index == 0 else 16,
                "fontFamily": "Inter", "color": "#111111",
                "borderRadius": 8,
                **({"boxShadow": "0 8px 24px #0003"} if with_shadow and index == 2 else {}),
            },
            "children": [],
        })
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#ffffff", "primary": "#6d4aff"}},
        "tree": [
            {"id": "hero", "type": "section", "frame": {"width": 1200, "height": 600},
             "style": {"background": "#ffffff"}, "children": children},
            {"id": "accent", "type": "section", "frame": {"width": 1200, "height": 120},
             "style": {"background": "#6d4aff"}, "children": []},
        ],
    }


def foundations() -> dict:
    return {
        "colors": {"semantic": {"background": "#ffffff", "primary": "#6d4aff"}, "primitives": {}},
        "typography": {"families": ["Inter"], "scale": {"display": 48, "body": 16}, "weights": [400, 700]},
        "spacing": {"sm": 8, "md": 16}, "radii": [0, 8],
    }


def context(identity: dict, tests: list[dict]) -> dict:
    return {
        "systemRef": {"systemId": "ds-test", "revision": 2, "contentHash": "sha256:test"},
        "foundations": foundations(), "components": [], "identity": identity,
        "identityTests": tests, "constraints": {"usageMode": "strict"},
    }


def test_extract_is_deterministic_and_provenanced():
    blocks = [{"name": "hero", "kind": "hero", "ir": sample_ir()}]
    first = extract_identity(blocks, foundations())
    second = extract_identity(copy.deepcopy(blocks), foundations())
    assert first == second
    identity, tests, measured = first
    assert identity["status"] == "extracted"
    assert 3 <= len(identity["signatures"]) <= 9
    assert measured["displayBodyRatio"] == 3.0
    assert identity["paletteCoverage"]["method"].endswith("top-level-box-area")
    assert all(item.get("provenance") in ("measured", "inferred") for item in identity["signatures"])
    assert any(test["id"] == "identity.surface.no-shadow" for test in tests)


def test_compiler_is_budgeted_hashed_and_stable():
    identity, tests, _ = extract_identity([{"name": "hero", "ir": sample_ir()}], foundations())
    first = compile_profile(context(identity, tests), brief="hero", token_budget=520)
    second = compile_profile(context(identity, tests), brief="hero", token_budget=520)
    assert first == second
    assert first["estimatedTokens"] <= first["tokenBudget"]
    assert first["compiledContextHash"].startswith("sha256:")
    assert "identity.soul" in first["includedRuleIds"]
    assert "identity.test-plan" in first["includedRuleIds"]


def test_application_detects_hard_identity_failure():
    identity, tests, _ = extract_identity([{"name": "hero", "ir": sample_ir()}], foundations())
    report = evaluate_identity(sample_ir(with_shadow=True), identity, tests, foundations())
    assert report["passed"] is False
    assert report["hardFailures"][0]["id"] == "identity.surface.no-shadow"


def test_legacy_document_migrates_without_fake_identity():
    legacy = {"schemaVersion": "design-system/1.0", "components": {}}
    ensure_identity(legacy)
    assert legacy["schemaVersion"] == "design-system/1.1"
    assert legacy["identity"]["status"] == "not-extracted"
    assert legacy["identityTests"] == []


def test_reconstruction_report_uses_same_validator():
    identity, tests, _ = extract_identity([{"name": "hero", "ir": sample_ir()}], foundations())
    document = new_document("Proof")
    document["foundations"] = foundations()
    document["identity"] = identity
    document["identityTests"] = tests
    report = reconstruction_report(document, sample_ir(), proof="transfer")
    assert report["proof"] == "transfer"
    assert report["status"] == "passed"
    assert report["identityScore"] >= 70


def test_identity_schema_rejects_untrusted_hard_ban():
    document = new_document("Invalid")
    document["components"] = {
        "master": {"componentKey": "master", "templateIr": sample_ir(), "dependencies": [], "tokenBindings": {}}
    }
    identity, tests, _ = extract_identity([{"name": "hero", "ir": sample_ir()}], foundations())
    identity["bans"].append({"id": "ban-guess", "rule": "guess", "severity": "hard", "provenance": "inferred", "confidence": 0.4, "confirmed": False})
    document["identity"] = identity
    document["identityTests"] = tests
    errors = validate_document(document)
    assert any(item["code"] == "identity-unconfirmed-hard-ban" for item in errors)


def test_promote_and_proof_persist_in_existing_design_system_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    promoted = promote_design_identity(PromoteRequest(
        name="Accepted identity", sourceNodeId="generator-7", ir=sample_ir()))
    assert promoted["document"]["status"] == "draft"
    assert promoted["summary"]["identityStatus"] == "extracted"
    assert promoted["summary"]["identitySignatures"] >= 3
    proof = run_reconstruction_proof(ReconstructionRequest(
        document=promoted["document"], candidateIr=sample_ir(), proof="source"))
    assert proof["report"]["status"] == "passed"
    assert proof["document"]["reconstruction"]["sourceProof"]["identityScore"] >= 70


def test_taste_memory_records_only_explicit_sanitized_outcomes(tmp_path, monkeypatch):
    import project_store
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "projects.db")
    result = project_store.record_taste_outcome("accepted", {
        "systemId": "ds-test", "ruleIds": ["sig-type-contrast"],
        "prompt": "must never be persisted", "referenceImage": "data:image/png;base64,secret",
    })
    assert result["profile"]["outcomes"]["accepted"] == 1
    assert result["profile"]["accepted_rules"] == ["sig-type-contrast"]
    stored = project_store.load_taste_profile()
    assert "prompt" not in str(stored)
    assert "referenceImage" not in str(stored)
