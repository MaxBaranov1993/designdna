"""Техдолг renderer/geoedit: контракт frame.x/y — padding-box.
Проверяет:
  1) контейнер с layout:auto во free-родителе рендерится position:absolute
     в своих x/y (раньше position:relative перезаписывал absolute);
  2) free-секция без frame.padding сохраняет дефолтный padding (.sec-free),
     конверсия в free не пишет padding в IR и не сдвигает сиблингов;
  3) «Absolute Position» в инспекторе не сдвигает элемент (posOf = padding-box);
  4) одиночное выравнивание работает в тех же координатах (align-right к
     padding-box границе родителя).
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_renderer_frame_test.py
"""
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"

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
    "meta": {"name": "Техдолг: frame-контракт", "description": "тестовая фикстура",
             "styleTags": ["test"]},
    "frame": {"width": 960, "height": 980},
    "tokens": TOKENS,
    "tree": [
        {   # секция 0: auto-раскладка БЕЗ padding в frame — для конверсии в free
            "id": "auto-sec", "type": "feature-grid",
            "frame": {"width": "fill"},
            "children": [
                {"type": "card", "frame": {"width": 200, "height": 100}},
                {"type": "card", "frame": {"width": 200, "height": 100}},
            ],
        },
        {   # секция 1: free + контейнер-card (layout:auto, дети) в x/y
            "id": "free-sec", "type": "feature-grid",
            "frame": {"width": "fill", "height": 320, "layout": "free", "padding": 0},
            "children": [
                {"type": "card",
                 "frame": {"x": 150, "y": 60, "width": 260, "height": 140,
                           "layout": "auto", "direction": "column", "gap": 8, "padding": 16},
                 "children": [{"type": "text", "text": "Внутри карточки"}]},
            ],
        },
        {   # секция 2: free с padding 40 — для posOf/align
            "id": "pad-sec", "type": "feature-grid",
            "frame": {"width": "fill", "height": 260, "layout": "free", "padding": 40},
            "children": [
                {"type": "rect", "fill": "#8B5CF6", "radius": 8,
                 "frame": {"width": 120, "height": 60}},
            ],
        },
    ],
}


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1100})
        for _ in range(30):
            try:
                pg.goto(BASE + "/", timeout=2000)
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
        # reflow превью (в legacy соединение грел page-шрифт nodes.html). Пока
        # шрифты не догружены, геометрия плавает — замеры и drag расходятся.
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

        scale = pg.evaluate(
            "(() => { const el = document.querySelector('.n-edit [data-ir-sec=\"1\"]');"
            " return el.getBoundingClientRect().width / el.offsetWidth; })()")
        NODE_IR = ("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data.ir")

        # ---------- 1) контейнер с layout:auto во free-родителе — absolute в x/y ----------
        st = pg.evaluate("""(() => {
            const sec = document.querySelector('.n-edit [data-ir-sec="1"]');
            const card = document.querySelector('.n-edit [data-ir-sec="1"] [data-ir-path="children.0"]');
            const sb = sec.getBoundingClientRect(), cb = card.getBoundingClientRect();
            const s = sb.width / sec.offsetWidth;
            return { pos: getComputedStyle(card).position,
                     dx: (cb.left - sb.left) / s, dy: (cb.top - sb.top) / s };
        })()""")
        check("card-контейнер во free-секции: position=absolute", st["pos"] == "absolute", str(st))
        check("card-контейнер стоит в своих x/y (150,60)",
              abs(st["dx"] - 150) <= 2 and abs(st["dy"] - 60) <= 2, str(st))

        # ---------- 2) конверсия auto-секции в free: padding сохраняется, IR чистый ----------
        c1 = pg.query_selector('.n-edit [data-ir-sec="0"] [data-ir-path="children.0"]').bounding_box()
        c2 = pg.query_selector('.n-edit [data-ir-sec="0"] [data-ir-path="children.1"]').bounding_box()
        pg.mouse.click(c2["x"] + c2["width"] / 2, c2["y"] + c2["height"] / 2)
        pg.wait_for_timeout(250)
        pg.mouse.move(c2["x"] + c2["width"] / 2, c2["y"] + c2["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(c2["x"] + c2["width"] / 2 + 24, c2["y"] + c2["height"] / 2, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        fr0 = pg.evaluate(NODE_IR + ".tree[0].frame")
        check("конверсия: секция стала free", fr0.get("layout") == "free", str(fr0))
        check("конверсия: padding НЕ записан в IR (дело рендерера)",
              "padding" not in fr0, str(fr0))
        pad = pg.evaluate("""(() => {
            const sec = document.querySelector('.n-edit [data-ir-sec="0"]');
            const cs = getComputedStyle(sec);
            return { top: parseFloat(cs.paddingTop), left: parseFloat(cs.paddingLeft) };
        })()""")
        check("конверсия: дефолтный padding секции сохранён (64/32)",
              abs(pad["top"] - 64) < 1 and abs(pad["left"] - 32) < 1, str(pad))
        c1b = pg.query_selector('.n-edit [data-ir-sec="0"] [data-ir-path="children.0"]').bounding_box()
        check("конверсия: сиблинг не сдвинулся",
              abs(c1b["x"] - c1["x"]) <= 3 and abs(c1b["y"] - c1["y"]) <= 3,
              f"до=({c1['x']:.0f},{c1['y']:.0f}) после=({c1b['x']:.0f},{c1b['y']:.0f})")

        # ---------- 3) Absolute Position не сдвигает элемент (posOf = padding-box) ----------
        rect = pg.query_selector('.n-edit [data-ir-sec="2"] [data-ir-path="children.0"]')
        rb = rect.bounding_box()
        pg.mouse.click(rb["x"] + rb["width"] / 2, rb["y"] + rb["height"] / 2)
        pg.wait_for_timeout(300)
        pg.click('.n-edit .edit-inspector [data-pi="absolute"]', force=True)
        pg.wait_for_timeout(350)
        rb2 = pg.query_selector('.n-edit [data-ir-sec="2"] [data-ir-path="children.0"]').bounding_box()
        fr2 = pg.evaluate(NODE_IR + ".tree[2].children[0].frame")
        check("absolute: frame.x/y записаны числами",
              isinstance(fr2.get("x"), (int, float)) and isinstance(fr2.get("y"), (int, float)),
              str(fr2))
        check("absolute: элемент не сдвинулся (контракт padding-box)",
              abs(rb2["x"] - rb["x"]) <= 2 and abs(rb2["y"] - rb["y"]) <= 2,
              f"до=({rb['x']:.1f},{rb['y']:.1f}) после=({rb2['x']:.1f},{rb2['y']:.1f})")
        check("absolute: x/y равны отступу padding (40)",
              fr2.get("x") == 40 and fr2.get("y") == 40, str(fr2))

        # ---------- 4) одиночное выравнивание в координатах padding-box ----------
        pg.click('.n-edit .edit-inspector [data-act="align-right"]')
        pg.wait_for_timeout(350)
        ar = pg.evaluate("""(() => {
            const sec = document.querySelector('.n-edit [data-ir-sec="2"]');
            const el = document.querySelector('.n-edit [data-ir-sec="2"] [data-ir-path="children.0"]');
            const sb = sec.getBoundingClientRect(), eb = el.getBoundingClientRect();
            const s = sb.width / sec.offsetWidth;
            return { fx: window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id))
                        .data.ir.tree[2].children[0].frame.x,
                     right: (eb.right - sb.left) / s, secW: sb.width / s };
        })()""")
        check("align-right: frame.x записан", isinstance(ar["fx"], (int, float)), str(ar))
        check("align-right: правый край у границы padding-box родителя",
              abs(ar["right"] - ar["secW"]) <= 2, str(ar))

        SHOT_DIR.mkdir(exist_ok=True)
        pg.screenshot(path=str(SHOT_DIR / "ui_renderer_frame.png"), full_page=False)
        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL RENDERER-FRAME CHECKS PASSED")


if __name__ == "__main__":
    main()
