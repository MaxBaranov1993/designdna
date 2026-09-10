"""Reference roles survive prepare/finalize; composition images cannot become final pixels."""
import base64
import copy
import io
import json

import pytest
from PIL import Image
from fastapi.testclient import TestClient

import server
import visual_reference
from api import quality
from asset_plan import apply, prepare, store_image
from asset_quality import audit, preserves_resources
from quality_pass_test import HIGH_JUDGE
from test_qualitygate import BASE_IR


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    cache = {}
    monkeypatch.setattr(server.cache_store, "get", lambda kind, key: copy.deepcopy(cache.get((kind, key))))
    monkeypatch.setattr(server.cache_store, "put", lambda kind, key, value: cache.__setitem__((kind, key), copy.deepcopy(value)))
    monkeypatch.setattr(server.project_store, "build_prompt_memory_hint", lambda: "")
    monkeypatch.setattr(server.project_rules, "prompt_block", lambda *_: "")
    monkeypatch.setattr(server.llm, "chat", lambda *_a, **_kw: pytest.fail("Unexpected AI call"))


def png(color="blue"):
    output = io.BytesIO()
    Image.new("RGB", (96, 64), color).save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize("role", ["style", "composition", "reproduce"])
@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_visual_reference_reaches_prepared_provider_messages_and_binds_receipt(role, provider):
    request = dict(brief="Форма настроек", surface="form", provider=provider, count=1,
                   visualReference={"image": png(), "role": role, "origin": "upload.png"})
    first = server.generate(server.GenerateReq(**request, prepareOnly=True))
    content = first["prompts"][0]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[-1]["type"] == "image_url"
    assert f"Visual reference: {role}" in content[0]["text"]
    assert "masterHash" in content[0]["text"]
    request["visualReference"]["role"] = "style" if role != "style" else "composition"
    stale = server.generate(server.GenerateReq(**request, rawOutputs=[json.dumps(BASE_IR)], preparedContextId=first["preparedContextId"]))
    assert stale.status_code == 409


def test_invalid_reference_and_missing_design_system_are_not_accepted():
    client = TestClient(server.app)
    assert client.post("/api/generate", json={"brief": "Form", "prepareOnly": True,
        "visualReference": {"image": "https://example.test/image.png"}}).status_code == 422
    assert client.post("/api/generate/concept/prepare", json={"brief": "Form", "designSystem": {
        "systemId": "missing", "revision": 9}}).status_code == 422
    assert client.post("/api/generate/concept/store", json={"image": "data:image/png;base64,AAAA"}).status_code == 422


def test_concept_stored_separately_and_forbidden_as_final_resource():
    client = TestClient(server.app)
    stored = client.post("/api/generate/concept/store", json={"image": png()}).json()
    assert stored["conceptOnly"] is True
    reference = visual_reference.prepare(visual_reference.VisualReference(image=png(), role="composition", conceptOnly=True))
    ir = {"tree": [{"type": "image", "imagePrompt": "Standalone object"}]}
    plan = prepare([ir], {"conceptHash": stored["result"]["sha256"]})
    with pytest.raises(ValueError, match="Эскиз"):
        apply(ir, plan["slots"][0], png())
    assert visual_reference.concept_used_in_output({"tree": [{"src": stored["result"]["src"]}]}, reference)
    actual = apply(ir, plan["slots"][0], png("red"))
    assert not visual_reference.concept_used_in_output(actual["ir"], reference)
    assert audit(actual["ir"])["status"] == "pass"


def test_resource_quality_detects_missing_files_and_keeps_editing_unknown(tmp_path):
    result = store_image(png())
    ir = {"tree": [{"type": "composition", "children": [{"type": "text", "text": "Цена 1490 ₽"},
        {"type": "image", "src": result["src"], "frame": {"width": 500}}]}]}
    report = audit(ir)
    assert report["status"] == "pass" and report["warnings"]
    assert report["nativeTextCount"] == 1 and set(report["checks"].values()) == {"unknown"}
    (tmp_path / "blobs" / (result["sha256"] + ".png")).unlink()
    assert audit(ir)["status"] == "fail"


def test_quality_pass_cannot_pass_with_missing_image_despite_high_score():
    ir = copy.deepcopy(BASE_IR)
    next(node for node in ir["tree"] if node["type"] == "hero")["props"]["media"] = {"imagePrompt": "Missing photo"}
    judge = json.loads(HIGH_JUDGE)
    result = quality._quality_finish(server.QualityPassReq(ir=ir, repair=False), ir, judge, judge,
        {"attempted": False, "applied": False, "error": None}, visual=True)
    assert result["passed"] is False
    assert result["acceptance"]["checks"]["resources"] == "fail"
    assert result["resourceEvidence"]["errors"]


def test_repair_can_move_images_but_cannot_remove_or_replace_them():
    result = store_image(png())
    before = {"tree": [{"type": "image", "src": result["src"]}]}
    expanded = {"tree": [{"type": "composition", "children": [{"type": "image", "src": visual_reference.prepare(
        visual_reference.VisualReference(image=png()))["part"]["image_url"]["url"]}]}]}
    assert preserves_resources(before, expanded)
    assert not preserves_resources(before, {"tree": []})
    assert not preserves_resources(before, {"tree": [{"type": "image", "src": png("red")}]})


def test_unknown_external_resource_cannot_claim_passed_from_a_screenshot_alone():
    judge = json.loads(HIGH_JUDGE)
    result = quality._quality_finish(server.QualityPassReq(ir=BASE_IR, repair=False), BASE_IR, judge, judge,
        {"attempted": False, "applied": False, "error": None}, visual=True)
    assert result["passed"] is False
    assert result["acceptance"]["status"] == "unverified"
    assert result["resourceEvidence"]["status"] == "unknown"
