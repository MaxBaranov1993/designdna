"""Cross-source Harmonizer preview/apply/undo checks."""
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


def document(primary: str) -> dict:
    return {
        "version": "1.1",
        "tokens": {
            "mode": "light",
            "color": {"primary": primary, "background": "#ffffff", "surface": "#f5f5f7", "text": "#111111", "textMuted": "#666666", "border": "#dddddd"},
            "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}, "scale": "default"},
            "radius": {"card": "md", "button": "md", "input": "md"}, "spacing": {"section": "md", "container": "default"}, "shadow": "sm",
        },
        "tree": [{"id": "hero", "type": "hero", "variant": "default", "props": {"heading": "One product", "subheading": "Two sources"}}],
    }


def main() -> None:
    original = document("#ff0000")
    harmonized = document("#5b5bd6")
    tokens = harmonized["tokens"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.route("**/api/project/load", lambda route: route.fulfill(status=200, content_type="application/json", body='{"project":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'))
        page.route("**/api/style-dna/extract", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tokens": tokens})))
        page.route("**/api/style-dna/apply", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"ir": harmonized})))
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
        page.evaluate("""(v) => window.GraphDev.patchData(v.id, {
          ir:v.ir,
          sourceRegistry:{a:{id:'a',kind:'url',label:'Header'},b:{id:'b',kind:'manual',label:'Hero'}},
          nodeSources:{hero:'b'}
        })""", {"id": edit_id, "ir": original})
        page.click(f'.react-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.click('[data-act="harmonize"]')
        page.wait_for_selector('[data-act="apply-harmonizer"]')
        text = page.locator(".fe-harmonize-card").inner_text()
        check("Harmonizer understands multi-source context", "2 источн." in text, text)
        check("Harmonizer previews typography and facets", "Inter" in text and "цвет · тип · радиус · тень" in text, text)
        before = page.evaluate("(id) => window.GraphDev.node(id).data.ir.tokens.color.primary", edit_id)
        check("Harmonizer preview does not mutate IR", before == "#ff0000", before)
        page.click('[data-act="apply-harmonizer"]')
        applied = page.evaluate("(id) => window.GraphDev.node(id).data.ir.tokens.color.primary", edit_id)
        check("Style DNA applies atomically", applied == "#5b5bd6", applied)
        page.click('[data-act="undo"]')
        undone = page.evaluate("(id) => window.GraphDev.node(id).data.ir.tokens.color.primary", edit_id)
        check("Harmonizer is reversible with Undo", undone == "#ff0000", undone)
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL EDITOR HARMONIZER CHECKS PASSED")


if __name__ == "__main__":
    main()
