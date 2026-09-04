"""Browser regression for Design System component insertion order and refs."""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright


BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:8420")
FAILS: list[str] = []
MASTER_HASH = "sha256:" + "a" * 64


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILS.append(name)


def wait_ready(page) -> None:
    for _ in range(40):
        try:
            page.goto(BASE + "/flow", timeout=2_000)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"server not ready at {BASE}")


def main() -> int:
    component_requests: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.set_default_timeout(8_000)
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"revision":"test-1"}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true,"revision":"test-2"}'))
        page.route("**/api/design-system/get", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"document": {"components": {"promo-card": {
                "componentKey": "promo-card",
                "name": "Promo card",
                "category": "content",
                "variants": {
                    "default": {"label": "Default", "origin": "observed"},
                    "dark": {"label": "Dark", "origin": "user"},
                },
            }}}}),
        ))

        def component_section(route) -> None:
            request = route.request.post_data_json or {}
            component_requests.append(request)
            ref = {
                "systemId": "ds-test",
                "revision": 3,
                "componentKey": "promo-card",
                "masterHash": MASTER_HASH,
            }
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "name": "Promo card",
                    "section": {
                        "id": "ds-promo-card",
                        "type": "source-block",
                        "variant": "component-master",
                        "props": {},
                        "children": [{
                            "type": "card",
                            "sourceMeta": {"kind": "dom", "componentRef": ref},
                            "children": [{"type": "text", "typeRole": "body", "text": "Promo"}],
                        }],
                    },
                    "meta": {"fontFaces": []},
                    "componentRef": ref,
                }),
            )

        page.route("**/api/design-system/component-section", component_section)
        wait_ready(page)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && window.__flowStore")
        page.evaluate("""() => {
          window.GraphDev.clear();
        }""")
        edit_id = page.evaluate("window.GraphDev.add('edit', 60, 40).id")
        ir = {
            "version": "1.1",
            "tokens": {},
            "tree": [
                {"id": "first", "type": "composition", "children": [
                    {"type": "heading", "level": 2, "typeRole": "h2", "text": "First"}]},
                {"id": "second", "type": "composition", "children": [
                    {"type": "heading", "level": 2, "typeRole": "h2", "text": "Second"}]},
            ],
        }
        page.evaluate("(v) => window.GraphDev.setIR(v.id, v.ir)", {"id": edit_id, "ir": ir})
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor[style*="flex"]')

        page.locator('.fe-layer[data-key="0:"]').click()
        page.wait_for_selector('.fe-layer[data-key="0:"].selected')
        page.evaluate("""() => window.__flowStore.setState({designSystems: {
          systems: [{systemId: 'ds-test', name: 'Test DS', status: 'published', revision: 3}],
          defaultSystemRef: {systemId: 'ds-test', revision: 3},
        }})""")
        page.locator('.dna-editor [data-act="components"]').click()
        page.wait_for_selector("[data-components-panel]")
        page.locator('[data-component-key="promo-card"] select').select_option("dark")
        page.locator('[data-component-insert="promo-card"]').click()
        page.wait_for_function(
            "id => window.GraphDev.node(id).data._editorDraft?.ir?.tree?.length === 3",
            arg=edit_id,
        )
        inserted = page.evaluate("id => window.GraphDev.node(id).data._editorDraft.ir.tree", edit_id)
        check("selected insertion follows selected section", [section.get("id") for section in inserted] == [
            "first", "ds-promo-card", "second"], json.dumps(inserted, ensure_ascii=False))
        ref = inserted[1]["children"][0]["sourceMeta"]["componentRef"]
        check("inserted component keeps exact componentRef", ref == {
            "systemId": "ds-test", "revision": 3, "componentKey": "promo-card", "masterHash": MASTER_HASH,
        }, json.dumps(ref))
        check("selected variant is requested", component_requests[0].get("variantKey") == "dark", str(component_requests))

        page.locator('[data-components-panel] [data-act="close-components"]').click()
        page.wait_for_selector("[data-components-panel]", state="detached")
        page.locator('.dna-editor [data-viewport="desktop"]').click()
        page.locator('.dna-editor [data-act="components"]').click()
        page.wait_for_selector("[data-components-panel]")
        page.locator('[data-component-insert="promo-card"]').click()
        page.wait_for_function(
            "id => window.GraphDev.node(id).data._editorDraft?.ir?.tree?.length === 4",
            arg=edit_id,
        )
        appended = page.evaluate("id => window.GraphDev.node(id).data._editorDraft.ir.tree", edit_id)
        check("insertion without selection appends", [section.get("id") for section in appended] == [
            "first", "ds-promo-card", "second", "ds-promo-card-2"], json.dumps(appended, ensure_ascii=False))
        browser.close()

    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL EDITOR COMPONENT PANEL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
