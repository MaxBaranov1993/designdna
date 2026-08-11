"""Регрессия бага «при перетаскивании всё ломается»: child с width:fill после
конверсии родителя в free не должен растягиваться на весь padding-box —
размер фиксируется измеренным на момент конверсии.
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_fill_drag_test.py
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
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
        pg.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'))
        pg.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'))
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
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, IR)
        pg.wait_for_timeout(700)

        # Новый UI: renderer.js асинхронно подгружает Google-шрифты IR и делает
        # reflow превью (в legacy соединение грел page-шрифт nodes.html). Ждём
        # стабилизации до открытия редактора: в него IR уходит с догруженными шрифтами.
        def wait_ir_ready(sel, polls=3, interval=150):
            hits = 0
            for _ in range(80):
                st = pg.evaluate("document.fonts ? document.fonts.status : 'loaded'")
                hits = hits + 1 if st == "loaded" else 0
                if hits >= polls:
                    break
                pg.wait_for_timeout(interval)
            last, geo_hits = None, 0
            for _ in range(50):
                r = pg.evaluate(
                    "(s) => { const el = document.querySelector(s); if (!el) return null;"
                    " const b = el.getBoundingClientRect();"
                    " return [b.left, b.top, b.width, b.height]; }", sel)
                if r is not None and r == last:
                    geo_hits += 1
                    if geo_hits >= polls:
                        return True
                else:
                    geo_hits = 0
                last = r
                pg.wait_for_timeout(interval)
            return False

        wait_ir_ready('.n-edit .edit-inner [class^="ir-"]')

        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(500)

        fill_card = pg.query_selector('.fe-canvas [data-ir-path="children.0.children.1"]')
        fb = fill_card.bounding_box()
        w_before = fb["width"]
        check("fill-ребёнок растянут по родителю до drag", w_before > 300, str(fb))

        pg.mouse.move(fb["x"] + fb["width"] / 2, fb["y"] + fb["height"] / 2)
        # Component-first selection: Ctrl-drag drills into the nested fill child.
        pg.keyboard.down("Control")
        pg.mouse.down()
        pg.mouse.move(fb["x"] + fb["width"] / 2 + 30, fb["y"] + fb["height"] / 2 + 20, steps=8)
        pg.mouse.up()
        pg.keyboard.up("Control")
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
