"""Скриншот ноды «Редактор» со свежим IR и выделением (для визуальной проверки).
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow."""
import json
import pathlib

from playwright.sync_api import sync_playwright
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "app" / "fixtures" / "frame-example.json"
OUT = pathlib.Path(__file__).resolve().parent.parent / "results" / "ui_edit_node_clean.png"


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1700, "height": 1000})
        pg.goto(BASE + "/flow")
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(700)
        el = pg.query_selector('.n-edit [data-ir-path="children.0"]')
        bb = el.bounding_box()
        pg.mouse.click(bb["x"] + bb["width"] - 4, bb["y"] + bb["height"] - 4)
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT))
        # DNA-редактор: рельса как в pen.dev + нарисуем rect на канвасе
        pg.click('.n-edit .f-open-editor')
        pg.wait_for_timeout(600)
        pg.click('.dna-editor .fe-rail [data-tool="rect"]')
        pg.wait_for_timeout(200)
        sec = pg.query_selector('.fe-canvas [data-ir-sec="0"]').bounding_box()
        pg.mouse.move(sec["x"] + sec["width"] - 260, sec["y"] + 40)
        pg.mouse.down()
        pg.mouse.move(sec["x"] + sec["width"] - 120, sec["y"] + 140, steps=5)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT.with_name("ui_dna_editor_rail.png")))
        b.close()
    print("shot ok:", OUT)


if __name__ == "__main__":
    main()
