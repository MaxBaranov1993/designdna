"""P2: constraints при resize родителя, Z-order (] / [), Group/Ungroup, reorder в layers.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_p2_test.py
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
    "meta": {"name": "p2", "description": "тест", "styleTags": ["test"]},
    "frame": {"width": 700, "height": 500},
    "tokens": TOKENS,
    "tree": [
        {"id": "free-sec", "type": "feature-grid",
         "frame": {"width": 600, "height": 260, "layout": "free", "padding": 0},
         "children": [
             {"type": "card", "frame": {"x": 20, "y": 40, "width": 150, "height": 100}},
             {"type": "card", "frame": {"x": 430, "y": 40, "width": 150, "height": 100,
                                        "constraints": {"h": "right"}}},
             {"type": "card", "frame": {"x": 220, "y": 40, "width": 150, "height": 100,
                                        "constraints": {"h": "center"}}},
         ]},
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

        # ---------- constraints: resize секции +100 по ширине ----------
        sec = pg.query_selector('.fe-canvas [data-ir-sec="0"]')
        sb = sec.bounding_box()
        pg.mouse.click(sb["x"] + 10, sb["y"] + sb["height"] - 8)  # пустая зона секции
        pg.wait_for_timeout(300)
        # east-хендл: правый край рамки выделения
        box = pg.query_selector('.fe-canvas .geo-box.selected')
        bb = box.bounding_box()
        hx, hy = bb["x"] + bb["width"], bb["y"] + bb["height"] / 2
        pg.mouse.move(hx, hy)
        pg.mouse.down()
        pg.mouse.move(hx + 100, hy, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        fr = pg.evaluate(NODE_IR + ".tree[0].children.map(c => c.frame)")
        check("constraints: right-ребёнок сдвинулся на +100", fr[1]["x"] == 530, str(fr[1]))
        check("constraints: center-ребёнок на +50", fr[2]["x"] == 270, str(fr[2]))
        check("constraints: left-ребёнок на месте", fr[0]["x"] == 20, str(fr[0]))

        # ---------- Z-order: ] поднимает ----------
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        c0 = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        cb = c0.bounding_box()
        pg.mouse.click(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
        pg.wait_for_timeout(300)
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("]")
        pg.wait_for_timeout(400)
        widths = pg.evaluate(NODE_IR + ".tree[0].children.map(c => c.frame.x)")
        check("z-order: ] поднял первую карточку выше второй",
              widths == [530, 20, 270], str(widths))
        pg.keyboard.press("[")
        pg.wait_for_timeout(400)
        widths = pg.evaluate(NODE_IR + ".tree[0].children.map(c => c.frame.x)")
        check("z-order: [ вернул обратно", widths == [20, 530, 270], str(widths))

        # ---------- Group / Ungroup ----------
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        c0 = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        b0 = c0.bounding_box()
        c1 = pg.query_selector('.fe-canvas [data-ir-path="children.1"]')
        b1 = c1.bounding_box()
        pg.mouse.click(b0["x"] + b0["width"] / 2, b0["y"] + b0["height"] / 2)
        pg.wait_for_timeout(200)
        pg.keyboard.down("Shift")
        pg.mouse.click(b1["x"] + b1["width"] / 2, b1["y"] + b1["height"] / 2)
        pg.keyboard.up("Shift")
        pg.wait_for_timeout(300)
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+g")
        pg.wait_for_timeout(400)
        kids = pg.evaluate(NODE_IR + ".tree[0].children")
        check("group: два сиблинга стали группой (2 children, у группы 2 внутри)",
              len(kids) == 2 and len(kids[0].get("children", [])) == 2, str(len(kids)))
        check("group: у группы free-frame с габаритами",
              kids[0]["frame"].get("layout") == "free" and kids[0]["frame"].get("width") >= 300,
              str(kids[0].get("frame")))
        pg.keyboard.press("Control+Shift+g")
        pg.wait_for_timeout(400)
        kids = pg.evaluate(NODE_IR + ".tree[0].children")
        check("ungroup: вернулись 3 сиблинга", len(kids) == 3, str(len(kids)))

        # ---------- reorder в layers (HTML5 dnd) ----------
        order0 = pg.evaluate(NODE_IR + ".tree[0].children.map(c => c.frame.x)")
        try:
            pg.drag_and_drop('.fe-layer[data-key="0:children.0"]', '.fe-layer[data-key="0:children.2"]')
            pg.wait_for_timeout(400)
        except Exception as e:
            print("dnd exception:", e)
        order1 = pg.evaluate(NODE_IR + ".tree[0].children.map(c => c.frame.x)")
        check("layers dnd: порядок изменился", order0 != order1, f"{order0} -> {order1}")

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL P2 CHECKS PASSED")


if __name__ == "__main__":
    main()
