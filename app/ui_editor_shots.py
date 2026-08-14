"""Скриншоты fullscreen DNA-редактора для визуальной проверки UI.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_shots.py
Вывод: results/ui_editor_react_*.png
"""
import json
import pathlib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
ROOT = pathlib.Path(__file__).resolve().parent.parent
IR_PATH = ROOT / "app" / "fixtures" / "frame-example.json"
OUT = ROOT / "results"


def wait_stable(pg, sel, polls=3, interval=150):
    for _ in range(80):
        if pg.evaluate("document.fonts ? document.fonts.status : 'loaded'") == "loaded":
            break
        pg.wait_for_timeout(interval)
    last, hits = None, 0
    for _ in range(50):
        r = pg.evaluate(
            "(s) => { const el = document.querySelector(s); if (!el) return null;"
            " const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }", sel)
        if r is not None and r == last:
            hits += 1
            if hits >= polls:
                return
        else:
            hits = 0
        last = r
        pg.wait_for_timeout(interval)


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1000})
        for _ in range(30):
            try:
                pg.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)
        wait_stable(pg, '.n-edit .edit-inner [class^="ir-"]')
        pg.screenshot(path=str(OUT / "ui_editor_react_node.png"))

        pg.click(".n-edit .f-open-editor")
        pg.wait_for_selector('.dna-editor[style*="flex"]')
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT / "ui_editor_react_full.png"))

        # выделение карточки → инспектор + рамка выделения
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        if card:
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + 8, cb["y"] + 8)
            pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT / "ui_editor_react_selected.png"))

        # rail крупным планом
        rail = pg.query_selector(".dna-editor .fe-rail")
        if rail:
            rail.screenshot(path=str(OUT / "ui_editor_react_rail.png"))

        # слои
        layers = pg.query_selector(".dna-editor .fe-layers")
        if layers:
            layers.screenshot(path=str(OUT / "ui_editor_react_layers.png"))

        # инспектор
        insp = pg.query_selector(".dna-editor .fe-inspector")
        if insp:
            insp.screenshot(path=str(OUT / "ui_editor_react_inspector.png"))

        # новые инструменты: эллипс хоткеем O и drag на канвасе
        pg.keyboard.press("o")
        pg.wait_for_timeout(200)
        board = pg.query_selector(".fe-canvas-inner")
        bb = board.bounding_box()
        x0, y0 = bb["x"] + bb["width"] * 0.55, bb["y"] + bb["height"] * 0.35
        pg.mouse.move(x0, y0)
        pg.mouse.down()
        pg.mouse.move(x0 + 140, y0 + 100, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT / "ui_editor_react_ellipse.png"))

        # Style DNA панель
        dna_btn = pg.query_selector('.dna-editor [data-act="style-dna"]')
        if dna_btn:
            dna_btn.click()
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(OUT / "ui_editor_react_dna.png"))

        pg.click('.dna-editor [data-act="close"]')
        if pg.query_selector('[data-act="discard-close"]'):
            pg.click('[data-act="discard-close"]')
        pg.wait_for_timeout(400)
        browser.close()
    print("shots saved to results/ui_editor_react_*.png")


if __name__ == "__main__":
    main()
