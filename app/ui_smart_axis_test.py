"""AI Smart Axis preview/apply/undo checks for the fullscreen editor."""
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


def ir(section_id: str, source_key: str, kind: str, heading: str) -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#4f46e5"}},
        "frame": {"width": 1440, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": section_id,
            "sourceKey": source_key,
            "type": kind,
            "variant": "default",
            "props": {"heading": heading, "subheading": f"{heading} content"},
            "frame": {"width": "fill", "layout": "auto", "direction": "column"},
        }],
    }


def contract(source_id: str, label: str, source_key: str, width: int | None = None) -> dict:
    evidence = [] if width is None else [{
        "nodeRef": source_key,
        "role": "page-content",
        "anchor": "inner-content",
        "viewport": "desktop",
        "maxWidth": width,
        "inlineGutter": 32,
        "confidence": 0.98,
        "basis": "measured-dom",
    }]
    return {
        "version": "parser-source-envelope/1.0",
        "sourceRecord": {"id": source_id, "kind": "url", "label": label, "fingerprint": f"sha256:{source_id}", "colorToken": f"source.{source_id}", "symbol": label[0], "capturedAt": "2026-08-15T10:00:00Z", "parserVersion": "dom-v22", "confidence": 0.98},
        "nodeStates": {source_key: {"status": ["linked"]}},
        "layoutEvidence": evidence,
        "viewports": {},
        "diagnostics": [],
    }


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 980})
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
        ids = page.evaluate("""() => ({
          header: window.GraphDev.add('sourceimport', 40, 40).id,
          hero: window.GraphDev.add('sourceimport', 40, 500).id,
          edit: window.GraphDev.add('edit', 520, 180).id,
        })""")
        page.evaluate("""(v) => {
          window.GraphDev.patchData(v.ids.header, {blocks:[{name:'header',selector:'header',ir:v.header,lit:true,parserContract:v.headerContract}]});
          window.GraphDev.patchData(v.ids.hero, {blocks:[{name:'hero',selector:'main',ir:v.hero,lit:true,parserContract:v.heroContract}]});
          window.GraphDev.connect(v.ids.header, 'header', v.ids.edit, 'a');
          window.GraphDev.connect(v.ids.hero, 'hero', v.ids.edit, 'b');
        }""", {
            "ids": ids,
            "header": ir("header", "header-root", "navbar", "Header"),
            "hero": ir("hero", "hero-root", "hero", "Hero"),
            "headerContract": contract("source-header", "Imported header", "header-root", 960),
            "heroContract": contract("source-hero", "Custom hero", "hero-root"),
        })
        page.click(f'.react-flow__node[data-id="{ids["edit"]}"] .f-open-editor')
        page.click('[data-act="smart-axis"]')
        dialog = page.locator(".fe-smart-axis-card")
        check("AI proposes a preview before mutation", dialog.count() == 1)
        check("proposal uses measured source width", "960px" in dialog.inner_text(), dialog.inner_text())
        before = page.evaluate("(id) => window.GraphDev.node(id).data.ir.tree[1].frame.contentMaxWidth || null", ids["edit"])
        check("preview does not mutate IR", before is None, json.dumps(before))
        page.click('[data-act="apply-smart-axis"]')
        applied = page.evaluate("""(id) => {
          const sec=window.GraphDev.node(id).data.ir.tree[1];
          return {desktop:sec.frame.contentMaxWidth, tablet:sec.responsive.tablet.frame.contentMaxWidth, mobile:sec.responsive.mobile.frame.contentMaxWidth};
        }""", ids["edit"])
        check("apply binds desktop and responsive axes", applied == {"desktop": 960, "tablet": 720, "mobile": 358}, json.dumps(applied))
        page.click('[data-act="undo"]')
        undone = page.evaluate("(id) => window.GraphDev.node(id).data.ir.tree[1].frame.contentMaxWidth || null", ids["edit"])
        check("normal Undo reverses the atomic patch", undone is None, json.dumps(undone))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SMART AXIS CHECKS PASSED")


if __name__ == "__main__":
    main()
