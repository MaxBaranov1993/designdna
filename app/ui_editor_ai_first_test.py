"""Live browser acceptance for the compact AI-first inspector."""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).parent / "fixtures" / "frame-example.json"
SCREENSHOT = pathlib.Path(__file__).parent.parent / "artifacts" / "ai-first-inspector.png"
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    counter = 0
    def add_keys(node):
        nonlocal counter
        node["sourceKey"] = f"ui:{counter}"; counter += 1
        for child in node.get("children") or []: add_keys(child)
    for section in ir["tree"]: add_keys(section)
    requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        page.set_default_timeout(5000)
        page.on("pageerror", lambda error: print("PAGE ERROR:", error))

        def mock_assist(route):
            payload = route.request.post_data_json
            requests.append(payload)
            candidate = copy.deepcopy(payload["ir"])
            selected = set(payload["scope"]["sourceKeys"])
            ops = []
            def visit(node, path):
                if node.get("sourceKey") in selected:
                    node.setdefault("style", {})["opacity"] = 0.8
                    ops.append({"op": "add", "path": path + "/style/opacity", "after": 0.8, "reason": "UI test"})
                for index, child in enumerate(node.get("children") or []): visit(child, f"{path}/children/{index}")
            for index, section in enumerate(candidate["tree"]): visit(section, f"/tree/{index}")
            for source_key in selected:
                if not source_key.startswith("editor:/"):
                    continue
                parts = source_key.removeprefix("editor:/").split("/")
                parent = candidate
                for part in parts[:-1]:
                    parent = parent[int(part)] if isinstance(parent, list) else parent[part]
                last = parts[-1]
                before_value = parent[int(last)] if isinstance(parent, list) else parent[last]
                if isinstance(before_value, str):
                    after_value = "Заголовок от AI"
                    if isinstance(parent, list): parent[int(last)] = after_value
                    else: parent[last] = after_value
                    ops.append({"op": "replace", "path": source_key.removeprefix("editor:"), "before": before_value, "after": after_value, "reason": "UI scalar test"})
            if "много" in payload["prompt"].lower() and ops:
                seed = ops[0]
                ops = [{**seed, "path": seed["path"], "after": round(0.71 + index / 100, 2), "reason": f"UI test {index + 1}"} for index in range(9)]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "summary": "Выделение обновлено", "ops": ops, "previewIr": candidate,
                "changedViewports": [], "warnings": [],
                "validation": {"schema": True, "overflow": [], "constraints": []},
            }))

        page.route("**/api/editor/assist", mock_assist)
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000); break
            except Exception: time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        edit_id = page.evaluate("window.GraphDev.add('edit', 60, 40).id")
        page.evaluate("(v) => window.GraphDev.setIR(v.id, v.ir)", {"id": edit_id, "ir": ir})
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor[style*="flex"]')
        page.wait_for_timeout(500)

        # The top bar stays focused on viewport and AI actions; cryptic manual
        # glyphs are available as labelled controls in the inspector instead.
        for action in [
            "align-left", "align-center-h", "align-right", "align-top",
            "align-center-v", "align-bottom", "distribute-h", "distribute-v",
            "forward", "backward", "group", "ungroup", "undo", "redo", "style-dna",
            "smart-axis", "quality-gate", "harmonize", "responsive-autopilot",
            "intent-locks", "semantic-select",
        ]:
            assert page.locator(f'.fe-toolbar [data-act="{action}"]').count() == 0, action

        for viewport, label in [("mobile", "Mobile"), ("tablet", "Tablet"), ("desktop", "Desktop")]:
            button = page.locator(f'.fe-viewports [data-viewport="{viewport}"]')
            assert button.get_by_text(label, exact=True).count() == 1, viewport
            assert button.locator(".fe-device-icon").count() == 1, viewport
            button.click()
            assert "active" in (button.get_attribute("class") or ""), viewport

        def click_path(path):
            target = page.locator(f'.fe-layer[data-key="0:{path}"]')
            assert target.count() == 1, f"missing layer {path}"
            target.click()
            page.wait_for_selector("[data-ai-inspector]")

        # Every concrete element kind exposes the same clear AI entry point.
        for path in ["children.0", "children.0.children.0", "children.0.children.1", "children.0.children.2", "children.0.children.3", "children.0.children.4.children.1"]:
            click_path(path)
            assert page.locator("[data-ai-inspector]").count() == 1, path
            assert page.get_by_text("Что изменить?", exact=True).count() == 1, path

        # Semantic scalar props are honestly text-only and remain AI-editable.
        click_path("props.heading")
        assert page.locator(".ai-quick-row").count() == 0
        for label in ["Стиль", "Размеры", "Цвета"]:
            assert page.get_by_label(label, exact=True).is_disabled()
        page.locator(".ai-command-card textarea").fill("Замени заголовок")
        page.locator(".ai-run").click()
        page.wait_for_selector('[data-ai-preview="ready"]')
        assert page.locator(".ai-diff li").count() == 1
        page.locator("[data-ai-apply]").click()
        page.wait_for_timeout(150)
        scalar_draft = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        assert scalar_draft["tree"][0]["props"]["heading"] == "Заголовок от AI"

        inspector_text = page.locator(".fe-inspector").inner_text()
        for removed in ["Position", "Flex Layout", "Dimensions", "Appearance"]:
            assert removed not in inspector_text

        # Padding is scoped to the selected card.
        click_path("children.0")
        page.locator(".manual-controls summary").click()
        page.locator('[data-padding="t"]').fill("23")
        page.locator('[data-padding="t"]').press("Tab")
        page.wait_for_timeout(180)
        draft = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        assert draft["tree"][0]["children"][0]["frame"]["padding"][0] == 23

        # Font, Fill and Text work immediately on a text element.
        click_path("children.0.children.2")
        page.locator(".manual-controls summary").click()
        page.locator('.font-family select').select_option("Inter")
        page.locator(".manual-controls summary").click()
        page.locator('[data-style-num="fontSize"]').fill("31")
        page.locator('[data-style-num="fontSize"]').press("Tab")
        page.locator(".manual-controls summary").click()
        page.locator(".manual-color .pi-cp-swatch").nth(0).click()
        assert page.locator(".pi-cp-pop").count() == 1
        page.locator(".pi-cp-hex").fill("aa2222")
        page.locator(".pi-cp-hex").press("Enter")
        page.keyboard.press("Escape")
        page.locator(".manual-color .pi-cp-swatch").nth(1).click()
        assert page.locator(".pi-cp-pop").count() == 1
        page.locator(".pi-cp-hex").fill("dddddd")
        page.locator(".pi-cp-hex").press("Enter")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        draft = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        heading = draft["tree"][0]["children"][0]["children"][2]
        assert heading["style"]["fontFamily"] == "Inter"
        assert heading["style"]["fontSize"] == 31
        assert heading["style"]["background"] == "#aa2222"
        assert heading["style"]["color"] == "#dddddd"
        heading_css = page.locator('.fe-canvas [data-ir-path="children.0.children.2"] h3').evaluate(
            "el => ({ background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el).color })")
        assert heading_css == {"background": "rgb(170, 34, 34)", "color": "rgb(221, 221, 221)"}

        # The same Fill/Text controls reach both button shell and inner label.
        click_path("children.0.children.4.children.1")
        page.locator(".manual-controls summary").click()
        page.locator('[data-style-text="background"]').fill("#334455")
        page.locator('[data-style-text="background"]').press("Tab")
        page.locator('[data-style-text="color"]').fill("#fefefe")
        page.locator('[data-style-text="color"]').press("Tab")
        page.wait_for_timeout(150)
        draft = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        button = draft["tree"][0]["children"][0]["children"][4]["children"][1]
        assert button["style"]["background"] == "#334455"
        assert button["style"]["color"] == "#fefefe"
        button_css = page.locator('.fe-canvas a[data-ir-path="children.0.children.4.children.1"]').evaluate(
            "el => ({ background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el.querySelector('span') || el).color })")
        assert button_css == {"background": "rgb(51, 68, 85)", "color": "rgb(254, 254, 254)"}

        click_path("children.0.children.2")
        if not page.locator(".manual-controls").evaluate("el => el.open"):
            page.locator(".manual-controls summary").click()
        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT), full_page=True)

        # Multi-selection makes the scope explicit and sends all selected source keys.
        click_path("children.0.children.0")
        page.locator('.fe-layer[data-key="0:children.0.children.1"]').evaluate(
            "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true, shiftKey:true}))")
        page.wait_for_timeout(200)
        assert page.locator(".fe-layer.selected").count() == 2
        assert page.locator(".ai-scope-chip").count() == 2
        assert "Shift/Ctrl/Cmd — группа" in page.locator(".fe-layers-hint").inner_text()
        click_path("children.0.children.0")
        badge_box = page.locator('.fe-canvas [data-ir-path="children.0.children.1"]').first.bounding_box()
        page.keyboard.down("Control")
        page.keyboard.down("Shift")
        page.mouse.click(badge_box["x"] + badge_box["width"] / 2, badge_box["y"] + badge_box["height"] / 2)
        page.keyboard.up("Shift")
        page.keyboard.up("Control")
        page.wait_for_timeout(250)
        selected_count = page.locator(".fe-layer.selected").count()
        assert selected_count > 1, page.locator(".ai-scope").inner_text()
        selected_layers = page.locator(".fe-layer.selected").evaluate_all("els => els.map(el => el.dataset.key)")
        assert selected_layers == ["0:children.0.children.0", "0:children.0.children.1"], selected_layers
        assert page.locator(".ai-scope-switch").count() == 1
        assert page.locator(".ai-scope-chip").count() == 2

        # Parent + child is normalized to the specific child before AI runs.
        click_path("children.0")
        page.locator('.fe-layer[data-key="0:children.0.children.0"]').evaluate(
            "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true, shiftKey:true}))")
        page.wait_for_timeout(200)
        assert page.locator(".ai-scope-chip").count() == 1
        assert "исключён" in page.locator(".ai-scope-warning").inner_text()
        click_path("children.0.children.0")
        badge_box = page.locator('.fe-canvas [data-ir-path="children.0.children.1"]').first.bounding_box()
        page.keyboard.down("Control"); page.keyboard.down("Shift")
        page.mouse.click(badge_box["x"] + badge_box["width"] / 2, badge_box["y"] + badge_box["height"] / 2)
        page.keyboard.up("Shift"); page.keyboard.up("Control")
        page.wait_for_timeout(200)

        # Merge and unmerge preserve the two independently editable children.
        page.locator(".manual-controls summary").click()
        page.get_by_role("button", name="Объединить").click()
        page.wait_for_timeout(200)
        grouped = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return (d._editorDraft?.ir || d.ir).tree[0].children[0].children[0]; }", edit_id)
        assert grouped["type"] == "card" and grouped["frame"]["layout"] == "free" and len(grouped["children"]) == 2
        page.locator(".manual-controls summary").click()
        page.get_by_role("button", name="Разъединить").click()
        page.wait_for_timeout(200)
        restored = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return (d._editorDraft?.ir || d.ir).tree[0].children[0].children.slice(0,2).map(n=>n.type); }", edit_id)
        assert restored == ["image", "badge"]

        page.locator(".manual-controls summary").click()
        page.locator('.manual-controls [data-act="align-left"]').click()
        page.wait_for_timeout(200)
        aligned = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return (d._editorDraft?.ir || d.ir).tree[0].children[0].children.slice(0,2).map(n=>n.frame?.x); }", edit_id)
        assert aligned[0] == aligned[1]
        click_path("children.0.children.0")
        badge_box = page.locator('.fe-canvas [data-ir-path="children.0.children.1"]').first.bounding_box()
        page.keyboard.down("Control"); page.keyboard.down("Shift")
        page.mouse.click(badge_box["x"] + badge_box["width"] / 2, badge_box["y"] + badge_box["height"] / 2)
        page.keyboard.up("Shift"); page.keyboard.up("Control")
        page.wait_for_timeout(200)
        assert page.locator(".fe-layer.selected").count() == 2
        selected_count = 2
        before = page.evaluate("(id) => JSON.stringify((window.GraphDev.node(id).data._editorDraft?.ir || window.GraphDev.node(id).data.ir))", edit_id)
        page.locator(".ai-command-card textarea").fill("Сделай группу спокойнее")
        page.get_by_label("Цвета").uncheck()
        page.locator(".ai-run").click()
        page.wait_for_selector('[data-ai-preview="ready"]')
        assert page.get_by_label("Цвета").is_checked() is False
        assert len(requests[-1]["scope"]["sourceKeys"]) == selected_count
        assert requests[-1]["constraints"]["allowColor"] is False
        assert page.locator(".ai-diff li").count() == selected_count
        assert page.locator(".ai-changed-node").count() == selected_count
        during = page.evaluate("(id) => JSON.stringify((window.GraphDev.node(id).data._editorDraft?.ir || window.GraphDev.node(id).data.ir))", edit_id)
        assert during == before
        page.locator("[data-ai-cancel]").click()
        assert page.locator('[data-ai-preview="ready"]').count() == 0
        page.locator(".ai-command-card textarea").fill("Сделай группу спокойнее")
        page.locator(".ai-run").click()
        page.wait_for_selector('[data-ai-preview="ready"]')
        page.locator("[data-ai-apply]").click()
        page.wait_for_timeout(250)
        applied = page.evaluate("(id) => { const d=window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }", edit_id)
        selected_keys = set(requests[-1]["scope"]["sourceKeys"])
        changed = {}
        def collect(node):
            changed[node["sourceKey"]] = node
            for child in node.get("children") or []: collect(child)
        for section in applied["tree"]: collect(section)
        node_selected = selected_keys.intersection(changed)
        assert len(node_selected) > 1
        assert all(changed[key]["style"]["opacity"] == 0.8 for key in node_selected)

        # Large previews cannot be applied accidentally.
        click_path("children.0.children.2")
        page.locator(".ai-command-card textarea").fill("Сделай много безопасных изменений")
        page.locator(".ai-run").click()
        page.wait_for_selector(".ai-impact")
        assert page.locator("[data-ai-apply]").is_disabled()
        page.get_by_label("Я проверил изменения").check()
        assert page.locator("[data-ai-apply]").is_enabled()
        page.locator("[data-ai-cancel]").click()
        browser.close()
    print("ALL AI-FIRST INSPECTOR CHECKS PASSED")


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print("FAILED:", exc)
        raise
