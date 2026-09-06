"""Browser regression with isolated persistence and an explicitly stubbed AI response.

Live account execution is checked separately by video_account_smoke.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from timeline_director import direct

BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:8437")
OUTPUT = Path(__file__).resolve().parents[1] / "results" / "video-stage1"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    live = json.loads((OUTPUT / "codex-live.json").read_text(encoding="utf-8"))
    saved = None
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def save(route):
            nonlocal saved
            saved = route.request.post_data_json["project"]
            route.fulfill(json={"ok": True, "revision": "test-revision"})

        def assist(route):
            body = route.request.post_data_json
            assert body["provider"] in ("codex", "claude") and body["require_llm"]
            timeline, changes, meta = direct(body["timeline"], body["prompt"], allow_llm=False)
            route.fulfill(json={"timeline": timeline, "changeSet": changes, "preview": True, **meta})

        page.route("**/api/project/load", lambda route: route.fulfill(json={"project": saved, "revision": "test-revision"}))
        page.route("**/api/project/save", save)
        page.route("**/api/timeline/assist", assist)
        page.goto(BASE + "/flow")
        page.wait_for_function("window.GraphDev")
        page.evaluate("window.GraphDev.clear()")
        source_id = page.evaluate("window.GraphDev.add('page', 150, 130).id")
        node_id = page.evaluate("window.GraphDev.add('timeline', 640, 130).id")
        page.evaluate("v => { GraphDev.patchData(v.source, {ir:v.ir}); GraphDev.connect(v.source,'ir',v.node,'ir'); GraphDev.fit(); }", {"source": source_id, "node": node_id, "ir": live["ir"]})
        node = page.locator(f'.svelte-flow__node[data-id="{node_id}"]')
        node.get_by_label("Промпт видео").fill("Плавное интро снизу")
        expect(node.get_by_role("combobox", name="Провайдер")).to_have_value("codex")
        expect(node.get_by_role("combobox", name="Провайдер").locator("option")).to_have_count(2)
        page.screenshot(path=str(OUTPUT / "video-node.png"))
        node.get_by_role("button", name="Создать по промпту").click()
        page.locator('[data-act="ai-preview"]').wait_for()
        baseline = page.evaluate("id => GraphDev.node(id).data.timeline", node_id)
        page.locator('[data-act="ai-apply"]').click()
        page.wait_for_function("id => GraphDev.node(id).data.revisions?.length === 2", arg=node_id)
        first = page.evaluate("id => GraphDev.node(id).data.revisions[1]", node_id)
        page.locator('[data-act="layer"]').first.click()
        page.locator('[data-act="ruler"]').focus()
        page.keyboard.press("ArrowRight")
        page.locator('[data-act="add-keyframe"]').click()
        page.wait_for_timeout(650)
        manual = page.evaluate("id => GraphDev.node(id).data.timeline", node_id)
        page.locator('[data-act="ai-prompt"]').fill("Добавь медленный наезд камеры")
        page.locator('[data-act="ai-run"]').click()
        page.locator('[data-act="ai-apply"]').click()
        page.wait_for_function("id => GraphDev.node(id).data.revisions?.length === 4", arg=node_id)
        history = page.evaluate("id => GraphDev.node(id).data.revisions", node_id)
        assert history[2]["kind"] == "manual" and history[2]["timeline"] == manual
        page.locator('[data-act="video-history"]').click()
        versions = page.get_by_role("region", name="История монтажа")
        versions.locator(".video-version").filter(has=page.get_by_text(first["label"], exact=True)).get_by_role("button", name="Вернуться").click()
        page.wait_for_function("id => GraphDev.node(id).data.revisions?.length === 5", arg=node_id)
        current = page.evaluate("id => GraphDev.node(id).data", node_id)
        assert current["timeline"] == first["timeline"]
        assert current["revisions"][-1]["parentId"] == first["id"]
        assert current["revisions"][:4] == history
        assert current["revisions"][0]["timeline"] == baseline
        ruler = page.locator('[data-act="ruler"]')
        ruler.click(position={"x": 500, "y": 12})
        page.screenshot(path=str(OUTPUT / "video-history.png"))
        page.locator('.tlw-root [data-act="close"]').click()
        page.wait_for_timeout(1800)
        assert saved is not None
        # Clear browser storage: this reload must restore the saved project response.
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("id => window.GraphDev?.node(id)?.data?.revisions?.length === 5", arg=node_id)
        reloaded = page.evaluate("id => GraphDev.node(id).data", node_id)
        assert reloaded["revisions"] == current["revisions"]
        assert reloaded["timeline"] == current["timeline"]
        assert reloaded["activeRevisionId"] == current["activeRevisionId"]
        assert not errors, errors
        browser.close()
    print("PASS: node prompt / AI preview / apply / manual checkpoint / branch restore / database reload; no browser errors", flush=True)


if __name__ == "__main__":
    main()
