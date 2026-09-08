from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import blockparse  # noqa: E402
import scraper  # noqa: E402


def _captured_item() -> dict:
    return {
        "ir": {"version": "1.0", "tokens": json.loads((ROOT / "app/fixtures/frame-example.json").read_text(encoding="utf-8"))["tokens"], "tree": [{"id": "hero", "type": "hero", "variant": "centered", "props": {"heading": "Hero", "ctaPrimary": {"text": "Go", "href": "#"}}}]},
        "width": 100,
        "height": 40,
        "layer_count": 1,
        "layers_by_viewport": {"desktop": 1},
        "editable_layers_by_viewport": {"desktop": 1},
        "component_boundaries_by_viewport": {"desktop": 0},
        "coverage": {"desktop": 100},
        "paint_coverage": {"desktop": 100},
    }


def test_font_downloads_are_shared_across_source_blocks(monkeypatch):
    calls = []
    monkeypatch.setattr(scraper, "_download_font", lambda url: calls.append(url) or b"font-bytes")
    monkeypatch.setattr(scraper, "_store_font", lambda _data: "font.woff2")
    faces = [{"family": "Inter", "weight": "400", "style": "normal", "urls": ["https://cdn.example/inter.woff2"]}]
    cache = {}

    first = scraper._resolve_font_faces(faces, {"inter"}, download_cache=cache)
    second = scraper._resolve_font_faces(faces, {"inter"}, download_cache=cache)

    assert first == second
    assert calls == ["https://cdn.example/inter.woff2"]


def test_parse_blocks_returns_measured_stage_diagnostics(monkeypatch, capsys):
    monkeypatch.setattr(
        blockparse,
        "capture_block_irs",
        lambda *_args, **_kwargs: ({"#hero": _captured_item()}, {"mode": "light"}),
    )
    monkeypatch.setattr(blockparse, "_validate", lambda _doc: [])
    monkeypatch.setattr(blockparse, "enrich_ir", lambda doc, **_kwargs: doc)
    monkeypatch.setattr(blockparse, "ensure_current_ir", lambda doc, **_kwargs: doc)
    monkeypatch.setattr(blockparse, "build_parser_envelope", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(blockparse.fidelity_harness, "is_raster_fallback", lambda _doc: False)
    monkeypatch.setattr(blockparse.fidelity_harness, "evaluate_captures", lambda _items: {})
    monkeypatch.setattr(blockparse.cache_store, "put_gated", lambda *_args, **_kwargs: None)

    stages = []
    result = blockparse.parse_blocks(
        "https://example.com",
        blocks=[{"name": "hero", "selector": "#hero"}],
        on_stage=lambda name, duration, timings: stages.append((name, duration, timings)),
    )

    timings = result["diagnostics"]["timingsMs"]
    assert result["cached"] is False
    assert result["diagnostics"]["pipelineVersion"] == blockparse.SOURCE_COMPILER_VERSION
    assert {"prepare", "cacheLookup", "captureCompile", "assemble", "fidelity", "cacheWrite", "total"} <= set(timings)
    assert all(isinstance(value, int) and value >= 0 for value in timings.values())
    assert [stage[0] for stage in stages] == [
        "prepare", "cacheLookup", "captureCompile", "assemble", "fidelity", "cacheWrite",
    ]
    assert stages[-1][2]["cacheWrite"] == timings["cacheWrite"]

    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert event["event"] == "source_import.completed"
    assert event["blockCount"] == 1
    assert event["timingsMs"] == timings


def test_cache_hit_has_fresh_lookup_and_total_timings(monkeypatch, capsys):
    cached_payload = {
        "url": "https://example.com",
        "blocks": [{"name": "hero", "selector": "#hero", "ir": {}}],
        "tokens": {},
        "authenticated": False,
    }
    monkeypatch.setattr(blockparse.cache_store, "get", lambda *_args, **_kwargs: cached_payload)

    result = blockparse.parse_blocks("https://example.com")

    assert result["cached"] is True
    assert set(result["diagnostics"]["timingsMs"]) == {"prepare", "cacheLookup", "total"}
    assert "diagnostics" not in cached_payload
    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert event["cached"] is True


def test_auto_detection_uses_single_capture_fast_path_without_llm(monkeypatch):
    calls = []
    detected = [{"name": "hero", "selector": "#hero", "kind": "header", "label": "Hero"}]

    def capture(url, blocks, **kwargs):
        calls.append({"url": url, "blocks": blocks, **kwargs})
        assert blocks is None
        assert kwargs["return_blocks"] is True
        return {"#hero": _captured_item()}, {"mode": "light"}, detected

    monkeypatch.setattr(blockparse.cache_store, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(blockparse, "capture_block_irs", capture)
    monkeypatch.setattr(blockparse, "rendered_html", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("second navigation")))
    monkeypatch.setattr(blockparse.llm, "chat", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM in Source critical path")))
    monkeypatch.setattr(blockparse, "_validate", lambda _doc: [])
    monkeypatch.setattr(blockparse, "enrich_ir", lambda doc, **_kwargs: doc)
    monkeypatch.setattr(blockparse, "ensure_current_ir", lambda doc, **_kwargs: doc)
    monkeypatch.setattr(blockparse, "build_parser_envelope", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(blockparse.fidelity_harness, "is_raster_fallback", lambda _doc: False)
    monkeypatch.setattr(blockparse.fidelity_harness, "evaluate_captures", lambda _items: {
        "#hero": {"viewports": {"desktop": {
            "pixel_similarity": 0.96, "paint_coverage": 0.99, "bbox_p95": 1.5,
        }}, "gate": {"passed": True}},
    })
    monkeypatch.setattr(blockparse.cache_store, "put_gated", lambda *_args, **_kwargs: None)

    result = blockparse.parse_blocks("https://example.com")

    assert len(calls) == 1
    assert result["blocks"][0]["kind"] == "header"
    assert result["blocks"][0]["fidelity"] == {"desktop": 0.96}
    assert result["blocks"][0]["paintCoverage"] == {"desktop": 0.99}
    assert result["blocks"][0]["p95LayoutError"] == {"desktop": 1.5}
    artifact = result["sourceArtifact"]
    assert artifact["version"] == "source-artifact/1.0"
    assert {key: artifact["summary"][key] for key in (
        "screenCount", "componentCount", "componentSetCount", "variantCount",
        "observedStateCount", "viewportCount",
    )} == {
        "screenCount": 1,
        "componentCount": 1,
        "componentSetCount": 1,
        "variantCount": 1,
        "observedStateCount": 1,
        "viewportCount": 1,
    }
    assert artifact["summary"]["tokenGroupCount"] == len(artifact["foundations"]["groups"])
    assert artifact["summary"]["tokenCount"] == sum(
        group["tokenCount"] for group in artifact["foundations"]["groups"]
    )
    assert artifact["summary"]["tokenCount"] > 0
    assert artifact["library"] == {
        "componentSetCount": 1, "variantCount": 1, "observedStateCount": 1,
    }
    assert artifact["screens"][0]["name"] == "100w light"
    assert artifact["screens"][0]["basis"] == "assembled-from-source-blocks"
    assert artifact["screens"][0]["size"] == {"width": 100, "height": 40}
    assert artifact["screens"][0]["componentKeys"] == [artifact["components"][0]["componentKey"]]
    assert artifact["screens"][0]["metrics"]["fidelityMean"] == 0.96
    assert artifact["components"][0]["master"]["blockIndex"] == 0
    assert artifact["components"][0]["states"]["default"]["basis"] == "measured"
    assert artifact["components"][0]["responsive"]["desktop"]["fidelity"] == 0.96
    timings = result["diagnostics"]["timingsMs"]
    assert "semanticRefine" not in timings
    assert "renderDom" not in timings


def test_source_artifact_assembles_ordered_responsive_screens_without_ir_copies():
    def source_block(name, selector, source_id, heights, fidelity):
        return {
            "name": name,
            "label": name.title(),
            "kind": "section",
            "selector": selector,
            "ir": {"version": "1.0", "tree": [{"type": "section", "name": name}]},
            "sizes": {
                "desktop": {"width": 1200, "height": heights[0]},
                "mobile": {"width": 390, "height": heights[1]},
            },
            "layersByViewport": {"desktop": 10, "mobile": 8},
            "editableLayersByViewport": {"desktop": 9, "mobile": 7},
            "fidelity": {"desktop": fidelity[0], "mobile": fidelity[1]},
            "p95LayoutError": {"desktop": 1.0, "mobile": 2.0},
            "parserContract": {
                "version": "parser-source/1.0",
                "sourceRecord": {"id": source_id},
                "nodeStates": {"root": {}},
            },
        }

    artifact = blockparse._build_source_artifact(
        "https://example.com",
        [
            source_block("header", "header", "source:header", (100, 80), (0.98, 0.96)),
            source_block("main", "main", "source:main", (200, 150), (0.82, 0.78)),
        ],
        {"color": {"brand": "#7018e6"}, "spacing": {"sm": 4}},
        False,
    )

    assert [screen["viewport"] for screen in artifact["screens"]] == ["desktop", "mobile"]
    desktop = artifact["screens"][0]
    assert desktop["size"] == {"width": 1200, "height": 300}
    assert desktop["componentKeys"] == ["source:header", "source:main"]
    assert [item["selector"] for item in desktop["hierarchy"]] == ["header", "main"]
    assert desktop["metrics"] == {
        "layers": 20,
        "editableLayers": 18,
        "fidelityMean": 0.9,
        "fidelityMin": 0.82,
        "p95LayoutErrorMax": 1.0,
    }
    assert artifact["library"]["componentSetCount"] == 2
    assert artifact["summary"]["tokenGroupCount"] == 2
    assert all("ir" not in component for component in artifact["components"])
