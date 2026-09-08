"""AI-ревью мастеров: одобренный мастер уходит в реестр, отклонённый остаётся
с конкретными дефектами; одобрение агента заменяет попиксельный гейт."""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_system import document as dsdoc
from design_system import master_review


def _png(width: int = 40, height: int = 20) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (20, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _document() -> dict:
    from design_system.builder import _tokens_for_ir, normalize_dna
    master = {"version": "1.1", "tokens": _tokens_for_ir(normalize_dna({})), "tree": [{
        "type": "frame", "sourceKey": "row", "sourceMeta": {"kind": "dom", "componentBoundary": True},
        "frame": {"x": 0, "y": 0, "width": 240, "height": 60, "layout": "free"},
        "children": [{"type": "text", "text": "Sending Engine", "frame": {"x": 0, "y": 0, "width": 200, "height": 20}}],
    }]}
    fidelity = {"basis": "component-source-fidelity-harness", "requiredViewports": ["desktop"],
                "viewports": {"desktop": {"pixelSimilarity": 91.2, "paintCoverage": 99, "bboxP95": 1,
                                          "originError": 0, "unexplainedLosses": 0, "sizeMatch": True,
                                          "sourceGatePassed": True}},
                "status": "needs-review", "reasons": ["desktop: pixel similarity 91.2 < 95"]}
    comp = {"componentKey": "list-item", "name": "List item", "category": "content", "origin": "observed",
            "status": "needs-review", "confirmed": False, "masterIr": master, "fidelity": fidelity,
            "variants": {"default": {"masterRef": "self"}},
            "review": {"kind": "fidelity", "reasons": fidelity["reasons"]},
            "sourceRef": {"sourceKey": "row", "sourceRevisionHash": "rev", "evidenceKey": "ev1",
                          "masterHash": dsdoc.content_hash(master),
                          "bounds": {"x": 0, "y": 0, "width": 240, "height": 60},
                          "boundsByViewport": {"desktop": {"x": 0, "y": 0, "width": 240, "height": 60}}}}
    return {
        "id": "ds-review", "revision": 1, "status": "draft", "components": {},
        "reviewComponents": {"list-item-review": comp},
        "referenceAssets": {"ev1": {
            "referencePreviews": {"desktop": "data:image/png;base64," + base64.b64encode(_png(240, 60)).decode()},
            "blockSizes": {"desktop": {"width": 240, "height": 60}},
        }},
        "foundations": {}, "sourceRefs": [{"revisionHash": "rev"}],
    }


def test_candidates_need_reference_evidence():
    doc = _document()
    assert [key for key, _ in master_review.review_candidates(doc)] == ["list-item-review"]
    doc["referenceAssets"] = {}
    assert master_review.review_candidates(doc) == []


def test_parse_verdict_blocks_on_major_defects_and_low_score():
    ok = master_review.parse_verdict(json.dumps({"approved": True, "score": 92, "summary": "same", "defects": []}))
    assert ok["approved"] and ok["score"] == 92
    major = master_review.parse_verdict(json.dumps({"approved": True, "score": 92, "defects": [
        {"severity": "major", "what": "price wraps to two lines", "where": "bottom row"}]}))
    assert not major["approved"] and major["defects"][0]["where"] == "bottom row"
    low = master_review.parse_verdict('prose before {"approved": true, "score": 60} after')
    assert not low["approved"]


def test_run_approves_and_moves_master_into_registry():
    doc = _document()
    prompts: list[str] = []

    def fake_vision(images, prompt):
        prompts.append(prompt)
        assert len(images) == 2 and images[0].startswith("data:image/jpeg") and images[1].startswith("data:image/png")
        return json.dumps({"approved": True, "score": 96, "summary": "Точная копия", "defects": []})

    updated, results = master_review.run(doc, provider="codex", chat_vision=fake_vision, render=lambda page, comp, vp: _png())
    assert results and results[0]["approved"]
    assert "pixel similarity 91.2" in prompts[0]
    assert "list-item-review" not in updated["reviewComponents"]
    moved = updated["components"]["list-item"]
    assert moved["status"] == "verified" and moved["confirmed"] is True
    assert moved["fidelity"]["aiReview"]["verdict"] == "approved"
    assert dsdoc.component_fidelity_status(moved["fidelity"])["passed"]
    assert not [e for e in dsdoc.validate_document(updated) if e["code"] == "master-fidelity-failed"]
    # оригинальный документ не тронут
    assert "list-item-review" in doc["reviewComponents"]


def test_run_keeps_rejected_master_on_review_with_defects():
    doc = _document()

    def fake_vision(images, prompt):
        return json.dumps({"approved": False, "score": 70, "summary": "Строка цены переносится",
                           "defects": [{"severity": "major", "what": "price wraps", "where": "bottom"}]})

    updated, results = master_review.run(doc, chat_vision=fake_vision, chat_repair=lambda images, prompt: '{"operations": []}',
                                         render=lambda page, comp, vp: _png())
    assert not results[0]["approved"]
    comp = updated["reviewComponents"]["list-item-review"]
    assert comp["status"] == "needs-review"
    assert comp["review"]["reasons"] == ["major: price wraps (bottom)"]
    assert not dsdoc.component_fidelity_status(comp["fidelity"])["passed"]
    assert updated["components"] == {}


def test_run_survives_provider_failure_per_component():
    doc = _document()

    def broken(images, prompt):
        raise RuntimeError("no provider")

    updated, results = master_review.run(doc, chat_vision=broken, render=lambda page, comp, vp: _png())
    assert results[0].get("error", "").startswith("RuntimeError")
    assert "list-item-review" in updated["reviewComponents"]


def test_review_prompt_does_not_attribute_inherited_block_offsets_to_component():
    from design_system.master_review import build_prompt
    comp = {"name": "Card", "fidelity": {"basis": "source-fidelity-harness",
        "viewports": {"desktop": {"bboxP95": 12, "pixelSimilarity": 53.4}}},
        "review": {"reasons": ["block bbox p95 12px"]}}
    prompt = build_prompt(comp, "desktop")
    assert "not measurements of this component" in prompt
    assert "12px" not in prompt and "53.4" not in prompt
    comp["fidelity"]["basis"] = "component-source-fidelity-harness"
    prompt = build_prompt(comp, "desktop")
    assert "12px" in prompt and "53.4" in prompt


def test_fractional_source_bounds_use_same_pixel_edges_without_resizing_master():
    import copy
    comp = _document()["reviewComponents"]["list-item-review"]
    comp["masterIr"]["tree"][0]["frame"].update(width=305.44, height=185)
    comp["sourceRef"]["boundsByViewport"]["desktop"] = {"x": 261.83, "y": 3307.77, "width": 305.44, "height": 185}
    original = copy.deepcopy(comp)
    preview, width, height = master_review.proof_aligned_preview(comp, "desktop")
    assert (width, height) == (306, 185)
    root = preview["tree"][0]
    assert root["frame"]["width"] == 306
    assert abs(root["children"][0]["frame"]["x"] - .83) < 1e-6
    assert abs(root["children"][0]["frame"]["y"] - .77) < 1e-6
    assert root["children"][0]["frame"]["width"] == 305.44
    assert preview["responsive"]["viewports"]["desktop"] == {"width": 306, "height": 185}
    assert comp == original


def test_capture_canvas_does_not_hide_a_resized_master_boundary():
    comp = _document()["reviewComponents"]["list-item-review"]
    comp["masterIr"]["tree"][0]["frame"].update(width=330, height=185)
    comp["sourceRef"]["boundsByViewport"]["desktop"] = {"x": 261.83, "y": 3307.77, "width": 305.44, "height": 185}
    preview, width, height = master_review.proof_aligned_preview(comp, "desktop")
    assert width == 330 and width != 306
    assert preview["tree"][0]["children"][0]["frame"]["width"] == 330
