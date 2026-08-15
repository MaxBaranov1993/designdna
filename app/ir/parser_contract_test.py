"""Contract tests for deterministic Parser v2 source metadata."""
from __future__ import annotations

from datetime import datetime, timezone

from app.ir.parser_contract import build_parser_envelope, normalize_source_ref, stable_source_id
from app.ir.validate import validate_parser_envelope


def sample_ir() -> dict:
    return {
        "version": "1.1",
        "tokens": {},
        "tree": [
            {
                "id": "imported-block",
                "sourceKey": "root",
                "type": "source-block",
                "variant": "dom-capture",
                "frame": {"width": 1200, "height": 420, "layout": "free"},
                "props": {},
                "children": [
                    {
                        "sourceKey": "root/content:1",
                        "type": "container",
                        "frame": {"x": 120, "y": 20, "width": 960, "height": 380},
                        "style": {"background": "#ffffff"},
                        "children": [
                            {
                                "sourceKey": "root/content:1/heading:1",
                                "type": "heading",
                                "text": "Parser v2",
                                "frame": {"width": 420, "height": 64},
                            },
                            {
                                "sourceKey": "root/content:1/button:1",
                                "type": "button",
                                "props": {"href": "#start", "label": "Start"},
                                "frame": {"width": 120, "height": 44},
                            },
                        ],
                    }
                ],
            }
        ],
    }


def capture() -> dict:
    return {
        "preview": "data:image/jpeg;base64,preview",
        "sizes": {
            "desktop": {"width": 1200, "height": 420},
            "tablet": {"width": 768, "height": 480},
            "mobile": {"width": 390, "height": 640},
        },
        "layersByViewport": {"desktop": 12, "tablet": 12, "mobile": 10},
        "coverage": {"desktop": 98, "tablet": 96, "mobile": 92},
        "fidelity": {"desktop": 0.97, "tablet": 0.95, "mobile": 0.9},
        "warnings": [],
    }


def test_source_identity_is_stable_and_fragment_independent() -> None:
    first = stable_source_id("HTTPS://Example.com/catalog/#hero", "header.site")
    second = stable_source_id("https://example.com/catalog", "header.site")
    assert first == second
    assert first != stable_source_id("https://example.com/catalog", "main.hero")
    assert normalize_source_ref("HTTPS://Example.com/catalog/#hero") == "https://example.com/catalog"


def test_image_and_url_sources_have_separate_identity_namespaces() -> None:
    url_source = stable_source_id("https://example.com/capture", "screenshot")
    image_source = stable_source_id("https://example.com/capture", "screenshot", "image")
    assert url_source != image_source
    value = build_parser_envelope(
        sample_ir(),
        url="image-sha256:0123456789abcdef",
        selector="screenshot",
        label="Uploaded screenshot",
        parser_version="vision-v2",
        kind="image",
        capture={},
    )
    assert value["sourceRecord"]["kind"] == "image"
    assert value["sourceRecord"]["ref"] == "image-sha256:0123456789abcdef"


def test_parser_envelope_passes_schema_and_carries_facet_provenance() -> None:
    value = build_parser_envelope(
        sample_ir(),
        url="https://example.com/catalog",
        selector="main.hero",
        label="Hero",
        parser_version="dom-v22",
        capture=capture(),
        captured_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    assert validate_parser_envelope(value) == []
    source_id = value["sourceRecord"]["id"]
    assert value["nodeStates"]["root/content:1/button:1"]["provenance"]["primarySourceId"] == source_id
    facets = value["nodeStates"]["root/content:1/button:1"]["provenance"]["facets"]
    assert set(facets) >= {"structure", "appearance", "content", "interaction"}
    assert value["sourceRecord"]["parserVersion"] == "dom-v22"


def test_parser_emits_measured_outer_and_inferred_content_axes() -> None:
    value = build_parser_envelope(
        sample_ir(),
        url="https://example.com/catalog",
        selector="main.hero",
        label="Hero",
        parser_version="dom-v22",
        capture=capture(),
    )
    roles = {(item["role"], item["viewport"]): item for item in value["layoutEvidence"]}
    assert roles[("full-bleed", "desktop")]["maxWidth"] == 1200
    content = roles[("page-content", "desktop")]
    assert content["maxWidth"] == 960
    assert content["inlineGutter"] == 120
    assert content["basis"] == "inferred"


def test_low_capture_quality_is_visible_and_marks_nodes() -> None:
    weak = capture()
    weak["coverage"] = {"desktop": 48}
    weak["fidelity"] = {"desktop": 0.52}
    weak["warnings"] = ["font fallback", "clipped layer"]
    value = build_parser_envelope(
        sample_ir(),
        url="https://example.com/catalog",
        selector="main.hero",
        label="Hero",
        parser_version="dom-v22",
        capture=weak,
    )
    assert value["sourceRecord"]["confidence"] < 0.75
    assert "low-confidence" in value["nodeStates"]["root"]["status"]
    codes = [item["code"] for item in value["diagnostics"]]
    assert codes.count("capture-warning") == 2
    assert "low-coverage" in codes


def test_parser_schema_rejects_dangling_layout_evidence() -> None:
    value = build_parser_envelope(
        sample_ir(),
        url="https://example.com/catalog",
        selector="main.hero",
        label="Hero",
        parser_version="dom-v22",
        capture=capture(),
    )
    value["layoutEvidence"][0]["nodeRef"] = "missing"
    errors = validate_parser_envelope(value)
    assert any("unknown nodes" in error.message for error in errors)
