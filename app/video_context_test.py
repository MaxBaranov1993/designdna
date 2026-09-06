import json
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from video_context import prepare_context, structure
from video_story import build_pages, direct_story
from video_story_fixtures import pages_fixture, plan_fixture


def test_visual_tiles_and_hierarchy_precede_planning():
    pages = pages_fixture()
    timeline = build_pages(pages, {})
    picture = BytesIO(); Image.new("RGB", (960, 2200), "white").save(picture, "PNG")
    with patch("video_context.render_png", return_value=picture.getvalue()) as render, patch("video_context.cache_store.get", return_value=None), patch("video_context.cache_store.put"):
        visual = prepare_context(timeline)
    assert render.call_count == 2
    assert len(visual[0]["images"]) == 3
    assert visual[0]["images"][0]["url"].startswith("data:image/jpeg;base64,")
    nodes = structure(pages[0]["ir"])
    field = next(n for n in nodes if n["id"] == "s0.children.3")
    assert field["parentId"] == "s0" and field["type"] == "input" and field["frame"]["y"] == 248
    plan = {**plan_fixture(), "understanding": "Форма объявления с названием, ценой и городом."}
    with patch("video_story.llm.chat", side_effect=[json.dumps({"summary": plan["understanding"], "targets": [{"pageId": "ir", "id": "s0.children.3", "meaning": "Название товара"}]}), json.dumps(plan)]) as chat:
        _, _, meta = direct_story(timeline, "Заполни форму", "codex", "high", visual_context=visual)
    assert chat.call_count == 2
    content = chat.call_args_list[0].args[1][-1]["content"]
    assert any(part["type"] == "image_url" for part in content)
    assert '"parentId": "s0"' in content[0]["text"]
    assert meta["understanding"] == plan["understanding"]
    assert "COMPLETED PAGE UNDERSTANDING" in chat.call_args.args[1][-1]["content"][0]["text"]


def test_same_snapshot_reuses_images_and_skips_derived_copies():
    timeline = build_pages(pages_fixture(), {})
    timeline["story"]["pages"].append({**timeline["story"]["pages"][0], "id": "derived", "generatedFrom": "ir"})
    with patch("video_context.cache_store.get", return_value={"images": []}), patch("video_context.render_png") as render:
        assert len(prepare_context(timeline)) == 2
    render.assert_not_called()
