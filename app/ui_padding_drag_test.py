"""Interactive canvas padding handles: live drag, IR commit, Undo, no inspector fields."""
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
FAILS = []

IR = {
    "version": "1.0",
    "meta": {"name": "Padding drag", "description": "test", "styleTags": ["test"]},
    "frame": {"width": 960, "height": 500},
    "responsive": {"viewports": {
        "desktop": {"width": 960, "height": 500},
        "tablet": {"width": 768, "height": 700},
        "mobile": {"width": 390, "height": 700},
    }},
    "tokens": {
        "mode": "light",
        "color": {"primary": "#6d28d9", "background": "#ffffff", "surface": "#f5f3ff", "text": "#111111"},
        "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}},
    },
    "tree": [{
        "id": "padding-section", "type": "feature-grid",
        "frame": {"width": "fill", "height": 300, "layout": "auto", "direction": "row", "gap": 16,
                  "padding": [20, 30, 20, 30]},
        "responsive": {"desktop": {"frame": {
            "width": "fill", "height": 300, "layout": "auto", "direction": "row", "gap": 16,
            "padding": [20, 30, 20, 30],
        }}},
        "children": [
            {"type": "card", "frame": {"width": 180, "height": 100}},
            {"type": "card", "frame": {"width": 180, "height": 100}},
        ],
    }],
}

NODE_IR = "window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir"
EDITOR_IR = "window.DNAEditor.getIR()"


def check(name, condition, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": node_id, "ir": IR})
        page.wait_for_timeout(500)
        page.click(".n-edit .f-open-editor")
        page.wait_for_selector('.dna-editor [data-ir-sec="0"]')
        page.click('.dna-editor [data-act="zoom-fit"]')
        page.wait_for_timeout(400)

        section = page.query_selector('.dna-editor [data-ir-sec="0"]')
        section_box = section.bounding_box()
        # Empty area on the right belongs to the section itself, not to either card.
        page.mouse.click(section_box["x"] + section_box["width"] - 50,
                         section_box["y"] + section_box["height"] / 2)
        page.wait_for_selector('.dna-editor .geo-pad[data-side="left"]')

        selected_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
        active_viewport = page.evaluate("document.querySelector('.fe-viewports [data-viewport].active')?.dataset.viewport || ''")
        check("section container is selected", selected_label.startswith("section"), selected_label)
        check("desktop viewport is active", active_viewport == "desktop", active_viewport)
        check("four padding handles are visible",
              page.locator(".dna-editor .geo-box.selected .geo-pad").count() == 4)
        check("padding inputs are removed from inspector",
              page.locator('.fe-inspector [data-pi="padv"], .fe-inspector [data-pi="padh"]').count() == 0)

        handle = page.query_selector('.dna-editor .geo-box.selected .geo-pad[data-side="left"]')
        handle_box = handle.bounding_box()
        scale = section.bounding_box()["width"] / page.evaluate(
            "document.querySelector('.dna-editor [data-ir-sec=\"0\"]').offsetWidth")
        page.mouse.move(handle_box["x"] + handle_box["width"] / 2,
                        handle_box["y"] + handle_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(handle_box["x"] + handle_box["width"] / 2 + 24 * scale,
                        handle_box["y"] + handle_box["height"] / 2, steps=8)
        page.mouse.up()
        page.wait_for_timeout(400)

        padding = page.evaluate(EDITOR_IR + ".tree[0].frame.padding")
        check("left drag commits only the left padding", padding == [20, 30, 20, 54], str(padding))
        desktop_padding = page.evaluate(EDITOR_IR + ".tree[0].responsive.desktop.frame.padding")
        rendered_left = page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.dna-editor [data-ir-sec=\"0\"]')).paddingLeft)")
        check("desktop override persists the padding", desktop_padding == [20, 30, 20, 54], str(desktop_padding))
        check("padding does not reset after rerender", rendered_left == 54, str(rendered_left))

        page.keyboard.press("Control+z")
        page.wait_for_timeout(400)
        undone = page.evaluate(EDITOR_IR + ".tree[0].frame.padding")
        check("Undo restores padding in one step", undone == [20, 30, 20, 30], str(undone))

        # Mobile edits must be stored in the mobile override and survive a
        # viewport round-trip, not only the immediate live preview.
        page.click('.fe-viewports [data-viewport="mobile"]')
        page.wait_for_timeout(350)
        mobile_section = page.query_selector('.dna-editor [data-ir-sec="0"]')
        page.click('.dna-editor .fe-layer[data-key="0:"]')
        page.wait_for_selector('.dna-editor .geo-box.selected .geo-pad[data-side="top"]')
        mobile_label = page.evaluate("document.querySelector('.geo-box.selected .geo-chip')?.textContent || ''")
        check("mobile section container is selected", mobile_label.startswith("section"), mobile_label)
        top_handle = page.query_selector('.dna-editor .geo-box.selected .geo-pad[data-side="top"]')
        top_box = top_handle.bounding_box()
        mobile_scale = mobile_section.bounding_box()["width"] / page.evaluate(
            "document.querySelector('.dna-editor [data-ir-sec=\"0\"]').offsetWidth")
        page.mouse.move(top_box["x"] + top_box["width"] / 2, top_box["y"] + top_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(top_box["x"] + top_box["width"] / 2,
                        top_box["y"] + top_box["height"] / 2 + 16 * mobile_scale, steps=6)
        page.mouse.up()
        page.wait_for_timeout(300)
        mobile_top_immediate = page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.dna-editor [data-ir-sec=\"0\"]')).paddingTop)")
        check("mobile padding persists after pointer-up", mobile_top_immediate == 36, str(mobile_top_immediate))
        page.click('.fe-viewports [data-viewport="desktop"]')
        page.wait_for_timeout(250)
        page.click('.fe-viewports [data-viewport="mobile"]')
        page.wait_for_timeout(350)
        mobile_top = page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.dna-editor [data-ir-sec=\"0\"]')).paddingTop)")
        check("mobile padding survives viewport round-trip", mobile_top == 36, str(mobile_top))
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS))
        sys.exit(1)
    print("ALL PADDING DRAG CHECKS PASSED")


if __name__ == "__main__":
    main()
