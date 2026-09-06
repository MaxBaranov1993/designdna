from __future__ import annotations

import copy
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from server import app
from ir.timeline import validate, revert_change_set
from video_story import build_pages, direct_story, targets
from video_story_fixtures import pages_fixture, plan_fixture, PROMPT


def baseline():
    return build_pages(pages_fixture(), {"width": 960, "height": 640, "fps": 12, "duration": 8000})


def generate(timeline=None, plan=None):
    with patch("video_story.llm.chat", return_value=json.dumps(plan or plan_fixture())):
        return direct_story(timeline or baseline(), PROMPT, "codex", "medium")


def test_walkthrough_targets_and_snapshots_are_exact_and_changes_reversible():
    before = baseline()
    frozen = copy.deepcopy(before)
    edited, changes, meta = generate(before)
    assert before == frozen
    assert validate(edited) == []
    assert edited["story"]["pages"] == pages_fixture()
    assert next(l for l in edited["layers"] if l["ref"] == "publish")["storyTarget"] == "s0.children.9"
    assert {t["id"] for t in targets(pages_fixture()[0]["ir"]) if t["kind"] == "input"} == {"s0.children.3", "s0.children.5", "s0.children.7"}
    assert edited["composition"]["duration"] == 10450
    assert revert_change_set(edited, changes) == before
    assert meta["planSource"] == "llm"


def test_local_prompt_edit_preserves_manual_actions_and_layer_keyframes():
    first, _, _ = generate()
    first["story"]["actions"][1]["text"] = "Ручное название"
    first["layers"][0]["transform"]["properties"]["x"] = {"keyframes": [{"t": 0, "value": 12}]}
    before = copy.deepcopy(first)
    second, _, _ = generate(first, {"edits": [{"op": "update", "id": "scroll", "changes": {"duration": 2000}}]})
    assert second["story"]["actions"][1]["text"] == "Ручное название"
    assert second["layers"][0]["transform"] == before["layers"][0]["transform"]
    assert [a for a in second["story"]["actions"] if a["id"] != "scroll"] == [a for a in before["story"]["actions"] if a["id"] != "scroll"]


@pytest.mark.parametrize("change", [
    {"target": "s9.fake"}, {"pageId": "absent"}, {"duration": -20}, {"duration": "slow"}, {"text": {"invalid": True}},
])
def test_invalid_actions_cannot_change_document(change):
    doc = baseline(); frozen = copy.deepcopy(doc); plan = plan_fixture()
    plan["edits"][0]["actions"][1].update(change)
    with pytest.raises(ValueError): generate(doc, plan)
    assert doc == frozen


def test_unknown_page_or_missing_navigation_is_rejected():
    plan = plan_fixture(); plan["edits"][0]["actions"][6]["toPageId"] = "missing"
    with pytest.raises(ValueError): generate(plan=plan)
    plan = plan_fixture(); del plan["edits"][0]["actions"][6]
    with pytest.raises(ValueError, match="неактивной"): generate(plan=plan)


def test_missing_information_is_returned_as_a_question_without_fabricated_video():
    with pytest.raises(ValueError, match="Нужно уточнить"):
        generate(plan={"question": "Какую цену ввести?"})


def test_build_api_supports_multiple_pages_and_assist_preserves_selected_account():
    with TestClient(app) as client:
        built = client.post("/api/timeline/build", json={"ir": pages_fixture()[0]["ir"], "pages": pages_fixture(), "settings": {"duration": 8000}})
        assert built.status_code == 200, built.text
        with patch("video_story.llm.chat", return_value=json.dumps(plan_fixture())) as chat:
            result = client.post("/api/timeline/assist", json={"timeline": built.json()["timeline"], "prompt": PROMPT, "provider": "claude", "require_llm": True})
        assert result.status_code == 200, result.text
        assert chat.call_args.args[0] == "claude"


def test_scroll_to_exact_element_without_pixel_coordinates():
    plan = plan_fixture()
    action = plan["edits"][0]["actions"][4]
    action.pop("y"); action["target"] = "s0.children.9"
    doc, _, _ = generate(plan=plan)
    assert validate(doc) == []
    with TestClient(app) as client:
        result = client.post("/api/timeline/export", json={"timeline":doc, "mode":"css"})
        assert result.status_code == 422
    action["target"] = "s9.missing"
    with pytest.raises(ValueError): generate(plan=plan)


def test_ai_can_soften_existing_actions_without_replacing_content():
    before, _, _ = generate()
    plan = {"edits": [{"op":"update","id":"scroll","changes":{"easing":"soft","duration":1600}}, {"op":"update","id":"next","changes":{"easing":"ease-out","transition":"motion"}}]}
    after, changes, _ = generate(before,plan)
    assert after['story']['actions'][1] == before['story']['actions'][1]
    assert after['story']['actions'][4]['duration'] == 1600
    assert revert_change_set(after,changes) == before
    plan['edits'][0]['changes']['easing']='unknown'
    with pytest.raises(ValueError): generate(before,plan)
