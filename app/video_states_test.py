import copy
import json
from unittest.mock import patch
import pytest
from video_story import build_pages, direct_story, validate_story
from video_story_fixtures import pages_fixture
from video_states import derive_states, text_fields
from ir.timeline import validate, revert_change_set


def state_plan():
    return {"summary": "Выбор русского языка", "states": [
        {"id": "menu", "name": "Меню языков", "fromPageId": "ir", "overlays": [{"id": "languages", "anchorTarget": "s0.children.3", "title": "Язык",
            "items": [{"id": "en", "text": "English"}, {"id": "sr", "text": "Srpski"}, {"id": "ru", "text": "Русский"}]}]},
        {"id": "translated", "name": "Русская версия", "fromPageId": "ir", "text": {"tree.0.children.0.text": "Переведённая страница"}, "overlays": []},
    ], "edits": [{"op": "insert", "afterId": None, "actions": [
        {"id": "open", "type": "click", "pageId": "ir", "target": "s0.children.3"},
        {"id": "show", "type": "navigate", "pageId": "ir", "toPageId": "menu", "transition": "state"},
        {"id": "choose", "type": "click", "pageId": "menu", "target": "overlay.languages.ru"},
        {"id": "translate", "type": "navigate", "pageId": "menu", "toPageId": "translated", "transition": "state"},
        {"id": "hold", "type": "wait", "pageId": "translated"},
    ]}]}


def test_generated_menu_translation_layers_and_exact_undo():
    original = build_pages(pages_fixture(), {"width": 960, "height": 640})
    frozen = copy.deepcopy(original)
    with patch("video_story.llm.chat", return_value=json.dumps(state_plan())):
        edited, changes, _ = direct_story(original, "Создай меню и перевод", "codex", "medium")
    assert validate(edited) == []
    assert original == frozen
    assert edited["story"]["pages"][:2] == original["story"]["pages"]
    assert edited["story"]["pages"][-1]["ir"]["tree"][0]["children"][0]["text"] == "Переведённая страница"
    assert any(layer["storyTarget"] == "overlay.languages.ru" for layer in edited["layers"] if layer.get("storyTarget"))
    assert revert_change_set(edited, changes) == original


def test_state_revisions_preserve_unmentioned_manual_changes():
    story = build_pages(pages_fixture(), {})["story"]
    states = state_plan()["states"]
    updated = derive_states(story, states)
    updated["pages"][-1]["ir"]["tree"][0]["children"][1]["text"] = "Ручная подпись"
    revised = derive_states(updated, [{"id": "translated", "name": "Русская версия", "fromPageId": "ir", "text": {"tree.0.children.0.text": "Новый заголовок"}}])
    assert revised["pages"][-1]["ir"]["tree"][0]["children"][1]["text"] == "Ручная подпись"
    assert revised["pages"][:2] == story["pages"]


@pytest.mark.parametrize("state", [
    {"id":"ir","fromPageId":"page2","name":"replace"},
    {"id":"new","fromPageId":"ir","name":"script","text":{"tree.0.style.background":"red"}},
    {"id":"new","fromPageId":"ir","name":"url","text":{"tree.0.children.0.href":"https://example.com"}},
    {"id":"new","fromPageId":"missing","name":"missing"},
    {"id":"new","fromPageId":"ir","name":"menu","overlays":[{"id":"languages","anchorTarget":"missing","items":[{"id":"ru","text":"Русский"}]}]},
])
def test_bad_state_never_mutates_source(state):
    story = build_pages(pages_fixture(), {})["story"]
    frozen = copy.deepcopy(story)
    with pytest.raises(ValueError): derive_states(story, [state])
    assert story == frozen


def test_all_nested_visible_text_is_available_for_translation():
    fields = text_fields({"tree":[{"props":{"heading":"Title","items":[{"title":"Item","description":"Copy"}]}, "children":[{"type":"input","placeholder":"Search"}]}]})
    assert {field["text"] for field in fields} == {"Title","Item","Copy","Search"}
