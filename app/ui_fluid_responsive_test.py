"""Browser checks for arbitrary canvas width and responsive override controls."""
from __future__ import annotations

import copy
import sys
import time

from playwright.sync_api import sync_playwright

from ui_source_import_editor_test import SOURCE_IR

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, condition: bool, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def select_find_button(page):
    point = page.evaluate("""() => {
      const el = document.querySelector('.fe-canvas-inner [data-ir-path="children.2.children.0"]');
      const rect = el.getBoundingClientRect();
      return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
    }""")
    page.mouse.click(point["x"], point["y"])


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            sys.exit(2)

        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": node_id, "ir": copy.deepcopy(SOURCE_IR)})
        page.click(".n-edit .f-open-editor")

        width = page.locator(".fe-viewport-width")
        width.fill("900")
        width.press("Enter")
        page.wait_for_timeout(200)
        state = page.evaluate("() => ({active:document.querySelector('[data-viewport].active').dataset.viewport, width:document.querySelector('.fe-canvas-inner > div').offsetWidth})")
        check("900 px resolves tablet breakpoint", state["active"] == "tablet" and state["width"] == 900, str(state))

        width.fill("500")
        width.press("Enter")
        page.wait_for_timeout(200)
        select_find_button(page)
        status = page.locator(".fe-responsive-status").inner_text()
        check("inspector identifies mobile override", "mobile" in status and "frame mobile" in status, status)

        page.click('[data-responsive-act="reset"]')
        mobile_override = page.evaluate("id => window.GraphDev.node(id).data.ir.tree[0].children[2].responsive?.mobile || null", node_id)
        check("Reset override removes current device patch", mobile_override is None, str(mobile_override))

        select_find_button(page)
        page.click('[data-responsive-copy="tablet"]')
        tablet_frame = page.evaluate("id => window.GraphDev.node(id).data.ir.tree[0].children[2].responsive?.tablet?.frame || null", node_id)
        check("Copy to breakpoint writes explicit tablet frame", isinstance(tablet_frame, dict) and tablet_frame.get("width") == 100, str(tablet_frame))
        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL FLUID RESPONSIVE CHECKS PASSED")


if __name__ == "__main__":
    main()
