"""Responsive Autopilot preview/apply/undo checks."""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def document() -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#2563eb"}},
        "frame": {"width": 1440, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": "features",
            "type": "feature-grid",
            "variant": "cards",
            "props": {"heading": "Features"},
            "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 32},
            "children": [
                {"type": "card", "frame": {"width": 520, "layout": "auto", "direction": "column"}, "children": []},
                {"type": "card", "frame": {"width": 520, "layout": "auto", "direction": "column"}, "children": []},
            ],
        }],
    }


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        page.route("**/api/quality-gate", lambda route: route.fulfill(status=200, content_type="application/json", body='{"passed":true,"violations":[],"fixed_ir":{},"journal":[]}'))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev")
        edit_id = page.evaluate("window.GraphDev.add('edit', 200, 120).id")
        page.evaluate("(v) => window.GraphDev.patchData(v.id, {ir:v.ir})", {"id": edit_id, "ir": document()})
        page.click(f'.react-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.click('[data-act="responsive-autopilot"]')
        page.wait_for_selector('[data-act="apply-responsive-autopilot"]')
        panel = page.locator(".fe-responsive-card").inner_text()
        check("Autopilot previews three target widths", all(value in panel for value in ("1440", "768", "390")), panel)
        before = page.evaluate("(id) => window.GraphDev.node(id).data.ir.responsive || null", edit_id)
        check("responsive preview leaves canonical IR untouched", before is None, json.dumps(before))
        page.click('[data-act="apply-responsive-autopilot"]')
        applied = page.evaluate("""(id) => {
          const ir=window.GraphDev.node(id).data.ir, sec=ir.tree[0];
          return {mobile:ir.responsive.viewports.mobile.width,direction:sec.responsive.mobile.frame.direction,child:sec.children[0].responsive.mobile.frame.width};
        }""", edit_id)
        check("Autopilot applies viewport, reflow and width constraints", applied == {"mobile": 390, "direction": "column", "child": "fill"}, json.dumps(applied))
        page.click('[data-act="undo"]')
        undone = page.evaluate("(id) => window.GraphDev.node(id).data.ir.responsive || null", edit_id)
        check("responsive patch is reversible with Undo", undone is None, json.dumps(undone))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL RESPONSIVE AUTOPILOT CHECKS PASSED")


if __name__ == "__main__":
    main()
