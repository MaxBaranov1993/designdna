"""Browser checks for arbitrary canvas width and responsive override controls."""
from __future__ import annotations

import copy
import sys
import time

from playwright.sync_api import sync_playwright

from ui_source_import_editor_test import SOURCE_IR
import ir

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []

CARD_ROW_IR = ir.ensure_current({
    "version": "1.1",
    "frame": {"width": 1440, "layout": "auto", "direction": "column"},
    "tokens": copy.deepcopy(SOURCE_IR["tokens"]),
    "tree": [{
        "id": "cards", "type": "feature-grid", "variant": "cards", "props": {},
        "frame": {"width": "fill", "layout": "auto", "direction": "column", "gap": 32, "padding": 24},
        "children": [{
            "type": "card", "role": "card-row",
            "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 24},
            "children": [{
                "type": "card", "title": f"Card {index + 1}",
                "frame": {"width": "fill", "minWidth": 260, "height": 160},
            } for index in range(3)],
        }],
    }],
})


def check(name: str, condition: bool, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def select_find_button(page):
    page.wait_for_function("""() => {
      return document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1"]')
        || document.querySelector('.fe-canvas-inner [data-ir-path="children.2"]')
        || document.querySelector('.fe-canvas-inner [data-ir-path="children.2.children.0"]');
    }""")
    point = page.evaluate("""() => {
      const el = document.querySelector('.fe-canvas-inner [data-ir-path="root/button:1"]')
        || document.querySelector('.fe-canvas-inner [data-ir-path="children.2"]')
        || document.querySelector('.fe-canvas-inner [data-ir-path="children.2.children.0"]');
      const rect = el.getBoundingClientRect();
      return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
    }""")
    page.mouse.click(point["x"], point["y"])
    page.wait_for_timeout(200)


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
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")
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
        mobile_override = page.evaluate("id => { const d=window.GraphDev.node(id).data; const ir=d._editorDraft?.ir||d.ir; return ir.tree[0].children[2].responsive?.mobile || null; }", node_id)
        check("Reset override removes current device patch", mobile_override is None, str(mobile_override))

        select_find_button(page)
        page.click('.fe-shared-insp [data-act="stretch-width"]')
        widths = page.evaluate("""id => {
          const d=window.GraphDev.node(id).data; const ir=d._editorDraft?.ir||d.ir; const node=ir.tree[0].children[2];
          return { shared: node.frame.width, mobile: node.responsive?.mobile?.frame?.width };
        }""", node_id)
        check("Stretch writes a mobile-only fluid width", widths["shared"] == 100 and widths["mobile"] == "fill", str(widths))

        text_input = page.locator('[data-el-prop="text"]')
        text_input.fill("Buy now")
        text_input.press("Tab")
        edited_text = page.evaluate("id => { const d=window.GraphDev.node(id).data; return (d._editorDraft?.ir||d.ir).tree[0].children[2].text; }", node_id)
        check("Mobile inspector text edit persists in canonical content", edited_text == "Buy now", str(edited_text))

        page.click('[data-responsive-act="reset"]')

        select_find_button(page)
        page.click('[data-responsive-copy="tablet"]')
        tablet_frame = page.evaluate("id => { const d=window.GraphDev.node(id).data; return (d._editorDraft?.ir||d.ir).tree[0].children[2].responsive?.tablet?.frame || null; }", node_id)
        check("Copy to breakpoint writes explicit tablet frame", isinstance(tablet_frame, dict) and tablet_frame.get("width") == 100, str(tablet_frame))

        page.click('.dna-editor [data-act="close"]')
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": node_id, "ir": copy.deepcopy(CARD_ROW_IR)})
        page.click(".n-edit .f-open-editor")
        page.click('.dna-editor [data-viewport="tablet"]')
        page.wait_for_timeout(200)
        tablet_cards = page.evaluate("""() => {
          const row = document.querySelector('.dna-editor [data-ir-path="children.0"]');
          const cards = [...row.querySelectorAll(':scope > [data-ir-path]')];
          const boxes = cards.map(card => card.getBoundingClientRect());
          return {overflow:row.scrollWidth - row.clientWidth,
                  rows:new Set(boxes.map(box => Math.round(box.top))).size,
                  firstRow:boxes.filter(box => Math.abs(box.top - boxes[0].top) < 2).length};
        }""")
        check("tablet wraps generated cards into two columns",
              tablet_cards["overflow"] <= 1 and tablet_cards["rows"] == 2 and tablet_cards["firstRow"] == 2,
              str(tablet_cards))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(200)
        mobile_cards = page.evaluate("""() => {
          const row = document.querySelector('.dna-editor [data-ir-path="children.0"]');
          const cards = [...row.querySelectorAll(':scope > [data-ir-path]')];
          const boxes = cards.map(card => card.getBoundingClientRect());
          return {overflow:row.scrollWidth - row.clientWidth,
                  rows:new Set(boxes.map(box => Math.round(box.top))).size,
                  widths:boxes.map(box => Math.round(box.width))};
        }""")
        check("mobile stacks generated cards without overflow",
              mobile_cards["overflow"] <= 1 and mobile_cards["rows"] == 3 and
              max(mobile_cards["widths"]) - min(mobile_cards["widths"]) <= 1,
              str(mobile_cards))
        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL FLUID RESPONSIVE CHECKS PASSED")


if __name__ == "__main__":
    main()
