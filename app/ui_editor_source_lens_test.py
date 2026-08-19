"""Multi-source Edit inputs and Source Lens interaction checks."""
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


def component_ir(section_id: str, source_key: str, kind: str, heading: str) -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#4f46e5"}},
        "frame": {"width": 1200, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": section_id,
            "sourceKey": source_key,
            "type": kind,
            "variant": "default",
            "props": {"heading": heading, "subheading": f"{heading} content"},
            "frame": {"width": "fill", "layout": "auto", "direction": "column"},
        }],
    }


def parser_contract(source_id: str, label: str, source_key: str, symbol: str) -> dict:
    return {
        "version": "parser-source-envelope/1.0",
        "sourceRecord": {
            "id": source_id,
            "kind": "url",
            "label": label,
            "fingerprint": f"sha256:{source_id}",
            "colorToken": f"source.{source_id}",
            "symbol": symbol,
            "capturedAt": "2026-08-15T10:00:00Z",
            "parserVersion": "dom-v22",
            "confidence": 0.96,
        },
        "nodeStates": {source_key: {"status": ["linked"]}},
        "layoutEvidence": [],
        "viewports": {},
        "diagnostics": [],
    }


def main() -> None:
    header = component_ir("header", "header-root", "navbar", "Header")
    hero = component_ir("hero", "hero-root", "hero", "Hero")
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
        }""", {
            "ids": ids,
            "header": header,
            "hero": hero,
            "headerContract": parser_contract("source-header", "Imported header", "header-root", "H"),
            "heroContract": parser_contract("source-hero", "Custom hero", "hero-root", "B"),
        })
        page.wait_for_timeout(100)
        connected = page.evaluate("""(ids) => [
          window.GraphDev.connect(ids.header, 'header', ids.edit, 'a'),
          window.GraphDev.connect(ids.hero, 'hero', ids.edit, 'b'),
        ]""", ids)
        check("both parser components connect directly to Edit", connected == [True, True], json.dumps(connected))
        composed = page.evaluate("""(id) => {
          const data=window.GraphDev.node(id).data;
          return {sections:data.ir.tree.map(s=>s.id), sources:Object.keys(data.sourceRegistry), refs:data.nodeSources};
        }""", ids["edit"])
        check("Edit composes inputs in port order", composed["sections"] == ["header", "hero"], json.dumps(composed))
        check("source registry survives composition", len(composed["sources"]) == 2, json.dumps(composed))

        page.click(f'.svelte-flow__node[data-id="{ids["edit"]}"] .f-open-editor')
        page.wait_for_selector(".fe-source-lens")
        check("Source Lens exposes two clear source chips", page.locator(".fe-source-filter").count() == 2)
        marks = page.evaluate("""() => Array.from(document.querySelectorAll('.dna-editor [data-ir-sec]')).map(el => ({
          cls:el.className, color:getComputedStyle(el).getPropertyValue('--source-color'), symbol:el.dataset.sourceSymbol
        }))""")
        check("sections receive different source colors", len(marks) == 2 and marks[0]["color"] != marks[1]["color"], json.dumps(marks))

        section = page.locator('.dna-editor [data-ir-sec="1"]').bounding_box()
        page.mouse.click(section["x"] + 8, section["y"] + 8)
        page.wait_for_timeout(80)
        origin = page.locator(".fe-source-origin")
        check("selection reveals its source in Inspector", origin.count() == 1 and "Custom hero" in origin.inner_text())

        page.locator(".fe-source-filter").first.click()
        page.wait_for_timeout(50)
        check("source filter dims the other source", page.locator(".source-lens-dim").count() == 1)
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SOURCE LENS CHECKS PASSED")


if __name__ == "__main__":
    main()
