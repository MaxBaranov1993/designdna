"""Subscription DS staging contract and fail-closed review/repair acceptance."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_system import desktop_ai as ai, document as dsdoc, store
from design_system_master_review_test import _document, _png


def document(count=1):
    doc = _document()
    doc["name"] = "Desktop subscription test"
    comp = doc["reviewComponents"]["list-item-review"]
    comp["masterIr"]["tree"][0]["style"] = {"background": "#ffffff"}
    comp["sourceRef"]["masterHash"] = dsdoc.content_hash(comp["masterIr"])
    for viewport in ai.VIEWPORTS[1:]:
        comp["sourceRef"]["boundsByViewport"][viewport] = copy.deepcopy(comp["sourceRef"]["bounds"])
        ev = doc["referenceAssets"]["ev1"]
        ev["referencePreviews"][viewport] = ev["referencePreviews"]["desktop"]
        ev["blockSizes"][viewport] = copy.deepcopy(ev["blockSizes"]["desktop"])
    for i in range(1, count):
        clone = copy.deepcopy(comp)
        clone["componentKey"] = f"list-item-{i}"
        doc["reviewComponents"][f"list-item-review-{i}"] = clone
    return doc


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    ai._PREPARATIONS.clear()

    def forbidden(*args, **kwargs):
        pytest.fail("Subscription staging must never call a provider API")

    monkeypatch.setitem(sys.modules, "llm_client", SimpleNamespace(chat=forbidden, chat_vision=forbidden))

    @contextmanager
    def renderer(render=None):
        yield None, render or (lambda page, comp, viewport: _png(240, 60))

    monkeypatch.setattr(ai, "_renderer", renderer)
    yield
    ai._PREPARATIONS.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ai.router)
    return TestClient(app)


def prepare(doc=None, operation="master-review", **kwargs):
    return ai.prepare(ai.PrepareRequest(document=doc or document(), operation=operation, provider="codex", **kwargs))


def verdict(approved=True, **changes):
    return {"approved": approved, "score": 96 if approved else 60,
            "summary": "Matches Source" if approved else "Wrong surface color",
            "defects": [] if approved else [{"severity": "major", "what": "Wrong surface color", "where": "row"}],
            **changes}


def apply(prepared, doc, outputs=None):
    responses = []
    for task in prepared["tasks"]:
        if task["status"] == "ready":
            value = outputs(task) if callable(outputs) else outputs or verdict()
            responses.append({"taskId": task["id"], "output": value if isinstance(value, str) else json.dumps(value)})
    return ai.apply(ai.ApplyRequest(prepareId=prepared["prepareId"], documentHash=prepared["documentHash"],
                                  document=doc, responses=responses))


def organizer_output(doc):
    return {"components": [{"key": key, "sectionKey": "content", "family": "List", "role": "list-item",
                            "label": "List item", "order": i, "confidence": .95, "rationale": "Measured role"}
                           for i, key in enumerate(ai.organizer._catalog_components(doc))]}


def repair_output():
    return {"operations": [{"op": "restore-style", "sourceKey": "row", "property": "background", "value": "#eeeeee"}]}


def test_router_exact_contract_and_provider_restriction(client):
    response = client.post("/api/design-system/desktop-ai/prepare", json={
        "document": document(), "operation": "organize", "provider": "claude"})
    assert response.status_code == 200
    prepared = response.json()
    assert set(prepared) == {"prepareId", "documentHash", "operation", "provider", "reasoningEffort", "stage", "tasks", "expiresAt"}
    assert prepared["provider"] == "claude" and prepared["stage"] == "organize"
    assert set(prepared["tasks"][0]) == {"id", "kind", "componentKey", "viewport", "status", "messages", "reason"}
    assert prepared["tasks"][0]["messages"][0]["role"] == "system"
    result = client.post("/api/design-system/desktop-ai/apply", json={
        "document": document(), "prepareId": prepared["prepareId"], "documentHash": prepared["documentHash"],
        "responses": [{"taskId": prepared["tasks"][0]["id"], "output": json.dumps(organizer_output(document()))}]})
    assert result.status_code == 200, result.text
    assert set(result.json()) == {"document", "summary", "results", "complete", "nextPreparation"}
    for provider in ("auto", "unknown", "", None):
        bad = client.post("/api/design-system/desktop-ai/prepare", json={
            "document": document(), "operation": "organize", "provider": provider})
        assert bad.status_code == 422


def test_organize_metadata_only_real_persistence_and_single_use():
    doc = document()
    before = copy.deepcopy(doc)
    prepared = prepare(doc, "organize")
    result = apply(prepared, doc, organizer_output(doc))
    saved = result["document"]
    assert doc == before
    assert saved["reviewComponents"] == before["reviewComponents"]
    assert saved["catalog"]["organizer"]["provider"] == "codex"
    assert saved["catalog"]["organizer"]["model"] is None
    assert saved["status"] == "draft" and result["complete"] and result["nextPreparation"] is None
    assert store.get_revision(doc["id"], 0)["catalog"] == saved["catalog"]
    assert result["summary"] == dsdoc.summary(saved)
    with pytest.raises(HTTPException) as exc:
        apply(prepared, doc, organizer_output(doc))
    assert exc.value.status_code == 410


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "section"])
def test_organizer_never_falls_back_for_bad_plan(mutation):
    doc = document()
    prepared = prepare(doc, "organize")
    output = organizer_output(doc)
    if mutation == "missing":
        output["components"].clear()
    elif mutation == "duplicate":
        output["components"].append(copy.deepcopy(output["components"][0]))
    elif mutation == "unknown":
        output["components"][0]["key"] = "invented"
    else:
        output["components"][0]["sectionKey"] = "invented"
    with pytest.raises(ValueError):
        apply(prepared, doc, output)
    assert not store._db_path().exists()
    assert apply(prepared, doc, organizer_output(doc))["complete"]


def test_style_review_uses_helper_preserves_ir_and_selected_provider():
    doc = document()
    prepared = ai.prepare(ai.PrepareRequest(document=doc, operation="style-review", provider="claude"))
    assert prepared["tasks"][0]["messages"] == ai.style_review.build_style_review_prompt(doc)
    result = apply(prepared, doc, {"styleGuide": {"tone": "Quiet", "doRules": ["Use Source typography"]},
                                   "siteBrief": {"summary": "List application"}, "masterIr": {"tree": []}})
    saved = result["document"]
    assert saved["reviewComponents"] == doc["reviewComponents"]
    assert saved["styleGuide"]["provider"] == "claude"
    assert saved["styleGuide"]["review"]["tone"] == "Quiet"
    assert saved["siteBrief"]["summary"] == "List application"
    assert "masterIr" not in saved


@pytest.mark.parametrize("field,value", [("name", "Changed"), ("status", "published"), ("contentHash", "forged")])
def test_hash_uses_current_content_not_client_hash(field, value):
    doc = document()
    doc["contentHash"] = "cached"
    prepared = prepare(doc, "organize")
    doc[field] = value
    with pytest.raises(HTTPException) as exc:
        apply(prepared, doc, organizer_output(doc))
    assert exc.value.status_code == 409
    assert not store._db_path().exists()


def test_stored_draft_concurrent_change_is_rejected():
    doc = store.save_draft(document())["document"]
    prepared = prepare(doc, "organize")
    changed = copy.deepcopy(doc)
    changed["name"] = "Other editor saved"
    store.save_draft(changed)
    with pytest.raises(HTTPException) as exc:
        apply(prepared, doc, organizer_output(doc))
    assert exc.value.status_code == 409
    assert store.get_revision(doc["id"], 0)["name"] == "Other editor saved"


def test_all_candidates_all_viewports_no_eight_component_cap():
    doc = document(10)
    before = copy.deepcopy(doc)
    prepared = prepare(doc, repair=False)
    assert len(prepared["tasks"]) == 30
    assert all(t["status"] == "ready" for t in prepared["tasks"])
    for task in prepared["tasks"]:
        content = task["messages"][1]["content"]
        assert [c["type"] for c in content] == ["text", "image_url", "image_url"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;")
        assert content[2]["image_url"]["url"].startswith("data:image/png;")
    result = apply(prepared, doc)
    assert len(result["document"]["components"]) == 10
    assert result["document"]["reviewComponents"] == {}
    assert all(r["approved"] for r in result["results"])
    assert doc == before
    assert all(set(c["fidelity"]["aiReview"]["viewports"]) == set(ai.VIEWPORTS)
               for c in result["document"]["components"].values())


@pytest.mark.parametrize("missing", ["screenshot", "bounds", "block", "master", "independent-variant"])
def test_unsupported_viewports_never_promote_or_repair(missing):
    doc = document()
    comp = doc["reviewComponents"]["list-item-review"]
    if missing == "screenshot":
        del doc["referenceAssets"]["ev1"]["referencePreviews"]["mobile"]
    elif missing == "bounds":
        del comp["sourceRef"]["boundsByViewport"]["tablet"]
    elif missing == "block":
        del doc["referenceAssets"]["ev1"]["blockSizes"]["mobile"]
    elif missing == "master":
        comp.pop("masterIr")
    else:
        comp["variants"]["alternate"] = {"masterIr": copy.deepcopy(comp["masterIr"])}
    prepared = prepare(doc)
    assert len(prepared["tasks"]) == 3
    assert any(t["status"] == "unsupported" and t["reason"] for t in prepared["tasks"])
    result = apply(prepared, doc)
    assert result["complete"] and not result["document"]["components"]
    assert not result["results"][0]["approved"] and not result["results"][0]["supported"]


def test_one_failed_viewport_blocks_promotion():
    doc = document()
    prepared = prepare(doc, repair=False)
    result = apply(prepared, doc, lambda t: verdict(t["viewport"] != "mobile"))
    assert result["complete"] and not result["document"]["components"]
    assert not result["results"][0]["approved"]
    assert "mobile" in result["results"][0]["defects"][0]["where"]


@pytest.mark.parametrize("raw", [
    '{"approved":"true","score":99,"summary":"yes","defects":[]}',
    '{"approved":true,"score":true,"summary":"yes","defects":[]}',
    '{"approved":true,"score":NaN,"summary":"yes","defects":[]}',
    '{"approved":true,"score":1e999,"summary":"yes","defects":[]}',
    '{"approved":false,"approved":true,"score":99,"summary":"yes","defects":[]}',
    '{"approved":true,"score":99,"summary":"yes","defects":[{"severity":"MAJOR","what":"wrong","where":"row"}]}',
    '{"approved":true,"score":99,"summary":"yes","defects":"none"}',
    'prose {"approved":true,"score":99,"summary":"yes","defects":[]}',
])
def test_invalid_verdict_is_atomic_and_retryable(raw):
    doc = document()
    prepared = prepare(doc)
    with pytest.raises(ValueError):
        apply(prepared, doc, lambda t: raw if t["viewport"] == "mobile" else verdict())
    assert not store._db_path().exists()
    assert apply(prepared, doc)["document"]["components"]


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unknown"])
def test_response_ids_exactly_match_ready_tasks(mode):
    doc = document()
    prepared = prepare(doc)
    responses = [{"taskId": t["id"], "output": json.dumps(verdict())} for t in prepared["tasks"]]
    if mode == "missing":
        responses.pop()
    elif mode == "duplicate":
        responses[-1] = copy.deepcopy(responses[0])
    else:
        responses[-1]["taskId"] = "unknown"
    with pytest.raises(ValueError):
        ai.apply(ai.ApplyRequest(prepareId=prepared["prepareId"], documentHash=prepared["documentHash"],
                                document=doc, responses=responses))
    assert not store._db_path().exists()


def test_repair_safe_candidate_requires_fresh_three_viewport_review(monkeypatch):
    doc = document()
    original = copy.deepcopy(doc["reviewComponents"]["list-item-review"]["masterIr"])
    first = apply(prepare(doc), doc, verdict(False))
    repair = first["nextPreparation"]
    assert repair["stage"] == "master-repair" and not first["complete"]
    assert sum(p["type"] == "image_url" for p in repair["tasks"][0]["messages"][1]["content"]) == 6
    checked = []

    def acceptance(*args, **kwargs):
        checked.append(kwargs["viewport"])
        return True, []

    monkeypatch.setattr(ai.master_repair, "_layout_acceptance", acceptance)
    second = apply(repair, first["document"], repair_output())
    assert checked == list(ai.VIEWPORTS)
    assert second["document"]["reviewComponents"]["list-item-review"]["masterIr"] == original
    assert store.get_revision(doc["id"], 0)["reviewComponents"]["list-item-review"]["masterIr"] == original
    verification = second["nextPreparation"]
    assert verification["stage"] == "master-verify" and len(verification["tasks"]) == 3
    third = apply(verification, second["document"])
    comp = third["document"]["components"]["list-item"]
    assert third["complete"] and third["results"][0]["repaired"]
    assert comp["masterIr"]["tree"][0]["style"]["background"] == "#eeeeee"
    assert comp["sourceRef"]["masterHash"] == dsdoc.content_hash(comp["masterIr"])
    assert comp["fidelity"]["aiReview"]["repaired"]
    assert comp["fidelity"]["aiReview"]["rounds"] == 1
    assert doc["reviewComponents"]["list-item-review"]["masterIr"] == original


def test_repair_prompt_explicitly_matches_strict_operation_budget_and_schema():
    doc = document()
    first = apply(prepare(doc), doc, verdict(False))
    task = first["nextPreparation"]["tasks"][0]
    prompt = task["messages"][1]["content"][0]["text"]
    assert f"at most {ai.master_repair.MAX_OPERATIONS} operations TOTAL across all viewports" in prompt
    assert "exactly these four keys: op, sourceKey, property, value" in prompt
    assert "Allowed op values are restore-style and restore-layout only" in prompt
    assert json.dumps(sorted(ai.master_repair.repairable_props())) in prompt
    assert json.dumps(sorted(ai.master_repair.LAYOUT_PROPS)) in prompt
    assert 'return {"operations": []}' in prompt
    assert "never truncated" in prompt


@pytest.mark.parametrize('fail_first', [False, True])
def test_repair_batch_owns_one_renderer_and_closes_after_all_viewport_checks(monkeypatch, fail_first):
    doc = document(count=2)
    first = apply(prepare(doc), doc, verdict(False))
    events, checks = [], []
    page = object()
    @contextmanager
    def renderer(render=None):
        events.append('open')
        try:
            yield page, lambda *_args: _png(240, 60)
        finally:
            events.append('close')
    def acceptance(*_args, **kwargs):
        assert kwargs['page'] is page
        checks.append(kwargs['viewport'])
        return (False, ['escape']) if fail_first and len(checks) == 1 else (True, [])
    monkeypatch.setattr(ai, '_renderer', renderer)
    monkeypatch.setattr(ai.master_repair, '_layout_acceptance', acceptance)
    result = apply(first['nextPreparation'], first['document'], repair_output())
    assert events == ['open', 'close']
    assert checks == (['desktop'] if fail_first else list(ai.VIEWPORTS)) + list(ai.VIEWPORTS)
    assert len(result['nextPreparation']['tasks']) == (3 if fail_first else 6)
    assert all(not entry['repaired'] for entry in result['results'])


@pytest.mark.parametrize("count", [13, 15, 16])
def test_over_budget_repair_rejects_entire_response_without_consuming_preparation(count, monkeypatch):
    doc = document()
    first = apply(prepare(doc), doc, verdict(False))
    prepared = first["nextPreparation"]
    before = store.get_revision(doc["id"], 0)
    state = copy.deepcopy(ai._PREPARATIONS[prepared["prepareId"]])

    def must_not_truncate(*args, **kwargs):
        pytest.fail("Over-budget operations must reject before the helper can truncate them")

    monkeypatch.setattr(ai.master_repair, "validate_operations", must_not_truncate)
    with pytest.raises(ai.InvalidAIOutput) as error:
        apply(prepared, first["document"], {"operations": repair_output()["operations"] * count})
    assert error.value.detail["code"] == "invalid-ai-output"
    assert error.value.detail["stage"] == "master-repair"
    assert store.get_revision(doc["id"], 0) == before
    assert ai._PREPARATIONS[prepared["prepareId"]] == state


def test_repair_rejected_in_one_viewport_rolls_back_exact_master(monkeypatch):
    doc = document()
    original = copy.deepcopy(doc["reviewComponents"]["list-item-review"])
    first = apply(prepare(doc), doc, verdict(False))
    monkeypatch.setattr(ai.master_repair, "_layout_acceptance", lambda *a, **k: (True, []))
    second = apply(first["nextPreparation"], first["document"], repair_output())
    third = apply(second["nextPreparation"], second["document"], lambda t: verdict(t["viewport"] != "mobile"))
    assert third["complete"] and not third["document"]["components"]
    comp = third["document"]["reviewComponents"]["list-item-review"]
    assert comp["masterIr"] == original["masterIr"] and comp["sourceRef"] == original["sourceRef"]
    assert not comp["fidelity"]["aiReview"]["repaired"]
    assert third["results"][0]["rejected"]


@pytest.mark.parametrize("reason", ["escape", "new-defect", "similarity:80.00"])
def test_objective_repair_guard_blocks_without_verification(monkeypatch, reason):
    doc = document()
    first = apply(prepare(doc), doc, verdict(False))
    monkeypatch.setattr(ai.master_repair, "_layout_acceptance", lambda *a, **k: (False, [reason]))
    second = apply(first["nextPreparation"], first["document"], repair_output())
    assert second["complete"] and second["nextPreparation"] is None
    assert reason in second["results"][0]["rejected"][0]
    assert second["document"]["reviewComponents"]["list-item-review"]["masterIr"] == doc["reviewComponents"]["list-item-review"]["masterIr"]


@pytest.mark.parametrize("op", [
    {"op": "replace-tree", "sourceKey": "row", "property": "background", "value": "#eeeeee"},
    {"op": "restore-style", "sourceKey": "invented", "property": "background", "value": "#eeeeee"},
    {"op": "restore-layout", "sourceKey": "row", "property": "width", "value": 1000},
    {"op": "restore-style", "sourceKey": "row", "property": "text", "value": "replacement"},
])
def test_invalid_repair_operations_never_save(op):
    doc = document()
    first = apply(prepare(doc), doc, verdict(False))
    before = store.get_revision(doc["id"], 0)
    with pytest.raises(ValueError):
        apply(first["nextPreparation"], first["document"], {"operations": [op]})
    assert store.get_revision(doc["id"], 0) == before


def test_render_copy_mutation_never_touches_canonical_document():
    doc = document()
    comp = doc["reviewComponents"]["list-item-review"]
    comp["masterIr"]["tree"][0]["src"] = "ddna://blobs/" + "a" * 64 + ".png"
    comp["sourceRef"]["masterHash"] = dsdoc.content_hash(comp["masterIr"])
    before = copy.deepcopy(doc)

    def render(page, disposable, viewport):
        disposable["masterIr"]["tree"][0]["src"] = "data:image/png;base64,expanded-for-render"
        return _png(240, 60)

    prepared = ai.prepare(ai.PrepareRequest(document=doc, operation="master-review", provider="codex", repair=False), render=render)
    result = apply(prepared, doc)
    assert doc == before
    assert result["document"]["components"]["list-item"]["masterIr"] == comp["masterIr"]


def test_render_failure_is_explicit_and_does_not_call_chat():
    doc = document()

    def render(*args):
        raise RuntimeError("local renderer unavailable")

    prepared = ai.prepare(ai.PrepareRequest(document=doc, operation="master-review", provider="codex"), render=render)
    assert all(t["status"] == "unsupported" and not t["messages"] for t in prepared["tasks"])
    result = apply(prepared, doc)
    assert result["complete"] and not result["results"][0]["approved"]
    assert not result["document"]["components"]


def test_expiry_and_capacity_are_explicit(monkeypatch):
    doc = document()
    prepared = prepare(doc, "organize")
    monkeypatch.setattr(ai, "MAX_PREPARATIONS", 1)
    with pytest.raises(HTTPException) as exc:
        prepare(doc, "organize")
    assert exc.value.status_code == 503
    ai._PREPARATIONS[prepared["prepareId"]]["deadline"] = 0
    with pytest.raises(HTTPException) as exc:
        apply(prepared, doc, organizer_output(doc))
    assert exc.value.status_code == 410


def test_endpoint_invalid_output_returns_422_and_stale_returns_409(client):
    doc = document()
    prepared = prepare(doc, "organize")
    body = {"prepareId": prepared["prepareId"], "documentHash": prepared["documentHash"], "document": doc,
            "responses": [{"taskId": prepared["tasks"][0]["id"], "output": "not JSON"}]}
    assert client.post("/api/design-system/desktop-ai/apply", json=body).status_code == 422
    body["document"]["name"] = "changed"
    assert client.post("/api/design-system/desktop-ai/apply", json=body).status_code == 409


def test_fenced_json_accepted():
    doc = document()
    result = apply(prepare(doc, repair=False), doc, "```json\n" + json.dumps(verdict()) + "\n```")
    assert result["complete"] and result["results"][0]["approved"]


def hide_source_viewports(doc, viewports):
    comp = doc["reviewComponents"]["list-item-review"]
    master = comp["masterIr"]
    master["responsive"] = {"viewports": {vp: {"width": 1440, "height": 900} for vp in ai.VIEWPORTS}}
    for viewport in viewports:
        master["tree"][0].setdefault("responsive", {})[viewport] = {"visible": False}
        comp["sourceRef"]["boundsByViewport"].pop(viewport, None)
    comp["sourceRef"]["masterHash"] = dsdoc.content_hash(master)
    return comp


@pytest.mark.parametrize("hidden", [("mobile",), ("desktop", "tablet")])
def test_source_hidden_viewports_are_deterministic_skips_not_approvals(hidden):
    doc = document()
    comp = hide_source_viewports(doc, hidden)
    before = copy.deepcopy(comp["masterIr"])
    prepared = prepare(doc, repair=False)
    assert len(prepared["tasks"]) == 3 - len(hidden)
    assert {t["viewport"] for t in prepared["skippedViewports"]} == set(hidden)
    assert all(t["status"] == "ready" for t in prepared["tasks"])
    result = apply(prepared, doc)
    assert result["results"][0]["approved"] and result["results"][0]["supported"]
    saved = result["document"]["components"]["list-item"]
    assert saved["masterIr"] == before
    audit = saved["fidelity"]["aiReview"]["viewports"]
    assert set(audit) == set(ai.VIEWPORTS)
    for vp in hidden:
        assert audit[vp]["status"] == "skipped"
        assert audit[vp]["approved"] is None and audit[vp]["score"] is None
        assert audit[vp]["evidence"]["masterHash"] == comp["sourceRef"]["masterHash"]
        assert audit[vp]["evidence"]["referenceHash"].startswith("sha256:")


@pytest.mark.parametrize("missing", ["capture", "bad-capture", "viewport-metadata", "block-size", "bounds-conflict",
                                     "source-revision", "pinned-hash", "source-key", "explicit-false"])
def test_hidden_skip_requires_consistent_captured_source_evidence(missing):
    doc = document()
    comp = hide_source_viewports(doc, ("mobile",))
    if missing == "capture":
        doc["referenceAssets"]["ev1"]["referencePreviews"].pop("mobile")
    elif missing == "bad-capture":
        doc["referenceAssets"]["ev1"]["referencePreviews"]["mobile"] = "data:image/png;base64,bm90YW5pbWFnZQ=="
    elif missing == "viewport-metadata":
        comp["masterIr"].pop("responsive")
        comp["sourceRef"]["masterHash"] = dsdoc.content_hash(comp["masterIr"])
    elif missing == "block-size":
        doc["referenceAssets"]["ev1"]["blockSizes"].pop("mobile")
    elif missing == "bounds-conflict":
        comp["sourceRef"]["boundsByViewport"]["mobile"] = {"x": 0, "y": 0, "width": 0, "height": 0}
    elif missing == "source-revision":
        comp["sourceRef"]["sourceRevisionHash"] = "wrong"
    elif missing == "pinned-hash":
        comp["sourceRef"]["masterHash"] = "wrong"
    elif missing == "source-key":
        comp["sourceRef"]["sourceKey"] = "wrong"
    else:
        comp["masterIr"]["tree"][0]["responsive"]["mobile"].pop("visible")
        comp["sourceRef"]["masterHash"] = dsdoc.content_hash(comp["masterIr"])
    if missing == "pinned-hash":
        with pytest.raises(HTTPException) as exc:
            prepare(doc)
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "invalid-master-pins"
        return
    prepared = prepare(doc)
    assert not prepared.get("skippedViewports")
    mobile = next(t for t in prepared["tasks"] if t["viewport"] == "mobile")
    assert mobile["status"] == "unsupported" and mobile["messages"] == []
    result = apply(prepared, doc)
    assert not result["results"][0]["approved"] and result["complete"]


def test_hidden_child_cannot_skip_visible_parent():
    doc = document()
    comp = doc["reviewComponents"]["list-item-review"]
    comp["masterIr"]["tree"][0]["children"][0]["responsive"] = {"mobile": {"visible": False}}
    comp["sourceRef"]["masterHash"] = dsdoc.content_hash(comp["masterIr"])
    prepared = prepare(doc)
    assert len(prepared["tasks"]) == 3 and not prepared.get("skippedViewports")
    assert all(t["status"] == "ready" for t in prepared["tasks"])


def test_all_hidden_requires_no_chats_and_cannot_be_promoted(monkeypatch):
    doc = document()
    hide_source_viewports(doc, ai.VIEWPORTS)

    def forbidden_render(*args, **kwargs):
        pytest.fail("Hidden viewports must not launch a renderer")

    monkeypatch.setattr(ai, "_renderer", forbidden_render)
    prepared = prepare(doc)
    assert prepared["tasks"] == [] and len(prepared["skippedViewports"]) == 3
    result = apply(prepared, doc)
    assert result["complete"] and not result["document"]["components"]
    assert result["results"][0]["approved"] is False and result["results"][0]["supported"] is False


def test_mobile_only_repair_uses_visible_viewport_and_preserves_hidden_evidence(monkeypatch):
    doc = document()
    hide_source_viewports(doc, ("desktop", "tablet"))
    first = apply(prepare(doc), doc, verdict(False))
    repair = first["nextPreparation"]
    assert repair["stage"] == "master-repair"
    assert len(repair["tasks"]) == 1 and repair["tasks"][0]["viewport"] == "mobile"
    assert sum(p["type"] == "image_url" for p in repair["tasks"][0]["messages"][1]["content"]) == 2
    checked = []

    def acceptance(*args, **kwargs):
        checked.append(kwargs["viewport"])
        return True, []

    monkeypatch.setattr(ai.master_repair, "_layout_acceptance", acceptance)
    second = apply(repair, first["document"], repair_output())
    assert checked == ["mobile"]
    verification = second["nextPreparation"]
    assert len(verification["tasks"]) == 1 and len(verification["skippedViewports"]) == 2
    third = apply(verification, second["document"])
    assert third["complete"] and third["results"][0]["repaired"]
    comp = third["document"]["components"]["list-item"]
    for vp in ("desktop", "tablet"):
        evidence = comp["fidelity"]["aiReview"]["viewports"][vp]["evidence"]
        assert evidence["visible"] is False and evidence["masterHash"] == comp["sourceRef"]["masterHash"]


def test_render_failure_does_not_turn_proven_hidden_into_failure(monkeypatch):
    doc = document()
    hide_source_viewports(doc, ("mobile",))

    @contextmanager
    def unavailable(*args, **kwargs):
        raise RuntimeError("Renderer unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(ai, "_renderer", unavailable)
    prepared = prepare(doc)
    assert len(prepared["skippedViewports"]) == 1
    assert all(t["status"] == "unsupported" for t in prepared["tasks"])
    result = apply(prepared, doc)
    assert result["results"][0]["viewports"]["mobile"]["status"] == "skipped"
    assert not result["results"][0]["approved"]


@pytest.mark.parametrize("operation", ["organize", "style-review", "master-review"])
def test_corrupt_client_pins_cannot_prepare_or_overwrite_valid_saved_draft(client, operation):
    saved = store.save_draft(document())["document"]
    before = store.get_revision(saved["id"], 0)
    corrupted = copy.deepcopy(saved)
    master = corrupted["reviewComponents"]["list-item-review"]["masterIr"]
    master["provenance"] = {"importedFrom": "project-load", "createdAt": "1970-01-01T00:00:00+00:00"}
    master["contentHash"] = "migration-output"
    response = client.post("/api/design-system/desktop-ai/prepare", json={
        "document": corrupted, "operation": operation, "provider": "claude"})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid-master-pins"
    assert detail["errors"] == [{
        "code": "master-hash-mismatch",
        "path": 'document.reviewComponents["list-item-review"].sourceRef.masterHash',
        "masterPath": 'document.reviewComponents["list-item-review"].masterIr',
        "message": "Observed master differs from its supplied Source hash; restore or rebuild from Source",
    }]
    assert not ai._PREPARATIONS
    assert store.get_revision(saved["id"], 0) == before


def test_apply_rejects_corrupted_client_without_consuming_valid_preparation(client):
    saved = store.save_draft(document())["document"]
    prepared = prepare(saved, "organize")
    corrupted = copy.deepcopy(saved)
    corrupted["reviewComponents"]["list-item-review"]["masterIr"]["provenance"] = {"importedFrom": "project-load"}
    response = client.post("/api/design-system/desktop-ai/apply", json={
        "document": corrupted, "prepareId": prepared["prepareId"], "documentHash": prepared["documentHash"],
        "responses": [{"taskId": prepared["tasks"][0]["id"], "output": json.dumps(organizer_output(saved))}],
    })
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid-master-pins"
    assert store.get_revision(saved["id"], 0) == saved
    assert apply(prepared, saved, organizer_output(saved))["complete"]


@pytest.mark.parametrize("pool", ["components", "reviewComponents", "suggestions"])
@pytest.mark.parametrize("nested", [None, "variants", "states"])
def test_invalid_supplied_observed_pins_checked_in_all_pools_and_nested_masters(pool, nested):
    doc = document()
    comp = doc["reviewComponents"].pop("list-item-review")
    doc.setdefault(pool, {})["candidate"] = comp
    target = comp
    path = f'document.{pool}["candidate"]'
    if nested:
        target = {"masterIr": copy.deepcopy(comp["masterIr"]), "sourceRef": copy.deepcopy(comp["sourceRef"])}
        comp[nested] = {"alternate": target}
        path += f'.{nested}["alternate"]'
    target["sourceRef"]["masterHash"] = "incorrect-supplied-pin"
    with pytest.raises(HTTPException) as exc:
        prepare(doc, "organize")
    assert exc.value.status_code == 422
    assert exc.value.detail["errors"][0]["path"] == path + ".sourceRef.masterHash"
    assert not store._db_path().exists()


def test_unpinned_suggestions_are_not_arbitrarily_pinned_or_rejected():
    doc = document()
    suggested = copy.deepcopy(doc["reviewComponents"]["list-item-review"])
    suggested.update(origin="suggested", status="draft")
    suggested["sourceRef"].pop("masterHash")
    doc["suggestions"] = {"idea": suggested}
    prepared = prepare(doc, "organize")
    result = apply(prepared, doc, organizer_output(doc))
    assert "masterHash" not in result["document"]["suggestions"]["idea"]["sourceRef"]


def test_missing_observed_pin_remains_unsupported_not_implicitly_repaired():
    doc = document()
    doc["reviewComponents"]["list-item-review"]["sourceRef"].pop("masterHash")
    prepared = prepare(doc)
    assert all(t["status"] == "unsupported" for t in prepared["tasks"])
    result = apply(prepared, doc)
    comp = result["document"]["reviewComponents"]["list-item-review"]
    assert not result["results"][0]["approved"] and "masterHash" not in comp["sourceRef"]


def test_new_accepted_layout_repair_keeps_pin_after_real_javascript_roundtrip(monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for real browser JSON serialization regression")
    doc = document()
    original = doc["reviewComponents"]["list-item-review"]
    original["masterIr"]["tree"][0]["children"][0]["sourceKey"] = "row-text"
    original["sourceRef"]["masterHash"] = dsdoc.content_hash(original["masterIr"])
    first = apply(prepare(doc), doc, verdict(False))
    monkeypatch.setattr(ai.master_repair, "_layout_acceptance", lambda *a, **k: (True, []))
    second = apply(first["nextPreparation"], first["document"], {"operations": [
        {"op": "restore-layout", "sourceKey": "row-text", "property": "width", "value": 202},
    ]})
    third = apply(second["nextPreparation"], second["document"])
    saved = third["document"]
    result = subprocess.run([node, "-e", "process.stdout.write(JSON.stringify(JSON.parse(require('node:fs').readFileSync(0,'utf8'))))"],
                            input=json.dumps(saved), encoding="utf-8", capture_output=True, check=True, timeout=15)
    roundtripped = json.loads(result.stdout)
    ai._check_document(roundtripped)
    comp = roundtripped["components"]["list-item"]
    assert comp["sourceRef"]["masterHash"] == dsdoc.content_hash(comp["masterIr"])
    assert type(comp["masterIr"]["tree"][0]["children"][0]["frame"]["width"]) is int
    assert comp["masterIr"]["tree"][0]["children"][0]["frame"]["width"] == 202


@pytest.mark.parametrize("stage", ["organize", "style-review", "master-review", "master-repair", "master-verify"])
def test_malformed_ai_output_returns_task_context_and_retry_preserves_transaction(client, monkeypatch, stage):
    doc = store.save_draft(document())["document"]
    operation = "master-review" if stage.startswith("master-") else stage
    prepared = ai.prepare(ai.PrepareRequest(document=doc, operation=operation, provider="claude"))
    if stage in ("master-repair", "master-verify"):
        first = apply(prepared, doc, verdict(False))
        prepared, doc = first["nextPreparation"], first["document"]
    if stage == "master-verify":
        monkeypatch.setattr(ai.master_repair, "_layout_acceptance", lambda *a, **k: (True, []))
        second = apply(prepared, doc, repair_output())
        prepared, doc = second["nextPreparation"], second["document"]
    before_doc = copy.deepcopy(doc)
    before_db = store.get_revision(doc["id"], 0)
    before_envelope = copy.deepcopy(ai._PREPARATIONS[prepared["prepareId"]]["envelope"])
    before_deadline = ai._PREPARATIONS[prepared["prepareId"]]["deadline"]
    if stage == "organize":
        valid = organizer_output(doc)
    elif stage == "style-review":
        valid = {"styleGuide": {"tone": "Quiet typography", "doRules": ["Use Source spacing"]}}
    elif stage == "master-repair":
        valid = {"operations": []}
    else:
        valid = verdict()
    responses = [{"taskId": t["id"], "output": json.dumps(valid)} for t in prepared["tasks"] if t["status"] == "ready"]
    index = len(responses) - 1
    task = next(t for t in prepared["tasks"] if t["id"] == responses[index]["taskId"])
    # Reproduce the real missing-last-brace response; never mend it server-side.
    responses[index]["output"] = responses[index]["output"][:-1]
    request = {"prepareId": prepared["prepareId"], "documentHash": prepared["documentHash"],
               "document": doc, "responses": responses}
    response = client.post("/api/design-system/desktop-ai/apply", json=request)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert set(detail) == {"code", "message", "taskId", "stage", "component", "path", "retryable"}
    assert detail["code"] == "invalid-ai-output" and detail["retryable"] is True
    assert detail["stage"] == stage and detail["component"] == task["componentKey"]
    assert detail["taskId"] == task["id"] and detail["path"] == f"responses[{index}].output"
    assert "Expecting" in detail["message"]
    assert doc == before_doc and store.get_revision(doc["id"], 0) == before_db
    state = ai._PREPARATIONS[prepared["prepareId"]]
    assert state["envelope"] == before_envelope and state["deadline"] == before_deadline
    assert state["settings"]["provider"] == "claude"
    responses[index]["output"] = json.dumps(valid)
    retried = client.post("/api/design-system/desktop-ai/apply", json=request)
    assert retried.status_code == 200, retried.text
    assert prepared["prepareId"] not in ai._PREPARATIONS


def test_task_schema_failure_is_retryable_but_bad_task_ids_are_not_format_correction(client):
    doc = document()
    prepared = prepare(doc, "style-review")
    request = {"prepareId": prepared["prepareId"], "documentHash": prepared["documentHash"], "document": doc,
               "responses": [{"taskId": prepared["tasks"][0]["id"], "output": "{}"}]}
    response = client.post("/api/design-system/desktop-ai/apply", json=request)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid-ai-output"
    request["responses"][0]["taskId"] = "wrong-task"
    response = client.post("/api/design-system/desktop-ai/apply", json=request)
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)
    assert not store._db_path().exists()


@pytest.mark.parametrize("provider", ["openai", "astra"])
def test_gpt_desktop_routes_prepare_apply_without_server_api_key(client, provider):
    doc = document()
    response = client.post("/api/design-system/desktop-ai/prepare", json={
        "document": doc, "operation": "master-review", "provider": provider})
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert prepared["provider"] == provider
    result = apply(prepared, doc)
    assert result["complete"] is True
    assert not result["document"]["reviewComponents"]
    reviewed = next(iter(result["document"]["components"].values()))
    assert reviewed["fidelity"]["aiReview"]["provider"] == provider


def test_retry_preserves_repair_validation_feedback_for_next_agent_prompt():
    doc = document()
    comp = doc["reviewComponents"]["list-item-review"]
    comp["fidelity"]["aiReview"] = {"rejected": ["mobile: layout regression"]}
    prepared = prepare(doc)
    result = apply(prepared, doc, verdict(False))
    next_task = result["nextPreparation"]["tasks"][0]
    assert "mobile: layout regression" in json.dumps(next_task["messages"])
    assert result["document"]["reviewComponents"]["list-item-review"]["fidelity"]["aiReview"]["previousRepairRejections"] == ["mobile: layout regression"]


def test_invalid_layout_feedback_identifies_operation_and_measured_frame():
    doc = document()
    reviewed = apply(prepare(doc), doc, verdict(False))
    prepared = reviewed["nextPreparation"]
    with pytest.raises(ai.InvalidAIOutput) as exc:
        apply(prepared, reviewed["document"], {"operations": [
            {"op": "restore-layout", "sourceKey": "row", "property": "width", "value": 9999}]})
    message = exc.value.detail["message"]
    assert "operations[0]" in message and "sourceKey=row" in message
    assert '"width": 240' in message and "omit it" in message
    assert prepared["prepareId"] in ai._PREPARATIONS


def test_fresh_desktop_review_does_not_present_historical_capture_offsets_as_current():
    doc = document()
    comp = doc["reviewComponents"]["list-item-review"]
    comp["fidelity"]["viewports"]["desktop"]["originError"] = 123.456
    comp["review"]["reasons"] = ["historical offset 123.456px"]
    prepared = prepare(doc)
    prompt = json.dumps(prepared["tasks"][0]["messages"])
    assert "123.456" not in prompt
    assert "fresh, isolated renders" in prompt
    assert comp["fidelity"]["viewports"]["desktop"]["originError"] == 123.456
