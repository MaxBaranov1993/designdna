"""Renderer/GeoEdit frame contract: free placement, exact drag detach and alignment."""
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"
FAILS = []

TOKENS = {
    "mode": "light",
    "color": {"primary": "#0E7A5F", "secondary": "#134E48", "accent": "#E85D26",
              "background": "#FFFFFF", "surface": "#F6F7F8", "text": "#17201D",
              "textMuted": "#5D6B66", "border": "#E2E7E5"},
    "font": {"display": {"family": "Manrope", "weight": 800},
             "body": {"family": "Inter", "weight": 400}, "scale": "default"},
    "radius": {"card": "lg", "button": "full", "input": "md"},
    "spacing": {"section": "md", "container": "default"},
    "shadow": "sm",
}

IR = {
    "version": "1.0",
    "meta": {"name": "frame contract", "description": "regression fixture", "styleTags": ["test"]},
    "frame": {"width": 1440, "height": 980},
    "tokens": TOKENS,
    "tree": [
        {
            "id": "auto-sec", "type": "feature-grid", "frame": {"width": "fill"},
            "children": [
                {"type": "card", "frame": {"width": 200, "height": 100}},
                {"type": "card", "frame": {"width": 200, "height": 100}},
            ],
        },
        {
            "id": "free-sec", "type": "feature-grid",
            "frame": {"width": "fill", "height": 320, "layout": "free", "padding": 0},
            "children": [{
                "type": "card",
                "frame": {"x": 150, "y": 60, "width": 260, "height": 140,
                          "layout": "auto", "direction": "column", "gap": 8, "padding": 16},
                "children": [{"type": "text", "text": "Inside card"}],
            }],
        },
        {
            "id": "pad-sec", "type": "feature-grid",
            "frame": {"width": "fill", "height": 260, "layout": "free", "padding": 40},
            "children": [{
                "type": "rect", "fill": "#8B5CF6", "radius": 8,
                "frame": {"width": 120, "height": 60},
            }],
        },
    ],
}


def check(name, condition, extra=""):
    print(f"[{'OK' if condition else 'FAIL'}] {name}" + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))
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
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("([id, ir]) => window.GraphDev.setIR(id, ir)", [node_id, IR])
        page.wait_for_timeout(700)
        page.click(".n-edit .f-open-editor")
        page.wait_for_selector('.dna-editor .fe-canvas-inner [class^="ir-"]')
        page.click('.dna-editor [data-act="zoom-fit"]')
        page.wait_for_timeout(500)

        state_ir = (f"(() => {{ const d = window.GraphDev.node({node_id}).data;"
                    " return d._editorDraft?.ir || d.ir; })()")
        rendered = page.evaluate("""() => {
            const section = document.querySelector('.dna-editor [data-ir-sec="1"]');
            const card = section.querySelector('[data-ir-path="children.0"]');
            const sb = section.getBoundingClientRect(), cb = card.getBoundingClientRect();
            const scale = sb.width / section.offsetWidth;
            return {position: getComputedStyle(card).position,
                    x: (cb.left - sb.left) / scale, y: (cb.top - sb.top) / scale};
        }""")
        check("free-layout child uses absolute positioning", rendered["position"] == "absolute", str(rendered))
        check("free-layout child preserves x/y", abs(rendered["x"] - 150) <= 2 and abs(rendered["y"] - 60) <= 2, str(rendered))

        first = page.query_selector('.dna-editor [data-ir-sec="0"] [data-ir-path="children.0"]').bounding_box()
        second = page.query_selector('.dna-editor [data-ir-sec="0"] [data-ir-path="children.1"]').bounding_box()
        pre = page.evaluate("""() => {
            const section = document.querySelector('.dna-editor [data-ir-sec="0"]');
            const child = section.querySelector('[data-ir-path="children.1"]');
            const sb = section.getBoundingClientRect(), cb = child.getBoundingClientRect();
            const scale = sb.width / section.offsetWidth;
            return {x: (cb.left - sb.left) / scale, y: (cb.top - sb.top) / scale};
        }""")
        section_scale = page.evaluate("""() => {
            const section = document.querySelector('.dna-editor [data-ir-sec="0"]');
            return section.getBoundingClientRect().width / section.offsetWidth;
        }""")
        x, y = second["x"] + second["width"] / 2, second["y"] + second["height"] / 2
        page.mouse.click(x, y)
        page.wait_for_timeout(200)
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 24 * section_scale, y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(400)

        parent_frame = page.evaluate(state_ir + ".tree[0].frame")
        moved_frame = page.evaluate(state_ir + ".tree[0].children[1].frame")
        first_after = page.query_selector('.dna-editor [data-ir-sec="0"] [data-ir-path="children.0"]').bounding_box()
        second_after = page.query_selector('.dna-editor [data-ir-sec="0"] [data-ir-path="children.1"]').bounding_box()
        check("auto-layout parent stays unchanged", parent_frame == {"width": "fill"}, str(parent_frame))
        check("dragged child detaches into absolute layout", moved_frame.get("absolute") is True, str(moved_frame))
        check(
            "detached child commits exact padding-box coordinates",
            abs(moved_frame.get("x", -999) - (pre["x"] + 24)) <= 2
            and abs(moved_frame.get("y", -999) - pre["y"]) <= 2,
            f"pre={pre} frame={moved_frame}",
        )
        check(
            "drag preview and committed position match",
            abs(second_after["x"] - (second["x"] + 24 * section_scale)) <= 3
            and abs(second_after["y"] - second["y"]) <= 3,
            f"before={second} after={second_after}",
        )
        check("sibling remains in place", abs(first_after["x"] - first["x"]) <= 3 and abs(first_after["y"] - first["y"]) <= 3)

        page.click('.dna-editor .fe-layer[data-key="2:children.0"]')
        page.wait_for_timeout(250)
        manual = page.query_selector(".manual-controls")
        if manual is not None and manual.get_attribute("open") is None:
            if not page.evaluate("!!document.querySelector('.manual-controls')?.open"):  # блок помнит состояние между перемонтированиями
                page.click(".manual-controls summary")
        page.click('.dna-editor .fe-inspector [data-act="align-right"]')
        page.wait_for_timeout(350)
        aligned = page.evaluate("""() => {
            const section = document.querySelector('.dna-editor [data-ir-sec="2"]');
            const child = section.querySelector('[data-ir-path="children.0"]');
            const sb = section.getBoundingClientRect(), cb = child.getBoundingClientRect();
            const scale = sb.width / section.offsetWidth;
            return {right: (cb.right - sb.left) / scale, width: sb.width / scale};
        }""")
        aligned_frame = page.evaluate(state_ir + ".tree[2].children[0].frame")
        check("align-right commits frame.x", isinstance(aligned_frame.get("x"), (int, float)), str(aligned_frame))
        check("align-right uses the parent padding-box", abs(aligned["right"] - aligned["width"]) <= 2, str(aligned))

        SHOT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOT_DIR / "ui_renderer_frame.png"), full_page=False)
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS))
        for failure in FAILS:
            print(" -", failure)
        raise SystemExit(1)
    print("ALL RENDERER-FRAME CHECKS PASSED")


if __name__ == "__main__":
    main()
