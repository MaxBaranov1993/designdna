"""Скриншоты нодового графа /flow для визуальной проверки shadcn-reskin'а.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_flow_shots.py
Вывод: results/ui_flow_shadcn_*.png
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
        pg.wait_for_selector(".svelte-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")

        gid = int(pg.evaluate("window.GraphDev.add('generator', 80, 60).id"))
        eid = int(pg.evaluate("window.GraphDev.add('edit', 620, 80).id"))
        pg.evaluate("window.GraphDev.add('styledna', 80, 460)")
        pg.evaluate("window.GraphDev.add('prompt', 80, 620)")
        pg.evaluate(f"window.GraphDev.connect({gid}, 'clones', {eid}, 'ir')")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % eid, ir)
        pg.wait_for_timeout(700)
        # ждём шрифты/геометрию превью
        for _ in range(60):
            if pg.evaluate("document.fonts ? document.fonts.status : 'loaded'") == "loaded":
                break
            pg.wait_for_timeout(150)
        pg.wait_for_timeout(400)

        pg.screenshot(path=str(OUT / "ui_flow_shadcn_graph.png"))

        node = pg.query_selector(f'.fnode[data-id="{eid}"]')
        if node:
            node.screenshot(path=str(OUT / "ui_flow_shadcn_node.png"))

        # выделенная нода + hover-состояния
        pg.click(f'.fnode[data-id="{eid}"]')
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(OUT / "ui_flow_shadcn_selected.png"))
        browser.close()
    print("shots saved to results/ui_flow_shadcn_*.png")


if __name__ == "__main__":
    main()
