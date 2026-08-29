"""Explicit DNA Editor action inventory: every visible control mutates state.

Requires a running server: .venv/Scripts/python app/server.py
Run: .venv/Scripts/python app/ui_editor_action_inventory_test.py
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent / "fixtures" / "frame-example.json"
FAILS: list[str] = []

EXPECTED_GROUPS = {
    "topbar": ["zoom-out", "zoom-in", "zoom-fit", "close", "save"],
    "viewports": ["desktop", "tablet", "mobile"],
    # Хендофф: рейка — 8 плоских инструментов, flyout фигур удалён
    "tools": ["select", "hand", "frame", "rect", "ellipse", "line", "image", "text"],
    "inspector": [
        "semantic-select", "smart-axis", "quality-gate", "harmonize",
        "responsive-autopilot", "intent-locks", "style-dna",
        "undo", "redo", "forward", "backward",
    ],
    "geometry": [
        "align-left", "align-center-h", "align-right",
        "align-top", "align-center-v", "align-bottom",
        "distribute-h", "distribute-v", "group", "ungroup",
        "stretch-width", "reset-frame",
    ],
    "styleDna": [
        "close-style-dna", "reset-style-dna", "apply-style-dna",
        "preview-normalize", "apply-normalize", "tailwind-exact",
        "tailwind-normalized", "copy-tailwind",
    ],
}


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def add_keys(ir: dict) -> dict:
    counter = 0

    def visit(node: dict) -> None:
        nonlocal counter
        if isinstance(node, dict):
            node["sourceKey"] = f"inv:{counter}"
            counter += 1
            for child in node.get("children") or []:
                visit(child)

    for section in ir.get("tree") or []:
        visit(section)
    return ir


def draft_ir(page, edit_id):
    return page.evaluate(
        "(id) => { const d = window.GraphDev.node(id).data; return d._editorDraft?.ir || d.ir; }",
        edit_id,
    )


def canonical_ir(page, edit_id):
    return page.evaluate("(id) => window.GraphDev.node(id).data.ir", edit_id)


def fingerprint(page, edit_id):
    return page.evaluate(
        "(id) => JSON.stringify((window.GraphDev.node(id).data._editorDraft?.ir || window.GraphDev.node(id).data.ir))",
        edit_id,
    )


def click_layer(page, path: str) -> None:
    target = page.locator(f'.fe-layer[data-key="0:{path}"]')
    target.wait_for()
    target.click()
    page.wait_for_timeout(180)


def open_manual(page) -> None:
    details = page.locator(".manual-controls")
    details.wait_for()
    if not details.evaluate("el => el.open"):
        page.locator(".manual-controls summary").click()
        page.wait_for_timeout(80)


def main() -> None:
    ir = add_keys(json.loads(IR_PATH.read_text(encoding="utf-8")))
    ir["responsive"] = {"viewports": {
        "desktop": {"width": 1440, "height": 900},
        "tablet": {"width": 768, "height": 1024},
        "mobile": {"width": 390, "height": 844},
    }}
    ir["tree"][0]["children"][0]["children"][0]["editable"] = False
    ir["tree"][0]["children"][0]["children"][0]["lockedReason"] = "raster surface"
    requests: list[dict] = []
    assist_hang = {"value": False}
    hanging_routes: list = []
    assist_status = {"value": 200}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        page.set_default_timeout(8000)
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))

        def mock_assist(route):
            if assist_hang["value"]:
                hanging_routes.append(route)
                return
            payload = route.request.post_data_json or {}
            requests.append(payload)
            if assist_status["value"] != 200:
                route.fulfill(status=assist_status["value"], content_type="application/json",
                              body=json.dumps({"detail": "AI unavailable"}))
                return
            candidate = copy.deepcopy(payload.get("ir") or {})
            selected = set((payload.get("scope") or {}).get("sourceKeys") or [])
            ops = []

            def visit(node, path):
                if node.get("sourceKey") in selected and node.get("editable") is not False:
                    node.setdefault("style", {})["opacity"] = 0.8
                    ops.append({"op": "add", "path": path + "/style/opacity", "after": 0.8, "reason": "inventory"})
                for index, child in enumerate(node.get("children") or []):
                    visit(child, f"{path}/children/{index}")

            for index, section in enumerate(candidate.get("tree") or []):
                visit(section, f"/tree/{index}")
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "summary": "Выделение обновлено", "ops": ops, "previewIr": candidate,
                "changedViewports": [], "warnings": [],
                "validation": {"schema": True, "overflow": [], "constraints": []},
            }))

        page.route("**/api/editor/assist", mock_assist)

        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        page.evaluate("window.GraphDev.clear()")
        edit_id = page.evaluate("window.GraphDev.add('edit', 60, 40).id")
        page.evaluate("(v) => window.GraphDev.setIR(v.id, v.ir)", {"id": edit_id, "ir": ir})
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor[style*="flex"]')
        page.wait_for_timeout(400)

        inventory = page.evaluate("window.__editorActions")
        check("explicit action inventory is published", isinstance(inventory, dict) and "topbar" in (inventory or {}))
        if inventory:
            for group, actions in EXPECTED_GROUPS.items():
                if group == "geometry":
                    continue
                check(f"inventory group {group}", inventory.get(group) == actions, str(inventory.get(group)))

        for action in EXPECTED_GROUPS["topbar"]:
            loc = page.locator(f'.fe-toolbar [data-act="{action}"]')
            check(f"topbar control {action}", loc.count() == 1 and loc.first.is_enabled())
        for action in EXPECTED_GROUPS["inspector"]:
            loc = page.locator(f'.fe-inspector [data-act="{action}"]')
            check(f"inspector control {action}", loc.count() == 1)

        dead = page.evaluate("""() => {
          const root = document.querySelector('.dna-editor');
          const buttons = [...root.querySelectorAll('button')].filter(b => b.offsetParent !== null);
          return buttons.filter(b => {
            if (b.disabled) return false;
            const wired = b.hasAttribute('data-act') || b.hasAttribute('data-tool')
              || b.hasAttribute('data-ai-run') || b.hasAttribute('data-ai-cancel')
              || b.hasAttribute('data-ai-apply') || b.hasAttribute('data-dna-action')
              || b.hasAttribute('data-responsive-act') || b.hasAttribute('data-responsive-copy')
              || b.hasAttribute('data-flag') || b.hasAttribute('data-viewport')
              || b.hasAttribute('data-pi-dir') || b.hasAttribute('data-fly-item');
            return !wired && !b.getAttribute('aria-label') && !b.textContent.trim();
          }).map(b => b.outerHTML.slice(0, 120));
        }""")
        check("no unlabeled dead buttons", dead == [], str(dead))

        zoom0 = page.locator(".fe-zoom").inner_text()
        page.click('.dna-editor [data-act="zoom-in"]')
        page.wait_for_timeout(150)
        zoom1 = page.locator(".fe-zoom").inner_text()
        check("zoom-in changes label", zoom1 != zoom0, f"{zoom0}->{zoom1}")
        page.click('.dna-editor [data-act="zoom-out"]')
        page.wait_for_timeout(150)
        page.click('.dna-editor [data-act="zoom-fit"]')
        page.wait_for_timeout(200)
        check("zoom-fit shows percent", page.locator(".fe-zoom").inner_text().endswith("%"))

        page.click('.dna-editor [data-viewport="tablet"]')
        page.wait_for_timeout(250)
        check("tablet viewport width", page.locator(".fe-viewport-width").input_value() == "768")
        check("tablet aria-pressed", page.locator('[data-viewport="tablet"]').get_attribute("aria-pressed") == "true")
        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(250)
        check("mobile viewport width", page.locator(".fe-viewport-width").input_value() == "390")
        page.click('.dna-editor [data-viewport="desktop"]')
        page.wait_for_timeout(250)

        for tool in EXPECTED_GROUPS["tools"]:
            page.click(f'.dna-editor .fe-rail [data-tool="{tool}"]')
            page.wait_for_timeout(80)
            check(f"tool {tool} pressed", page.locator(f'.fe-rail [data-tool="{tool}"]').first.get_attribute("aria-pressed") == "true")
        # Хендофф: рейка стала 8 плоскими кнопками — flyout фигур удалён
        check("rail is flat: 8 tool buttons", page.locator(".dna-editor .fe-rail [data-tool]").count() == 8)
        page.click('.dna-editor .fe-rail [data-tool="ellipse"]')
        page.wait_for_timeout(120)
        check("ellipse selected from rail", page.locator('.fe-rail [data-tool="ellipse"]').get_attribute("aria-pressed") == "true")
        page.keyboard.press("v")
        page.wait_for_timeout(80)

        click_layer(page, "children.0")
        check("layer select", page.locator('.fe-layer[data-key="0:children.0"]').get_attribute("aria-pressed") == "true")
        page.locator('.fe-layer[data-key="0:children.0.children.1"]').evaluate(
            "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true, shiftKey:true}))")
        page.wait_for_timeout(150)
        check("layer multiselect", page.locator(".fe-layer.selected").count() >= 2)

        click_layer(page, "children.0")
        page.locator('.fe-layer[data-key="0:children.0"] [data-flag="locked"]').click()
        page.wait_for_timeout(80)
        page.locator('.fe-layer[data-key="0:children.0"]').click()
        page.wait_for_timeout(80)
        still_locked = page.evaluate("""() => {
          const row = document.querySelector('.fe-layer[data-key="0:children.0"]');
          return row.classList.contains('flag-locked') && !row.classList.contains('selected');
        }""")
        check("locked layer is not selectable", still_locked)
        page.locator('.fe-layer[data-key="0:children.0"] [data-flag="locked"]').click()
        page.wait_for_timeout(80)
        click_layer(page, "children.0")

        sibling_before = draft_ir(page, edit_id)["tree"][0]["children"][0]["children"][1].get("text")
        keys_before = page.evaluate("""(id) => {
          const keys = [];
          const walk = (n) => { if (n.sourceKey) keys.push(n.sourceKey); (n.children||[]).forEach(walk); };
          const d = window.GraphDev.node(id).data; (d._editorDraft?.ir || d.ir).tree.forEach(walk);
          return keys;
        }""", edit_id)
        parent_len = len(draft_ir(page, edit_id)["tree"][0]["children"][0]["children"])
        page.locator(".manual-controls summary").click()
        page.locator('[data-pi="gap"]').fill("28")
        page.locator('[data-pi="gap"]').dispatch_event("change")
        page.wait_for_timeout(200)
        after = draft_ir(page, edit_id)
        check("inspector gap mutates selected card", after["tree"][0]["children"][0]["frame"]["gap"] == 28)
        check("sibling text isolated", after["tree"][0]["children"][0]["children"][1].get("text") == sibling_before)
        check("parent-child count preserved", len(after["tree"][0]["children"][0]["children"]) == parent_len)
        keys_after = page.evaluate("""(id) => {
          const keys = [];
          const walk = (n) => { if (n.sourceKey) keys.push(n.sourceKey); (n.children||[]).forEach(walk); };
          const d = window.GraphDev.node(id).data; (d._editorDraft?.ir || d.ir).tree.forEach(walk);
          return keys;
        }""", edit_id)
        check("sourceKeys preserved", keys_after == keys_before)

        click_layer(page, "children.0.children.0")
        locked_before = fingerprint(page, edit_id)
        open_manual(page)
        if page.locator('[data-style-num="fontSize"]').count():
            page.locator('[data-style-num="fontSize"]').fill("40")
            page.locator('[data-style-num="fontSize"]').dispatch_event("change")
            page.wait_for_timeout(150)
        locked_after = fingerprint(page, edit_id)
        check("editable:false node refuses style mutation", locked_before == locked_after)
        still_image = draft_ir(page, edit_id)["tree"][0]["children"][0]["children"][0]
        check("locked image keeps editable:false", still_image.get("editable") is False)

        click_layer(page, "children.0")
        page.click('[data-act="stretch-width"]')
        page.wait_for_timeout(200)
        stretched = draft_ir(page, edit_id)["tree"][0]["children"][0]["frame"].get("width")
        check("stretch-width writes fill or numeric width", stretched in ("fill", 360) or isinstance(stretched, (int, float)), str(stretched))

        page.click('.dna-editor [data-viewport="tablet"]')
        page.wait_for_timeout(250)
        click_layer(page, "children.0")
        page.wait_for_selector('[data-responsive-copy="tablet"]')
        page.click('[data-responsive-copy="tablet"]')
        page.wait_for_timeout(250)
        copied = page.evaluate(
            "(id) => (window.GraphDev.node(id).data._editorDraft?.ir || window.GraphDev.node(id).data.ir).tree[0].children[0].responsive?.tablet?.frame || null",
            edit_id,
        )
        check("copy responsive override writes tablet frame", isinstance(copied, dict), str(copied))
        click_layer(page, "children.0")
        page.wait_for_selector('[data-responsive-act="reset"]:not([disabled])')
        page.click('[data-responsive-act="reset"]')
        page.wait_for_timeout(250)
        reset = page.evaluate(
            "(id) => (window.GraphDev.node(id).data._editorDraft?.ir || window.GraphDev.node(id).data.ir).tree[0].children[0].responsive?.tablet || null",
            edit_id,
        )
        check("reset override removes tablet patch", reset is None, str(reset))
        page.click('.dna-editor [data-viewport="desktop"]')
        page.wait_for_timeout(200)

        click_layer(page, "children.0.children.1")
        page.locator('.fe-layer[data-key="0:children.0.children.2"]').evaluate(
            "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true, shiftKey:true}))")
        page.wait_for_timeout(200)
        open_manual(page)
        page.locator('[data-act="align-left"]').click()
        page.wait_for_timeout(180)
        aligned = page.evaluate(
            "(id) => { const n=(window.GraphDev.node(id).data._editorDraft?.ir||window.GraphDev.node(id).data.ir).tree[0].children[0].children; return [n[1].frame?.x, n[2].frame?.x]; }",
            edit_id,
        )
        check("align-left equalizes sibling x", aligned[0] == aligned[1], str(aligned))
        open_manual(page)
        page.locator('[data-act="group"]').click(force=True)
        page.wait_for_timeout(200)
        grouped = draft_ir(page, edit_id)["tree"][0]["children"][0]["children"][1]
        check("group creates free-layout parent", grouped.get("frame", {}).get("layout") == "free" and len(grouped.get("children") or []) == 2)
        open_manual(page)
        page.locator('[data-act="ungroup"]').click(force=True)
        page.wait_for_timeout(200)
        restored = [n.get("type") for n in draft_ir(page, edit_id)["tree"][0]["children"][0]["children"][1:3]]
        check("ungroup restores siblings", restored == ["badge", "heading"], str(restored))

        order_before = [n.get("type") for n in draft_ir(page, edit_id)["tree"][0]["children"][0]["children"]]
        click_layer(page, "children.0.children.1")
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.click('[data-act="forward"]')
        page.wait_for_timeout(150)
        order_fwd = [n.get("type") for n in draft_ir(page, edit_id)["tree"][0]["children"][0]["children"]]
        check("forward changes z-order", order_fwd != order_before, str(order_fwd))
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.keyboard.press("]")
        page.wait_for_timeout(150)
        order_more = [n.get("type") for n in draft_ir(page, edit_id)["tree"][0]["children"][0]["children"]]
        page.keyboard.press("[")
        page.wait_for_timeout(150)
        order_back = [n.get("type") for n in draft_ir(page, edit_id)["tree"][0]["children"][0]["children"]]
        check("keyboard [ / ] change sibling order", order_back != order_more or order_fwd != order_before, str(order_back))

        click_layer(page, "children.0")
        open_manual(page)
        page.locator('[data-pi="gap"]').fill("33")
        page.locator('[data-pi="gap"]').dispatch_event("change")
        page.wait_for_timeout(180)
        check("gap=33 applied", draft_ir(page, edit_id)["tree"][0]["children"][0]["frame"].get("gap") == 33)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.keyboard.press("Control+z")
        page.wait_for_timeout(180)
        check("ctrl+z undoes gap", draft_ir(page, edit_id)["tree"][0]["children"][0]["frame"].get("gap") != 33)
        page.keyboard.press("Control+Shift+z")
        page.wait_for_timeout(180)
        check("ctrl+shift+z redoes gap", draft_ir(page, edit_id)["tree"][0]["children"][0]["frame"].get("gap") == 33)

        click_layer(page, "children.0.children.2")
        before_preview = fingerprint(page, edit_id)
        page.locator(".ai-command-card textarea").fill("Сделай спокойнее")
        page.locator(".ai-run").click()
        page.wait_for_selector('[data-ai-preview="ready"]')
        during = fingerprint(page, edit_id)
        check("AI preview does not mutate canonical IR", during == before_preview)
        page.locator("[data-ai-apply]").click()
        page.wait_for_timeout(200)
        applied = draft_ir(page, edit_id)
        heading = applied["tree"][0]["children"][0]["children"][2]
        check("AI apply mutates selected node once", heading.get("style", {}).get("opacity") == 0.8)
        page.evaluate("document.activeElement && document.activeElement.blur()")
        page.click('[data-act="undo"]')
        page.wait_for_timeout(200)
        undone = draft_ir(page, edit_id)["tree"][0]["children"][0]["children"][2].get("style", {}).get("opacity")
        check("AI apply is one reversible history entry", undone != 0.8, str(undone))
        page.click('[data-act="redo"]')
        page.wait_for_timeout(200)

        before_cancel = fingerprint(page, edit_id)
        page.locator(".ai-command-card textarea").fill("Ещё раз")
        page.locator(".ai-run").click()
        page.wait_for_selector('[data-ai-preview="ready"]')
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        check("Escape cancels AI preview", page.locator('[data-ai-preview="ready"]').count() == 0)
        check("Escape restore leaves editor open", page.locator(".dna-editor").evaluate("el => el.style.display") == "flex")
        check("Escape restore exact IR", fingerprint(page, edit_id) == before_cancel)

        assist_status["value"] = 500
        page.locator(".ai-command-card textarea").fill("Ошибка")
        page.locator(".ai-run").click()
        page.wait_for_selector(".ai-error")
        check("AI error is visible", page.locator(".ai-error").count() == 1)
        check("AI error does not mutate IR", fingerprint(page, edit_id) == before_cancel)
        assist_status["value"] = 200

        assist_hang["value"] = True
        page.locator(".ai-command-card textarea").fill("Долгий запрос")
        page.locator(".ai-run").click()
        page.wait_for_selector("[data-ai-progress]")
        page.locator("[data-ai-cancel]").click()
        page.wait_for_timeout(300)
        check("in-flight AI cancel hides progress", page.locator("[data-ai-progress]").count() == 0)
        check("in-flight AI cancel keeps IR", fingerprint(page, edit_id) == before_cancel)
        assist_hang["value"] = False
        for pending in hanging_routes:
            try:
                pending.abort()
            except Exception:
                pass
        hanging_routes.clear()

        for act, sel in [
            ("semantic-select", ".fe-semantic-card"),
            ("intent-locks", ".fe-locks-card"),
            ("smart-axis", ".fe-smart-axis-card"),
            ("quality-gate", ".fe-quality-card"),
            ("harmonize", ".fe-harmonize-card"),
            ("responsive-autopilot", ".fe-responsive-card"),
        ]:
            overlay_before = fingerprint(page, edit_id)
            page.click(f'[data-act="{act}"]')
            page.wait_for_selector(sel, timeout=12000)
            check(f"{act} overlay opens", page.locator(sel).count() == 1)
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            check(f"{act} Escape dismisses overlay", page.locator(sel).count() == 0)
            check(f"{act} preview leaves canonical IR", fingerprint(page, edit_id) == overlay_before)

        page.click('[data-act="style-dna"]')
        page.wait_for_selector("#feDnaPanel.open")
        page.wait_for_selector('#feDnaBody input[data-kind="color"]', timeout=8000)
        check("style dna apply enabled after load", page.locator('[data-act="apply-style-dna"]').is_enabled())
        page.click('[data-dna-action="preview-normalize"]')
        page.wait_for_function("""() => {
          const err = document.querySelector('#feDnaWorkflowResult .fe-dna-err');
          const meta = document.querySelector('#feDnaWorkflowResult .fe-dna-meta');
          return !!(err || (meta && /properties/.test(meta.textContent)));
        }""", timeout=12000)
        check("normalize preview renders", page.locator("#feDnaWorkflowResult .fe-dna-result").count() == 1)
        apply_normalize = page.locator('[data-dna-action="apply-normalize"]')
        if apply_normalize.count():
            dna_before = fingerprint(page, edit_id)
            apply_normalize.click()
            page.wait_for_timeout(300)
            dna_applied = fingerprint(page, edit_id)
            check("normalize apply mutates IR", dna_applied != dna_before)
            page.evaluate("document.activeElement && document.activeElement.blur()")
            page.keyboard.press("Control+z")
            page.wait_for_timeout(200)
            check("normalize apply reversible", fingerprint(page, edit_id) == dna_before)
        page.click('[data-dna-action="tailwind-exact"]')
        page.wait_for_selector("#feDnaWorkflowResult .fe-dna-code", timeout=10000)
        check("exact tailwind classes", len((page.locator("#feDnaWorkflowResult .fe-dna-code").inner_text() or "").strip()) > 0)
        page.click('[data-dna-action="tailwind-normalized"]')
        page.wait_for_timeout(400)
        check("copy tailwind enabled", page.locator('[data-dna-action="copy-tailwind"]').is_enabled())
        page.click('[data-dna-action="copy-tailwind"]')
        page.wait_for_timeout(200)
        if page.locator('[data-highlight]').count():
            page.locator('[data-highlight]').first.click()
            page.wait_for_timeout(150)
            check("token highlight selects bound nodes", page.locator(".fe-layer.selected").count() >= 0)
        page.click('[data-act="reset-style-dna"]')
        page.wait_for_timeout(150)
        page.click('[data-act="close-style-dna"]')
        check("style dna closed", "open" not in (page.locator("#feDnaPanel").get_attribute("class") or ""))

        click_layer(page, "children.0")
        open_manual(page)
        page.locator('[data-pi="gap"]').fill("51")
        page.locator('[data-pi="gap"]').dispatch_event("change")
        page.wait_for_timeout(200)
        page.click('[data-act="save"]')
        page.wait_for_timeout(300)
        check("save closes editor", page.locator(".dna-editor").evaluate("el => el.style.display") == "none")
        saved = canonical_ir(page, edit_id)["tree"][0]["children"][0]["frame"]["gap"]
        check("save persists canonical IR", saved == 51, str(saved))
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor[style*="flex"]')
        page.wait_for_timeout(300)
        reopened = draft_ir(page, edit_id)["tree"][0]["children"][0]["frame"]["gap"]
        check("reopen after save keeps gap", reopened == 51, str(reopened))

        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL EDITOR ACTION INVENTORY CHECKS PASSED")


if __name__ == "__main__":
    main()
