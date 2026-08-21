"""Regression: an explicitly selected semantic section stays the geometry target."""
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
FAILS = []
IR = {
    "version": "1.0",
    "meta": {"name": "Section geometry", "description": "test", "styleTags": ["test"]},
    "frame": {"width": 960, "height": 600, "layout": "auto", "direction": "column"},
    "responsive": {"viewports": {
        "desktop": {"width": 960, "height": 600},
        "tablet": {"width": 768, "height": 720},
        "mobile": {"width": 390, "height": 760},
    }},
    "tokens": {
        "mode": "light",
        "color": {"primary": "#6d28d9", "background": "#fff", "surface": "#f5f3ff", "text": "#111"},
        "font": {"display": {"family": "Inter", "weight": 700}, "body": {"family": "Inter", "weight": 400}},
    },
    "tree": [{
        "id": "hero", "type": "hero", "variant": "centered",
        "frame": {"width": 720, "height": 360, "minHeight": 420},
        "props": {
            "heading": "A selected hero must stay selected while dragging",
            "subheading": "Its semantic text must not steal the geometry gesture.",
            "ctaPrimary": {"text": "Start"},
        },
    }],
}


def check(name, condition, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def drag(page, x1, y1, x2, y2):
    page.mouse.move(x1, y1)
    page.mouse.down()
    page.mouse.move(x2, y2, steps=10)
    page.mouse.up()
    page.wait_for_timeout(350)


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
            sys.exit("server not ready")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && window.DNAEditor")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("(a) => window.GraphDev.setIR(a.id, a.ir)", {"id": node_id, "ir": IR})
        page.click(".n-edit .f-open-editor")
        page.wait_for_selector('.dna-editor [data-ir-sec="0"]')
        page.click('.dna-editor [data-act="zoom-fit"]')
        page.wait_for_timeout(400)

        page.click('.dna-editor .fe-layer[data-key="0:"]')
        page.wait_for_selector('.dna-editor .geo-box.selected .geo-h.h-e')
        hero = page.locator('.dna-editor [data-ir-sec="0"]').bounding_box()
        heading = page.locator('.dna-editor [data-ir-sec="0"] [data-ir-path="props.heading"]').bounding_box()
        scale = page.evaluate("(() => { const e=document.querySelector('.dna-editor [data-ir-sec=\"0\"]'); return e.getBoundingClientRect().width/e.offsetWidth })()")

        # Start over semantic heading content: the existing section selection owns the gesture.
        drag(page, heading["x"] + heading["width"] / 2, heading["y"] + heading["height"] / 2,
             heading["x"] + heading["width"] / 2 + 48 * scale, heading["y"] + heading["height"] / 2 + 24 * scale)
        frame = page.evaluate("window.DNAEditor.getIR().tree[0].frame")
        root_frame = page.evaluate("window.DNAEditor.getIR().frame")
        selected = page.evaluate("document.querySelector('.dna-editor .geo-box.selected .geo-chip')?.textContent || ''")
        check("dragging selected hero commits section x/y", frame.get("x", 0) > 0 and frame.get("y", 0) > 0, str(frame))
        check("responsive root keeps free layout after section move", root_frame.get("layout") == "free", str(root_frame))
        check("semantic content does not steal selected section", selected.startswith("section"), selected)

        # Re-select the section so resize is independently verified (the move
        # assertion above deliberately records whether the body gesture stole it).
        page.click('.dna-editor .fe-layer[data-key="0:"]')
        page.wait_for_timeout(150)
        handle = page.locator('.dna-editor .geo-box.selected .geo-h.h-e').bounding_box()
        width_before = page.evaluate("window.DNAEditor.getIR().tree[0].frame.width")
        drag(page, handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2,
             handle["x"] + handle["width"] / 2 - 80 * scale, handle["y"] + handle["height"] / 2)
        width_after = page.evaluate("window.DNAEditor.getIR().tree[0].frame.width")
        check("visible east handle shrinks selected hero", width_after < width_before - 60, f"{width_before} -> {width_after}")

        # Generated heroes commonly carry minHeight. A direct south-handle
        # drag must visibly override that older generation constraint.
        page.click('.dna-editor .fe-layer[data-key="0:"]')
        page.wait_for_timeout(150)
        handle = page.locator('.dna-editor .geo-box.selected .geo-h.h-s').bounding_box()
        height_before = page.locator('.dna-editor [data-ir-sec="0"]').bounding_box()["height"] / scale
        drag(page, handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2,
             handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2 - 100 * scale)
        height_frame = page.evaluate("window.DNAEditor.getIR().tree[0].frame")
        height_after = page.locator('.dna-editor [data-ir-sec="0"]').bounding_box()["height"] / scale
        check("south handle shrinks hero below generated minHeight",
              height_after < height_before - 70 and height_frame.get("height", height_before) < height_before - 70,
              f"dom {height_before:.0f} -> {height_after:.0f}; frame={height_frame}")
        check("conflicting minHeight no longer blocks direct resize",
              height_frame.get("minHeight", 0) <= height_frame.get("height", 0), str(height_frame))

        # The ownership guard is drag-only: a click without movement still
        # drills into semantic content as before.
        page.click('.dna-editor .fe-layer[data-key="0:"]')
        heading = page.locator('.dna-editor [data-ir-sec="0"] [data-ir-path="props.heading"]').bounding_box()
        page.mouse.click(heading["x"] + heading["width"] / 2, heading["y"] + heading["height"] / 2)
        clicked = page.evaluate("document.querySelector('.dna-editor .geo-box.selected .geo-chip')?.textContent || ''")
        check("click without drag still selects semantic child", clicked.startswith("heading"), clicked)
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS))
        sys.exit(1)
    print("ALL SECTION GEOMETRY CHECKS PASSED")


if __name__ == "__main__":
    main()
