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
        }, {
            "id": "generated-hero",
            "type": "generated-section",
            "variant": "hero",
            "frame": {"width": "fill", "height": 520, "layout": "free"},
            "children": [
                {"type": "badge", "text": "Тысячи продавцов — один умный выбор", "frame": {"x": 64, "y": 52, "width": 370, "height": 32}},
                {"type": "heading", "level": 1, "text": "Всё, что нужно, уже на одной витрине", "style": {"fontSize": 54}, "frame": {"x": 64, "y": 104, "width": 620, "height": 130}},
                {"type": "text", "text": "Сравнивайте предложения, находите честные цены и заказывайте у проверенных продавцов.", "frame": {"x": 64, "y": 254, "width": 560, "height": 72}},
                {"type": "button", "text": "Найти товар", "frame": {"x": 64, "y": 354, "width": 150, "height": 44}},
                {"type": "image", "alt": "Подборка популярных товаров", "frame": {"x": 760, "y": 64, "width": 560, "height": 340}},
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
        page.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        page.click('[data-act="responsive-autopilot"]')
        page.wait_for_selector('[data-act="apply-responsive-autopilot"]')
        panel = page.locator(".fe-responsive-card").inner_text()
        check("Autopilot previews three target widths", all(value in panel for value in ("1440", "768", "390")), panel)
        before = page.evaluate("(id) => window.GraphDev.node(id).data.ir.responsive || null", edit_id)
        check("responsive preview leaves canonical IR untouched", before is None, json.dumps(before))
        page.click('[data-act="apply-responsive-autopilot"]')
        applied = page.evaluate("""(id) => {
          const ir=window.GraphDev.node(id).data._editorDraft.ir, sec=ir.tree[0];
          return {mobile:ir.responsive.viewports.mobile.width,direction:sec.responsive.mobile.frame.direction,child:sec.children[0].responsive.mobile.frame.width};
        }""", edit_id)
        check("Autopilot applies viewport, reflow and width constraints", applied == {"mobile": 390, "direction": "column", "child": "fill"}, json.dumps(applied))
        page.locator('[data-viewport="mobile"]').evaluate("el => el.click()")
        page.wait_for_timeout(250)
        visual = page.evaluate("""() => {
          const root=document.querySelector('.fe-canvas-inner [data-design-width="390"]');
          const section=root && root.querySelector('[data-ir-sec="1"]');
          const nodes=section ? [...section.querySelectorAll(':scope > [data-ir-path]')] : [];
          const bounds=section && section.getBoundingClientRect();
          const heading=section && section.querySelector('h1');
          const button=section && section.querySelector('.btn');
          return {
            root:!!root, section:!!section,
            overflow:bounds ? nodes.filter(node => {
              const r=node.getBoundingClientRect();
              return r.left < bounds.left - 1 || r.right > bounds.right + 1;
            }).length : -1,
            positions:nodes.map(node => getComputedStyle(node).position),
            headingSize:heading ? parseFloat(getComputedStyle(heading).fontSize) : 0,
            buttonMinHeight:button ? parseFloat(getComputedStyle(button).minHeight) : 0,
            sectionHeight:section ? section.getBoundingClientRect().height : 0,
          };
        }""")
        check("mobile free hero reflows without horizontal clipping", visual["root"] and visual["section"] and visual["overflow"] == 0, json.dumps(visual))
        check("mobile free hero leaves absolute desktop positioning", all(value != "absolute" for value in visual["positions"]), json.dumps(visual))
        check("mobile heading and CTA remain readable", visual["headingSize"] <= 34 and visual["buttonMinHeight"] >= 44 and visual["sectionHeight"] > 500, json.dumps(visual))
        page.locator('.fe-canvas').screenshot(path=r'C:\Users\iamma\AppData\Local\Temp\designai-mobile-adaptation-after.png')
        page.click('[data-act="undo"]')
        undone = page.evaluate("(id) => window.GraphDev.node(id).data._editorDraft.ir.responsive || null", edit_id)
        check("responsive patch is reversible with Undo", undone is None, json.dumps(undone))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL RESPONSIVE AUTOPILOT CHECKS PASSED")


if __name__ == "__main__":
    main()
