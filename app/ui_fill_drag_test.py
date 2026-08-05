"""Регрессия бага «при перетаскивании всё ломается»: child с width:fill после
конверсии родителя в free не должен растягиваться на весь padding-box —
размер фиксируется измеренным на момент конверсии.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_fill_drag_test.py
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
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
    "meta": {"name": "fill-drag", "description": "тест", "styleTags": ["test"]},
    "frame": {"width": 600, "height": 500},
    "tokens": TOKENS,
    "tree": [
        {   # card-контейнер (column) с fill-ребёнком — как в реальных IR
            "id": "col-sec", "type": "feature-grid",
            "frame": {"width": "fill", "padding": 20},
            "children": [
                {"type": "card",
                 "frame": {"width": 400, "layout": "auto", "direction": "column",
                           "gap": 12, "padding": 20},
                 "children": [
                     {"type": "card", "frame": {"width": 200, "height": 80}},
                     {"type": "card", "frame": {"width": "fill", "height": 90}},
                 ]},
            ],
        },
    ],
}

NODE_IR = ("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir")


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
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
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, IR)
        pg.wait_for_timeout(700)
        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(500)

        fill_card = pg.query_selector('.fe-canvas [data-ir-path="children.0.children.1"]')
        fb = fill_card.bounding_box()
        w_before = fb["width"]
        check("fill-ребёнок растянут по родителю до drag", w_before > 300, str(fb))

        pg.mouse.move(fb["x"] + fb["width"] / 2, fb["y"] + fb["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(fb["x"] + fb["width"] / 2 + 30, fb["y"] + fb["height"] / 2 + 20, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(500)

        ab = pg.query_selector('.fe-canvas [data-ir-path="children.0.children.1"]').bounding_box()
        fr = pg.evaluate(NODE_IR + ".tree[0].children[0].children[1].frame")
        check("после drag: ширина сохранена (не растянуло на padding-box)",
              abs(ab["width"] - w_before) <= 3, f"before={w_before:.0f} after={ab['width']:.0f}")
        check("после drag: fill заменён измеренным размером",
              isinstance(fr.get("width"), (int, float)), str(fr))
        check("после drag: высота сохранена", abs(ab["height"] - fb["height"]) <= 3,
              f"before={fb['height']:.0f} after={ab['height']:.0f}")

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL FILL-DRAG CHECKS PASSED")


if __name__ == "__main__":
    main()
