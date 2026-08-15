"""Contract tests for the opt-in Design IR 2.0 composition foundation."""
from __future__ import annotations

from copy import deepcopy

from app.ir.composition import CompositionContract, SemanticChangeSet
from app.ir.schema import CURRENT_SCHEMA_VERSION, LATEST_SCHEMA_VERSION, load_schema
from app.ir.validate import validate_change_set, validate_ir


def _tokens() -> dict:
    return {
        "mode": "light",
        "color": {
            "primary": "#6d28d9",
            "background": "#ffffff",
            "surface": "#f8fafc",
            "text": "#111827",
            "textMuted": "#64748b",
            "border": "#e2e8f0",
        },
        "font": {
            "display": {"family": "Inter", "weight": 700},
            "body": {"family": "Inter", "weight": 400},
            "scale": "default",
        },
        "radius": {"card": "lg", "button": "md", "input": "md"},
        "spacing": {"section": "lg", "container": "default"},
        "shadow": "sm",
    }


def valid_ir() -> dict:
    return {
        "version": "2.0",
        "tokens": _tokens(),
        "tree": [
            {
                "id": "header-main",
                "sourceKey": "source-a::header",
                "type": "navbar",
                "variant": "default",
                "frame": {"width": "fill", "contentMaxWidth": 1200, "contentGutter": 32},
                "props": {
                    "logoText": "DesignDNA",
                    "links": [{"label": "Product", "href": "#product"}],
                    "cta": {"text": "Start"},
                },
            },
            {
                "id": "hero-main",
                "sourceKey": "source-b::hero",
                "type": "hero",
                "variant": "split",
                "props": {
                    "heading": "Compose interfaces without visual seams",
                    "ctaPrimary": {"text": "Build"},
                },
            },
        ],
        "composition": {
            "schemaVersion": "composition/1.0",
            "revision": {
                "id": "revision-1",
                "createdAt": "2026-08-15T10:00:00Z",
                "actor": "test",
            },
            "sourceRegistry": {
                "source-a": {
                    "id": "source-a",
                    "kind": "url",
                    "label": "Imported header",
                    "ref": "https://example.com/header",
                    "fingerprint": "sha256:header",
                    "colorToken": "source-blue",
                    "symbol": "A",
                    "capturedAt": "2026-08-15T09:00:00Z",
                    "parserVersion": "2.0.0",
                    "confidence": 0.98,
                },
                "source-b": {
                    "id": "source-b",
                    "kind": "manual",
                    "label": "Custom hero",
                    "fingerprint": "manual:hero",
                    "colorToken": "source-orange",
                    "symbol": "B",
                    "capturedAt": "2026-08-15T09:30:00Z",
                    "parserVersion": "manual/1",
                    "confidence": 1,
                },
            },
            "layoutAxes": {
                "page-content": {
                    "id": "page-content",
                    "role": "page-content",
                    "maxWidth": {"desktop": 1200, "tablet": 960, "mobile": 640},
                    "inlineGutter": {"desktop": 32, "tablet": 24, "mobile": 16},
                    "alignment": "center",
                    "members": [
                        {"nodeRef": "header-main", "anchor": "inner-content"},
                        {"nodeRef": "hero-main", "anchor": "inner-content"},
                    ],
                }
            },
            "nodeStates": {
                "header-main": {
                    "provenance": {
                        "primarySourceId": "source-a",
                        "facets": {
                            "structure": {"sourceId": "source-a", "confidence": 0.98},
                            "appearance": {"sourceId": "source-a", "confidence": 0.94},
                        },
                    },
                    "axisBindings": [
                        {"axisId": "page-content", "anchor": "inner-content"}
                    ],
                    "locks": ["brand"],
                    "status": ["linked"],
                },
                "hero-main": {
                    "provenance": {
                        "primarySourceId": "source-b",
                        "facets": {
                            "structure": {"sourceId": "source-b", "confidence": 1},
                            "content": {"sourceId": "source-b", "confidence": 1},
                        },
                    },
                    "axisBindings": [
                        {"axisId": "page-content", "anchor": "inner-content"}
                    ],
                    "status": ["modified"],
                },
            },
            "documentLocks": ["source-link"],
        },
    }


def valid_change_set() -> dict:
    return {
        "version": "semantic-change-set/1.0",
        "id": "align-width-1",
        "baseRevisionId": "revision-1",
        "baseDocumentHash": "0123456789abcdef",
        "intent": "Align header and hero to the page content axis",
        "scope": ["header-main", "hero-main"],
        "preconditions": [
            {"kind": "revision-match", "expected": "revision-1"},
            {"kind": "lock-absent", "target": "hero-main", "expected": "layout"},
        ],
        "operations": [
            {
                "id": "bind-hero-axis",
                "kind": "bind-layout-axis",
                "target": "hero-main",
                "payload": {"axisId": "page-content", "anchor": "inner-content"},
            }
        ],
        "inverseOperations": [
            {
                "id": "unbind-hero-axis",
                "inverseOf": "bind-hero-axis",
                "kind": "unbind-layout-axis",
                "target": "hero-main",
                "payload": {"axisId": "page-content", "anchor": "inner-content"},
            }
        ],
        "validations": [
            {"kind": "schema", "status": "passed"},
            {"kind": "responsive", "status": "pending", "viewport": "mobile"},
        ],
        "atomic": True,
        "status": "validated",
        "actor": "layout-director",
        "createdAt": "2026-08-15T10:05:00Z",
    }


def test_v2_schema_is_opt_in_and_runtime_stays_on_1_1() -> None:
    assert CURRENT_SCHEMA_VERSION == "1.1"
    assert LATEST_SCHEMA_VERSION == "2.0"
    assert load_schema("2.0")["$id"].endswith("/2.0")


def test_valid_v2_document_passes_schema_and_semantic_validation() -> None:
    value = valid_ir()
    assert validate_ir(value) == []
    contract = CompositionContract.model_validate(value["composition"])
    assert contract.layout_axes["page-content"].members[0].node_ref == "header-main"


def test_unknown_provenance_source_is_rejected() -> None:
    value = valid_ir()
    value["composition"]["nodeStates"]["hero-main"]["provenance"]["facets"]["content"]["sourceId"] = "source-missing"
    errors = validate_ir(value)
    assert errors
    assert "unknown sources" in errors[0].message


def test_dangling_layout_member_is_rejected() -> None:
    value = valid_ir()
    value["composition"]["layoutAxes"]["page-content"]["members"].append(
        {"nodeRef": "missing-section", "anchor": "inner-content"}
    )
    errors = validate_ir(value)
    assert any("does not exist in tree" in error.message for error in errors)


def test_change_set_is_schema_valid_typed_and_reversible() -> None:
    value = valid_change_set()
    assert validate_change_set(value) == []
    contract = SemanticChangeSet.model_validate(value)
    assert contract.atomic is True
    assert contract.operations[0].target == "hero-main"
    assert contract.inverse_operations


def test_change_set_without_inverse_is_rejected() -> None:
    value = deepcopy(valid_change_set())
    value["inverseOperations"] = []
    errors = validate_change_set(value)
    assert errors
    assert any("non-empty" in error.message for error in errors)


def test_change_set_requires_explicit_inverse_coverage() -> None:
    value = deepcopy(valid_change_set())
    value["inverseOperations"][0].pop("inverseOf")
    errors = validate_change_set(value)
    assert errors
    assert any("must declare inverseOf" in error.message for error in errors)
