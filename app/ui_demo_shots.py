"""Скриншоты ключевых сценариев для сводного демо спринта.
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_demo_shots.py
"""
import json
import pathlib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "app" / "fixtures" / "frame-example.json"
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
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
        pg.wait_for_timeout(700)

        # DNA-редактор: слои + канвас + выделение карточки + инспектор
        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(500)
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        cb = card.bounding_box()
        pg.mouse.click(cb["x"] + 8, cb["y"] + 8)
        pg.wait_for_timeout(400)
        SHOT_DIR.mkdir(exist_ok=True)
        pg.screenshot(path=str(SHOT_DIR / "ui_demo_editor.png"), full_page=False)

        # drag карточки в DNA-редакторе: guides + distance labels (центр, не хендлы)
        pg.mouse.move(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(cb["x"] + cb["width"] / 2 + 90, cb["y"] + cb["height"] / 2 + 40, steps=8)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(SHOT_DIR / "ui_demo_drag_guides.png"), full_page=False)
        pg.mouse.up()
        browser.close()
    print("DEMO SHOTS SAVED")


if __name__ == "__main__":
    main()
