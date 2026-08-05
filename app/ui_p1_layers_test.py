"""P1: Lock/Hide + search в layers panel DNA-редактора.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_p1_layers_test.py
"""
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "frame-example.json"
FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1000})
        for _ in range(30):
            try:
                pg.goto(BASE + "/nodes", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector("#viewport")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id")
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(600)
        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(500)

        # ---------- search ----------
        total = pg.evaluate("document.querySelectorAll('.fe-layer').length")
        pg.fill(".fe-search", "card")
        pg.wait_for_timeout(200)
        rows = pg.evaluate(
            "Array.from(document.querySelectorAll('.fe-layer .fe-ln')).map(e => e.textContent)")
        check("search: только строки с 'card'", rows and all("card" in r.lower() for r in rows), str(rows))
        pg.fill(".fe-search", "")
        pg.wait_for_timeout(200)
        check("search: сброс возвращает все слои",
              pg.evaluate("document.querySelectorAll('.fe-layer').length") == total)

        # ---------- hide ----------
        key = "0:children.0"
        pg.click(f'.fe-layer[data-key="{key}"] [data-flag="hidden"]', force=True)
        pg.wait_for_timeout(300)
        disp = pg.evaluate(
            "document.querySelector('.fe-canvas [data-ir-path=\"children.0\"]').style.display")
        check("hide: элемент скрыт с канваса", disp == "none", disp)
        pg.click(f'.fe-layer[data-key="{key}"] [data-flag="hidden"]', force=True)
        pg.wait_for_timeout(300)
        disp = pg.evaluate(
            "document.querySelector('.fe-canvas [data-ir-path=\"children.0\"]').style.display")
        check("hide: повторный клик показывает", disp == "", disp)

        # ---------- lock ----------
        pg.click(f'.fe-layer[data-key="{key}"] [data-flag="locked"]', force=True)
        pg.wait_for_timeout(300)
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        cb = card.bounding_box()
        pg.mouse.click(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
        pg.wait_for_timeout(300)
        # залоченный card прозрачен для hit-test; клик может выделить лишь незалоченного предка
        chips = pg.evaluate(
            "Array.from(document.querySelectorAll('.fe-canvas .geo-box.selected .geo-chip'))"
            ".map(c => c.textContent)")
        check("lock: залоченный card не выделяется", not any(c.startswith("card") for c in chips),
              str(chips))
        pg.click(f'.fe-layer[data-key="{key}"] [data-flag="locked"]', force=True)
        pg.wait_for_timeout(300)
        pg.mouse.click(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
        pg.wait_for_timeout(300)
        n_sel = pg.evaluate("document.querySelectorAll('.fe-canvas .geo-box.selected').length")
        check("unlock: выделение снова работает", n_sel == 1, str(n_sel))

        # ---------- IR не загрязнен флагами ----------
        dirty = pg.evaluate(
            "(() => { const ir = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir; return /\"(hidden|locked)\"\\s*:/.test(JSON.stringify(ir)); })()")
        check("IR чистый: флаги не попадают в IR", dirty is False)

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL LAYERS CHECKS PASSED")


if __name__ == "__main__":
    main()
