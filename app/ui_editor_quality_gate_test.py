"""Editor-native Quality Copilot preview/apply/undo checks."""
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


def document(gap: int) -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#4f46e5"}},
        "frame": {"width": 1200, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": "hero",
            "type": "hero",
            "variant": "default",
            "props": {"heading": "Quality", "subheading": "Preview before apply"},
            "frame": {"width": "fill", "layout": "auto", "direction": "column", "gap": gap},
        }],
    }


def main() -> None:
    original = document(13)
    fixed = document(16)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        page.route("**/api/quality-gate", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "passed": False,
                "violations": [{"rule": "grid-8", "path": "tree.0.frame.gap", "severity": "minor", "message": "Gap не кратен сетке 8px"}],
                "fixed_ir": fixed,
                "journal": [{"path": "tree.0.frame.gap", "from": 13, "to": 16}],
            }),
        ))
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
        page.evaluate("(v) => window.GraphDev.patchData(v.id, {ir:v.ir})", {"id": edit_id, "ir": original})
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.click('[data-act="quality-gate"]')
        page.wait_for_selector(".fe-quality-card")
        page.wait_for_selector('[data-act="apply-quality-fixes"]')
        check("Quality Copilot explains the issue", "Gap не кратен" in page.locator(".fe-quality-card").inner_text())
        before = page.evaluate("(id) => window.GraphDev.node(id).data.ir.tree[0].frame.gap", edit_id)
        check("quality preview leaves IR untouched", before == 13, str(before))
        page.click('[data-act="apply-quality-fixes"]')
        applied = page.evaluate("(id) => window.GraphDev.node(id).data._editorDraft.ir.tree[0].frame.gap", edit_id)
        check("prepared fix applies atomically", applied == 16, str(applied))
        page.click('[data-act="undo"]')
        undone = page.evaluate("(id) => window.GraphDev.node(id).data._editorDraft.ir.tree[0].frame.gap", edit_id)
        check("quality fix is reversible with Undo", undone == 13, str(undone))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL EDITOR QUALITY GATE CHECKS PASSED")


if __name__ == "__main__":
    main()
