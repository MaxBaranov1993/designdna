"""Natural-language semantic/source selection checks."""
from __future__ import annotations

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
        "tree": [
            {"id": "header", "sourceKey": "source-a::header", "type": "navbar", "variant": "default", "props": {"logoText": "Logo", "links": [{"label": "Home", "href": "#"}], "cta": {"text": "Sign in"}}},
            {"id": "hero", "sourceKey": "source-b::hero", "type": "hero", "variant": "default", "props": {"heading": "Build", "ctaPrimary": {"text": "Start"}, "ctaSecondary": {"text": "Demo"}}},
        ],
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
        page.evaluate("""(v) => window.GraphDev.patchData(v.id, {
          ir:v.ir,
          sourceRegistry:{a:{id:'a',kind:'url',label:'Imported header',symbol:'A'},b:{id:'b',kind:'manual',label:'Custom hero',symbol:'B'}},
          nodeSources:{'source-a::header':'a','source-b::hero':'b'}
        })""", {"id": edit_id, "ir": document()})
        page.click(f'.react-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.click('[data-act="semantic-select"]')
        page.locator(".fe-semantic-input input").fill("кнопки из Custom hero")
        page.click('[data-act="run-semantic-select"]')
        result = page.locator(".fe-semantic-result").inner_text()
        check("semantic query combines role and source", "2" in result, result)
        selected = page.locator(".fe-layer.selected").count()
        check("matching CTA layers become one multi-selection", selected == 2, str(selected))
        page.locator(".fe-semantic-input input").fill("Imported header")
        page.click('[data-act="run-semantic-select"]')
        source_result = page.locator(".fe-semantic-result").inner_text()
        check("source-only query selects the source section", "1" in source_result, source_result)
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SEMANTIC SELECTION CHECKS PASSED")


if __name__ == "__main__":
    main()
