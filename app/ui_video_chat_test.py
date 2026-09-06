"""Isolated chat UX regression: question, follow-up, preview, stop, persistence."""
import json
import os
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from video_story import build_pages, direct_story
from video_story_fixtures import pages_fixture, plan_fixture

BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:9138")
OUT = Path(__file__).resolve().parents[1] / "results/video-chat"


def main():
    saved = None
    requests, errors = [], []
    pages = pages_fixture()
    baseline = build_pages(pages, {"width": 960, "height": 640, "duration": 8000})
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        def save(route):
            nonlocal saved
            saved = route.request.post_data_json["project"]
            route.fulfill(json={"ok": True, "revision": "chat-test"})
        def assist(route):
            body = route.request.post_data_json
            requests.append(body)
            if len(requests) == 1:
                route.fulfill(status=422, json={"error": "Нужно уточнить: Какое название товара указать?"})
            else:
                assert body["conversation"][-1]["content"] == "Какое название товара указать?"
                assert body["prompt"] == "Диван"
                with patch("video_story.llm.chat", return_value=json.dumps(plan_fixture())):
                    timeline, changes, meta = direct_story(body["timeline"], body["prompt"], "codex", "medium")
                route.fulfill(json={"timeline": timeline, "changeSet": changes, **meta})
        page.route("**/api/project/load", lambda route: route.fulfill(json={"project": saved, "revision": "chat-test"}))
        page.route("**/api/project/save", save)
        page.route("**/api/timeline/assist", assist)
        page.goto(BASE + "/flow")
        page.wait_for_function("window.GraphDev")
        page.evaluate("GraphDev.clear()")
        node_id = page.evaluate("v => {const n=GraphDev.add('timeline',150,100); GraphDev.patchData(n.id,v); GraphDev.fit(); return n.id;}",
            {"ir": pages[0]["ir"], "timeline": baseline, "sourcePages": pages, "provider": "codex"})
        node = page.locator(f'.svelte-flow__node[data-id="{node_id}"]')
        node.get_by_role("button", name="Открыть редактор", exact=True).click()
        chat = page.get_by_role("complementary", name="Чат с ИИ-режиссёром")
        expect(chat).to_be_visible()
        composer = chat.get_by_role("textbox", name="Промпт ИИ-режиссёра")
        composer.fill("Заполни форму")
        composer.press("Shift+Enter")
        expect(composer).to_have_value("Заполни форму\n")
        composer.press("Enter")
        expect(chat.get_by_text("Какое название товара указать?", exact=True)).to_be_visible()
        expect(chat.locator('[data-act="chat-message"]')).to_have_count(2)
        assert page.evaluate("id=>GraphDev.node(id).data.timeline", node_id) == baseline
        page.screenshot(path=str(OUT / "chat-question.png"))
        composer.fill("Диван")
        chat.get_by_role("button", name="Отправить сообщение").click()
        expect(chat.locator('[data-act="ai-preview"]')).to_be_visible()
        assert page.evaluate("id=>GraphDev.node(id).data.timeline", node_id) == baseline
        chat.locator('[data-act="ai-apply"]').click()
        expect(chat.get_by_text("✓ Изменения применены", exact=True)).to_be_visible()
        page.wait_for_function("id=>GraphDev.node(id).data.timeline.story.actions.length===8", arg=node_id)
        applied = page.evaluate("id=>GraphDev.node(id).data.timeline", node_id)
        # Simulate a transport that completes after Stop, including the desktop IPC case.
        page.evaluate("""() => {const original=window.fetch; window.fetch=(url, init)=>String(url)==='/api/timeline/assist'
            ? new Promise(resolve=>{window.finishLateChat=()=>resolve(new Response(JSON.stringify({error:'LATE RESPONSE'}),{status:422,headers:{'content-type':'application/json'}}));})
            : original(url, init); window.restoreChatFetch=()=>{window.fetch=original;};} """)
        composer.fill("Ещё плавнее")
        composer.press("Enter")
        expect(chat.locator('[data-act="ai-stop"]')).to_be_visible()
        page.wait_for_function("Boolean(window.finishLateChat)")
        chat.locator('[data-act="ai-stop"]').click()
        expect(chat.get_by_text("Запрос остановлен. Можно изменить сообщение и отправить снова.", exact=True)).to_be_visible()
        page.evaluate("finishLateChat(); restoreChatFetch()")
        page.wait_for_timeout(350)
        expect(chat.get_by_text("LATE RESPONSE")).to_have_count(0)
        assert page.evaluate("id=>GraphDev.node(id).data.timeline", node_id) == applied
        messages = page.evaluate("id=>GraphDev.node(id).data.chatMessages", node_id)
        assert len(messages) == 6 and messages[3]["kind"] == "applied"
        page.set_viewport_size({"width": 1366, "height": 768})
        expect(chat.locator('[data-act="ai-run"]')).to_be_in_viewport()
        page.screenshot(path=str(OUT / "chat-desktop.png"))
        page.locator('.tlw-root [data-act="close"]').click()
        page.wait_for_timeout(1800)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("id=>window.GraphDev?.node(id)?.data.chatMessages?.length===6", arg=node_id)
        assert page.evaluate("id=>GraphDev.node(id).data.chatMessages", node_id) == messages
        node.get_by_role("button", name="Открыть редактор", exact=True).click()
        expect(chat.get_by_text("Какое название товара указать?", exact=True)).to_be_attached()
        assert not errors, errors
        browser.close()
    print("PASS: visible clarification / multiline input / conversation context / preview and apply / stop and late response / 1366px layout / database reload")


if __name__ == "__main__":
    main()
