"""P1: numeric math («100*2») и drag-scrub лейблов в инспекторе.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_p1_insp_test.py
"""
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "docs" / "frame-example.json"
FAILS = []

FRAME = ("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id))"
         ".data.ir.tree[0].children[0].frame")


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def set_field(pg, pi, value):
    pg.fill(f'.fe-inspector input[data-pi="{pi}"]', value)
    pg.evaluate(f'document.querySelector(".fe-inspector input[data-pi=\\"{pi}\\"]")'
                ".dispatchEvent(new Event('change'))")
    pg.wait_for_timeout(300)


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
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        cb = card.bounding_box()
        # клик в padding-зону (нижний правый угол) — выделится сама карточка, не ребёнок
        pg.mouse.click(cb["x"] + cb["width"] - 4, cb["y"] + cb["height"] - 4)
        pg.wait_for_timeout(400)

        # ---------- numeric math ----------
        set_field(pg, "width", "100*2+40")
        w = pg.evaluate(FRAME + ".width")
        shown = pg.input_value('.fe-inspector input[data-pi="width"]')
        check("math: 100*2+40 → width 240", w == 240, str(w))
        check("math: поле схлопнулось в число", shown == "240", shown)

        set_field(pg, "gap", "16/2")
        g = pg.evaluate(FRAME + ".gap")
        check("math: 16/2 → gap 8", g == 8, str(g))

        set_field(pg, "width", "abc")
        w2 = pg.evaluate(FRAME + ".width")
        check("мусор не применяется", w2 == 240, str(w2))

        # ---------- drag-scrub лейбла X ----------
        x0 = pg.evaluate(FRAME + ".x")
        if not isinstance(x0, (int, float)):
            x0 = float(pg.input_value('.fe-inspector input[data-pi="x"]') or 0)
        lab = pg.query_selector('.fe-inspector .pi-field:has(input[data-pi="x"]) label')
        lb = lab.bounding_box()
        pg.mouse.move(lb["x"] + lb["width"] / 2, lb["y"] + lb["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(lb["x"] + lb["width"] / 2 + 30, lb["y"] + lb["height"] / 2, steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(300)
        x1 = pg.evaluate(FRAME + ".x")
        check("scrub: X сдвинулся на +30", isinstance(x1, (int, float)) and abs(x1 - (x0 + 30)) <= 2,
              f"x0={x0} x1={x1}")

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL INSPECTOR CHECKS PASSED")


if __name__ == "__main__":
    main()
