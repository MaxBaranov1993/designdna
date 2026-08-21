"""Focused Page -> Edit acceptance: auto-sized artboard and editable source layers."""
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"


def source_ir(label: str, desktop_height: int, mobile_height: int):
    root = f"{label.lower()}:root"
    return {
        "version": "1.1",
        "frame": {"width": 1440, "height": desktop_height},
        "tokens": {},
        "tree": [{
            "id": "imported-block",
            "type": "source-block",
            "variant": "dom-capture",
            "sourceKey": root,
            "frame": {"width": 1440, "height": desktop_height, "layout": "free"},
            "responsive": {"mobile": {"frame": {"width": 390, "height": mobile_height}}},
            "children": [
                {
                    "type": "text", "text": f"{label} text", "sourceKey": f"{root}/text:0",
                    "frame": {"x": 24, "y": 20, "width": 260, "height": 32, "absolute": True},
                },
                {
                    "type": "button", "text": f"{label} button", "sourceKey": f"{root}/button:0",
                    "frame": {"x": 24, "y": 72, "width": 180, "height": 44, "absolute": True},
                },
            ],
        }],
    }


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))

        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("server not ready")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")

        ids = page.evaluate("""() => {
          const first = window.GraphDev.add('edit', 40, 40).id;
          const second = window.GraphDev.add('edit', 40, 430).id;
          const pageNode = window.GraphDev.add('page', 560, 120).id;
          const result = window.GraphDev.add('edit', 1040, 120).id;
          return { first, second, pageNode, result };
        }""")
        page.evaluate("([id, ir]) => window.GraphDev.setIR(id, ir)", [ids["first"], source_ir("Header", 140, 190)])
        page.evaluate("([id, ir]) => window.GraphDev.setIR(id, ir)", [ids["second"], source_ir("Main", 460, 710)])
        assert page.evaluate("([a, p]) => window.GraphDev.connect(a, 'ir', p, 'a')", [ids["first"], ids["pageNode"]])
        assert page.evaluate("([b, p]) => window.GraphDev.connect(b, 'ir', p, 'b')", [ids["second"], ids["pageNode"]])
        page.evaluate("id => window.GraphDev.run(id)", ids["pageNode"])
        page.wait_for_timeout(300)

        composed = page.evaluate("""id => {
          const ir = window.GraphDev.node(id).data.ir;
          const keys = [];
          const walk = n => { if (n.sourceKey) keys.push(n.sourceKey); (n.children || []).forEach(walk); };
          ir.tree.forEach(walk);
          return { frame: ir.frame, viewports: ir.responsive.viewports, sections: ir.tree.length, keys };
        }""", ids["pageNode"])
        assert composed["frame"]["height"] == "hug", composed
        assert composed["viewports"]["desktop"]["height"] == 600, composed
        assert composed["viewports"]["mobile"]["height"] == 900, composed
        assert composed["sections"] == 2 and len(composed["keys"]) == len(set(composed["keys"])) == 6, composed

        assert page.evaluate("([p, r]) => window.GraphDev.connect(p, 'ir', r, 'a')", [ids["pageNode"], ids["result"]])
        page.wait_for_timeout(300)
        page.click(f'.n-edit[data-id="{ids["result"]}"] .f-open-editor')
        page.wait_for_selector(".dna-editor", state="visible")
        page.wait_for_selector(".fe-canvas [class^='ir-']")
        page.wait_for_timeout(500)

        geometry = page.evaluate("""() => {
          const board = document.querySelector('.fe-canvas [class^="ir-"]');
          const sections = [...board.querySelectorAll(':scope > [data-ir-sec]')];
          const br = board.getBoundingClientRect();
          const last = sections.at(-1).getBoundingClientRect();
          return { height: board.offsetHeight, count: sections.length, bottomError: Math.abs(br.bottom - last.bottom) };
        }""")
        assert geometry["count"] == 2, geometry
        assert abs(geometry["height"] - 600) <= 1, geometry
        assert geometry["bottomError"] <= 1, geometry

        layer_keys = page.locator(".fe-layers-tree .fe-layer").evaluate_all(
            "els => els.map(el => el.dataset.key)")
        expected = {
            "null:", "0:", "1:",
            "0:a/header:root/text:0", "0:a/header:root/button:0",
            "1:b/main:root/text:0", "1:b/main:root/button:0",
        }
        assert expected.issubset(set(layer_keys)), layer_keys

        def draft_frame(source_key):
            return page.evaluate("""([id, key]) => {
              const ir = window.GraphDev.node(id).data._editorDraft.ir;
              let found = null;
              const walk = n => { if (n.sourceKey === key) found = n; (n.children || []).forEach(walk); };
              ir.tree.forEach(walk);
              return found && found.frame;
            }""", [ids["result"], source_key])

        first_key = "a/header:root/text:0"
        page.locator(f'.fe-layer[data-key="0:{first_key}"]').click()
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(250)
        assert draft_frame(first_key)["x"] == 25

        second_key = "b/main:root/button:0"
        page.locator(f'.fe-layer[data-key="1:{second_key}"]').click()
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(250)
        assert draft_frame(second_key)["y"] == 73

        page.locator('.fe-layer[data-key="null:"]').click()
        handle = page.locator(".geo-box.selected .geo-h.h-n")
        box = handle.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 - 60, steps=6)
        page.mouse.up()
        page.wait_for_timeout(300)
        resized = page.evaluate("""id => {
          const ir = window.GraphDev.node(id).data._editorDraft.ir;
          return { frame: ir.frame, desktop: ir.responsive.viewports.desktop };
        }""", ids["result"])
        assert isinstance(resized["frame"]["height"], (int, float)) and resized["frame"]["height"] > 600, resized
        assert resized["desktop"]["height"] == resized["frame"]["height"], resized

        print("PASS page auto-size, root resize, outliner sourceKey selection, independent child edits")
        browser.close()


if __name__ == "__main__":
    main()
