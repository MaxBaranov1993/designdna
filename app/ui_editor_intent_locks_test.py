"""Intent Locks persistence, visibility and AI enforcement checks."""
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
        "tree": [{"id": "hero", "type": "hero", "variant": "default", "props": {"heading": "Locked hero", "subheading": "Keep intent"}, "frame": {"width": "fill"}}],
    }


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
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
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.locator(".fe-layers .fe-layer.depth-1").first.click()
        page.click('[data-act="intent-locks"]')
        check("lock dialog targets current selection", page.locator(".fe-locks-list input").count() == 6)
        page.locator(".fe-locks-list input").nth(2).check()
        page.locator(".fe-locks-list input").nth(3).check()
        page.click('[data-act="apply-intent-locks"]')
        locks = page.evaluate("(id) => { const d = window.GraphDev.node(id).data; return (d._editorDraft?.ir || d.ir).tree[0].constraints.intentLocks; }", edit_id)
        check("locks persist in Design IR", set(locks) == {"geometry", "appearance"}, json.dumps(locks))
        check("locked section has a visible canvas badge", page.locator(".intent-locked").count() == 1)
        page.click('[data-act="smart-axis"]')
        check("Smart Axis skips geometry-locked selection", page.locator(".fe-smart-axis-card").count() == 0)
        page.click('[data-act="undo"]')
        undone = page.evaluate("(id) => { const d = window.GraphDev.node(id).data; return (d._editorDraft?.ir || d.ir).tree[0].constraints?.intentLocks || []; }", edit_id)
        check("lock operation is reversible with Undo", undone == [], json.dumps(undone))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL INTENT LOCK CHECKS PASSED")


if __name__ == "__main__":
    main()
