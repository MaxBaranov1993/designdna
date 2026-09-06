"""Synthetic states: preview, editable menu copy, undo, persistence and DOM playback."""
import json
import os
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from video_story import build_pages, direct_story
from video_story_fixtures import pages_fixture
from video_states_test import state_plan

BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:9139")
OUT = Path(__file__).resolve().parents[1] / "results/video-states"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    saved = None
    errors = []
    source = pages_fixture()
    source[0]["ir"]["tree"][0]["type"] = "source-block"
    baseline = build_pages(source, {"width": 960, "height": 640, "duration": 8000})
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        def save(route):
            nonlocal saved
            saved = route.request.post_data_json["project"]
            route.fulfill(json={"ok": True, "revision": "states-test"})
        def assist(route):
            body = route.request.post_data_json
            assert body["model"] == "gpt-6-astra" and body["effort"] == "high"
            with patch("video_story.llm.chat", return_value=json.dumps(state_plan())):
                timeline, changes, meta = direct_story(body["timeline"], body["prompt"], "codex", "medium")
            route.fulfill(json={"timeline": timeline, "changeSet": changes, **meta})
        page.route("**/api/project/load", lambda route: route.fulfill(json={"project": saved, "revision": "states-test"}))
        page.route("**/api/project/save", save)
        page.route("**/api/timeline/assist", assist)
        page.goto(BASE + "/flow")
        page.wait_for_function("window.GraphDev")
        page.evaluate("GraphDev.clear()")
        node_id = page.evaluate("v=>{const n=GraphDev.add('timeline',150,100);GraphDev.patchData(n.id,v);GraphDev.fit();return n.id}",
            {"ir": source[0]["ir"], "sourcePages": source, "timeline": baseline, "provider": "codex"})
        node = page.locator(f'.svelte-flow__node[data-id="{node_id}"]')
        node.get_by_role("button", name="Открыть редактор", exact=True).click()
        page.get_by_label("Модель видео").last.select_option("gpt-6-astra")
        page.get_by_label("Уровень рассуждения").last.select_option("high")
        page.get_by_role("textbox", name="Промпт ИИ-режиссёра").fill("Создай меню и русский перевод")
        page.get_by_role("button", name="Отправить сообщение").click()
        expect(page.locator('[data-act="ai-preview"]')).to_be_visible()
        assert page.evaluate("id=>GraphDev.node(id).data.timeline", node_id) == baseline
        page.locator('[data-act="ai-apply"]').click()
        states = page.get_by_role("region", name="Созданные состояния")
        expect(states).to_be_visible()
        states.get_by_role("button", name="Показать в ролике").click()
        expect(page.locator('[data-story-page="menu"]')).to_have_css("opacity", "1")
        expect(page.locator('[data-story-page="menu"] [data-story-target="overlay.languages.ru"]')).to_have_text("Русский")
        states.get_by_label("Текст состояния", exact=True).select_option("overlays.0.items.2.text")
        editor = states.get_by_label("Изменить текст состояния")
        editor.fill("На русском")
        editor.press("Tab")
        page.wait_for_function("id=>GraphDev.node(id).data.timeline.story.pages.find(p=>p.id==='menu').overlays[0].items[2].text==='На русском'", arg=node_id)
        page.locator('.tlw-root [data-act="undo"]').click()
        expect(editor).to_have_value("Русский")
        page.locator('.tlw-root [data-act="redo"]').click()
        expect(editor).to_have_value("На русском")
        page.screenshot(path=str(OUT / "states-editor.png"))
        states.get_by_label("Состояние страницы").select_option("translated")
        states.get_by_role("button", name="Показать в ролике").click()
        expect(page.locator('[data-story-page="translated"]')).to_have_css("opacity", "1")
        current = page.evaluate("id=>GraphDev.node(id).data.timeline", node_id)
        assert current["story"]["pages"][:2] == baseline["story"]["pages"]
        page.locator('.tlw-root [data-act="close"]').click()
        page.wait_for_timeout(1800)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("id=>window.GraphDev?.node(id)?.data?.timeline?.story?.pages?.length===4", arg=node_id)
        assert page.evaluate("id=>GraphDev.node(id).data.timeline", node_id) == current
        assert page.evaluate("id=>GraphDev.node(id).data.model", node_id) == "gpt-6-astra"
        assert page.evaluate("id=>GraphDev.node(id).data.effort", node_id) == "high"
        assert not errors, errors
        browser.close()
    print("PASS: generated menu/translation preview, apply, manual menu text, undo/redo, source preservation and reload")


if __name__ == "__main__":
    main()
