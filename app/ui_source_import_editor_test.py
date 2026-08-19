"""Source Import 2.0 -> DNA Editor responsive interaction checks."""
from __future__ import annotations

import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright


BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []

SOURCE_IR = {
    "version": "1.0",
    "meta": {"name": "Responsive imported header"},
    "frame": {"width": 800, "height": 72, "layout": "auto", "direction": "row"},
    "responsive": {"viewports": {
        "desktop": {"width": 800, "height": 72, "preview": "data:image/png;base64,reference"},
        "tablet": {"width": 768, "height": 72, "preview": "data:image/png;base64,reference"},
        "mobile": {"width": 390, "height": 180, "preview": "data:image/png;base64,reference"},
    }},
    "tokens": {"color": {"background": "#ffffff", "text": "#111111"}},
    "tree": [{
        "id": "imported-block", "type": "source-block", "variant": "dom-capture", "sourceKey": "root",
        "frame": {"width": 800, "height": 72, "layout": "auto", "direction": "row", "gap": 12,
                  "padding": [14, 16, 14, 16], "clip": True},
        "responsive": {
            "tablet": {"visible": True, "frame": {"width": 768, "height": 72, "layout": "auto",
                                                         "direction": "row", "gap": 10, "padding": [14, 12, 14, 12]}},
            "mobile": {"visible": True, "frame": {"width": 390, "height": 180, "layout": "auto",
                                                         "direction": "column", "gap": 8, "padding": 10}},
        },
        "children": [
            {"type": "card", "role": "brand", "sourceKey": "root/div:1",
             "frame": {"width": 160, "height": 44, "layout": "auto", "direction": "row", "gap": 8},
             "children": [{"type": "text", "text": "Market", "sourceKey": "root/div:1::text0",
                           "frame": {"width": 80, "height": 20}}]},
            {"type": "input", "placeholder": "Search", "sourceKey": "root/input:1",
             "frame": {"width": "fill", "height": 44, "layout": "auto", "direction": "row", "padding": [0, 12]},
             "children": [{"type": "text", "text": "Search", "sourceKey": "root/input:1::value",
                           "frame": {"width": "hug", "height": "hug"}}]},
            {"type": "button", "text": "Find", "variant": "primary", "sourceKey": "root/button:1",
             "style": {"background": "#f97316", "color": "#ffffff", "borderRadius": 8},
             "frame": {"width": 100, "height": 44, "layout": "auto", "direction": "row", "padding": [0, 18],
                       "justify": "center", "align": "center"},
             "responsive": {"mobile": {"visible": True, "frame": {"width": 120, "height": 44,
                 "layout": "auto", "direction": "row", "padding": [0, 18], "justify": "center", "align": "center"}}},
             "children": [{"type": "text", "text": "Find", "sourceKey": "root/button:1::text0",
                           "style": {"color": "#ffffff"}, "frame": {"width": 32, "height": 18}}]},
        ],
    }],
}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.route(
            "**/api/project/load",
            lambda route: route.fulfill(status=200, content_type="application/json",
                                        body='{"project":null,"updated_at":null}'),
        )
        page.route(
            "**/api/project/save",
            lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'),
        )
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("server not ready")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && window.IRRenderer && window.DNAEditor")
        node_id = page.evaluate("window.GraphDev.add('edit', 80, 60).id")
        page.evaluate("(v) => window.GraphDev.setIR(v.id, v.ir)", {"id": node_id, "ir": SOURCE_IR})
        page.wait_for_function(
            "(id) => document.querySelector(`.svelte-flow__node[data-id=\"${id}\"] .edit-preview-card .ir-preview`)?.offsetHeight < 100",
            arg=node_id,
        )
        compact_preview = page.evaluate("""(id) => {
          const preview=document.querySelector(`.svelte-flow__node[data-id="${id}"] .edit-preview-card .ir-preview`);
          const art=preview.querySelector('[data-design-width]');
          return {previewHeight:preview.offsetHeight, renderedHeight:art.getBoundingClientRect().height};
        }""", node_id)
        check("Edit node preview hugs the rendered source artboard",
              compact_preview["previewHeight"] < 100 and
              abs(compact_preview["previewHeight"] - compact_preview["renderedHeight"]) <= 2,
              json.dumps(compact_preview))
        page.click(f'.svelte-flow__node[data-id="{node_id}"] .f-open-editor')
        page.wait_for_selector('.dna-editor [data-ir-path="children.2.children.0"]')

        desktop = page.evaluate("""() => ({
          art: [document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]').offsetWidth,
                document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]').offsetHeight],
          underlays: document.querySelectorAll('.dna-editor .source-underlay').length,
          viewportVisible: !document.querySelector('.dna-editor .fe-viewports').hidden,
          buttonChildren: document.querySelector('.fe-canvas-inner [data-ir-path="children.2"]').querySelectorAll('[data-ir-path]').length,
          sectionLayout: getComputedStyle(document.querySelector('.dna-editor [data-ir-sec="0"]')).display,
          canonicalLayout: window.GraphDev.node(%d).data.ir.tree[0].frame.layout,
          activeLayout: window.DNAEditor.getIR().tree[0].frame.layout,
        })""" % node_id)
        check("desktop artboard uses source viewport", desktop["art"] == [800, 72], json.dumps(desktop))
        check("source screenshot is not an editor underlay", desktop["underlays"] == 0, json.dumps(desktop))
        check("responsive viewport control is visible", desktop["viewportVisible"], json.dumps(desktop))
        check("button renders its real nested text layer", desktop["buttonChildren"] == 1, json.dumps(desktop))
        check("source section renders as auto-layout",
              desktop["sectionLayout"] == "flex" and desktop["canonicalLayout"] == "auto" and desktop["activeLayout"] == "auto",
              json.dumps(desktop))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(150)
        mobile = page.evaluate("""() => {
          const art = document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]');
          const button = document.querySelector('.fe-canvas-inner [data-ir-path="children.2"]');
          return {art:[art.offsetWidth,art.offsetHeight], buttonWidth:button.offsetWidth,
                  buttonCss:button.getAttribute('style'), buttonFrame:window.DNAEditor.getIR().tree[0].children[2].frame,
                  active:document.querySelector('[data-viewport="mobile"]').classList.contains('active')};
        }""")
        check("mobile switches the same artboard to 390x180", mobile["art"] == [390, 180], json.dumps(mobile))
        check("mobile frame override is applied", mobile["buttonWidth"] == 120 and mobile["active"], json.dumps(mobile))

        page.click('.dna-editor [data-viewport="tablet"]')
        page.wait_for_timeout(150)
        tablet = page.evaluate("""() => {
          const art = document.querySelector('.dna-editor .fe-canvas-inner div[class^="ir-"]');
          const section = document.querySelector('.dna-editor [data-ir-sec="0"]');
          return {art:[art.offsetWidth,art.offsetHeight], display:getComputedStyle(section).display,
                  direction:getComputedStyle(section).flexDirection,
                  activeLayout:window.DNAEditor.getIR().tree[0].frame.layout};
        }""")
        check("tablet keeps imported auto-layout",
              tablet["art"] == [768, 72] and tablet["display"] == "flex" and
              tablet["direction"] == "row" and tablet["activeLayout"] == "auto",
              json.dumps(tablet))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(120)

        point = page.evaluate("""() => {
          const el=document.querySelector('.fe-canvas-inner [data-ir-path="children.2.children.0"]'); const r=el.getBoundingClientRect();
          return {x:r.left+r.width/2,y:r.top+r.height/2};
        }""")
        page.mouse.click(point["x"], point["y"])
        selected_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
        check("single click selects the component container", selected_label.startswith("button"), selected_label)

        before = page.evaluate("""() => { const r=document.querySelector('.fe-canvas-inner [data-ir-path="children.2"]').getBoundingClientRect(); return [r.left,r.top]; }""")
        page.mouse.move(point["x"], point["y"])
        page.mouse.down()
        page.mouse.move(point["x"] + 35, point["y"] + 8, steps=5)
        page.mouse.up()
        page.wait_for_timeout(120)
        drag_state = page.evaluate("""() => {
          const ir=window.DNAEditor.getIR(); const button=ir.tree[0].children[2];
          const r=document.querySelector('.fe-canvas-inner [data-ir-path="children.2"]').getBoundingClientRect();
          return {parentLayout:ir.tree[0].frame.layout, absolute:button.frame.absolute, x:button.frame.x,
                  moved:[r.left,r.top]};
        }""")
        check("free drag keeps the parent auto-layout", drag_state["parentLayout"] == "auto", json.dumps(drag_state))
        check("free drag detaches only the selected component", drag_state["absolute"] is True and drag_state["x"] >= 0,
              json.dumps({"before": before, **drag_state}))

        page.evaluate("window.DNAEditor.getIR().tree[0].children[1].children[0].text = 'Search everywhere'")
        page.click('.dna-editor [data-viewport="desktop"]')
        page.wait_for_timeout(120)
        desktop_after_edit = page.evaluate("""() => ({
          buttonFrame:window.DNAEditor.getIR().tree[0].children[2].frame,
          search:document.querySelector('.fe-canvas-inner [data-ir-path="children.1.children.0"]').textContent,
        })""")
        check("text edits are shared between viewports", desktop_after_edit["search"] == "Search everywhere",
              json.dumps(desktop_after_edit))
        check("mobile drag does not change desktop layout",
              desktop_after_edit["buttonFrame"].get("absolute") is not True, json.dumps(desktop_after_edit))

        page.click('.dna-editor [data-viewport="mobile"]')
        page.wait_for_timeout(120)
        mobile_after_return = page.evaluate("window.DNAEditor.getIR().tree[0].children[2].frame")
        check("breakpoint-specific layout survives viewport switching",
              mobile_after_return.get("absolute") is True and mobile_after_return.get("x") == drag_state["x"],
              json.dumps(mobile_after_return))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SOURCE IMPORT EDITOR CHECKS PASSED")


if __name__ == "__main__":
    main()
