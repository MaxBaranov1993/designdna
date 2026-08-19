"""P1: Shift-constrain (одна ось) + Alt+drag duplicate (free и auto-родители).
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_p1_drag_test.py
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
    "meta": {"name": "P1 drag", "description": "тест", "styleTags": ["test"]},
    "frame": {"width": 960, "height": 700},
    "tokens": TOKENS,
    "tree": [
        {   # free-секция: три карточки
            "id": "free-sec", "type": "feature-grid",
            "frame": {"width": "fill", "height": 240, "layout": "free", "padding": 0},
            "children": [
                {"type": "card", "frame": {"x": 20, "y": 40, "width": 200, "height": 120}},
                {"type": "card", "frame": {"x": 260, "y": 40, "width": 200, "height": 120}},
                {"type": "card", "frame": {"x": 500, "y": 40, "width": 200, "height": 120}},
            ],
        },
        {   # auto-секция: карточки в потоке
            "id": "auto-sec", "type": "feature-grid",
            "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 20, "padding": 20},
            "children": [
                {"type": "card", "frame": {"width": 150, "height": 80}},
                {"type": "card", "frame": {"width": 150, "height": 80}},
            ],
        },
    ],
}

NODE_IR = ("(() => { const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data;"
           " return d._editorDraft?.ir || d.ir; })()")


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

        wait_ir_ready('.n-edit .ir-preview-inner [class^="ir-"]')

        # GeoEdit живёт только в полноэкранном DNA-редакторе (thin Edit-нода — read-only
        # превью) — открываем редактор и работаем в нём
        pg.click('.n-edit .f-open-editor')
        pg.wait_for_selector('.dna-editor .fe-canvas-inner [class^="ir-"]')
        pg.click('.dna-editor [data-act="zoom-fit"]')
        wait_ir_ready('.dna-editor .fe-canvas-inner [class^="ir-"]')

        scale = pg.evaluate(
            "(() => { const el = document.querySelector('.dna-editor [data-ir-sec=\"0\"]');"
            " return el.getBoundingClientRect().width / el.offsetWidth; })()")

        def bb(sel):
            return pg.query_selector(sel).bounding_box()

        # ---------- 1) Shift-constrain: диагональ → только доминантная ось ----------
        c3 = bb('.dna-editor [data-ir-sec="0"] [data-ir-path="children.2"]')
        pg.mouse.click(c3["x"] + c3["width"] / 2, c3["y"] + c3["height"] / 2)
        pg.wait_for_timeout(250)
        pg.mouse.move(c3["x"] + c3["width"] / 2, c3["y"] + c3["height"] / 2)
        pg.mouse.down()
        pg.keyboard.down("Shift")
        pg.mouse.move(c3["x"] + c3["width"] / 2 + 60 * scale, c3["y"] + c3["height"] / 2 + 40 * scale, steps=10)
        pg.wait_for_timeout(200)
        pg.mouse.up()
        pg.keyboard.up("Shift")
        pg.wait_for_timeout(400)
        f3 = pg.evaluate(NODE_IR + ".tree[0].children[2].frame")
        check("Shift-constrain: Y не изменился", f3.get("y") == 40, str(f3))
        check("Shift-constrain: X сдвинулся", isinstance(f3.get("x"), (int, float)) and f3["x"] > 500, str(f3))

        # ---------- 2) Alt+drag в free: оригинал на месте, копия со сдвигом ----------
        c1 = bb('.dna-editor [data-ir-sec="0"] [data-ir-path="children.0"]')
        pg.mouse.click(c1["x"] + c1["width"] / 2, c1["y"] + c1["height"] / 2)
        pg.wait_for_timeout(250)
        pg.keyboard.down("Alt")
        pg.mouse.move(c1["x"] + c1["width"] / 2, c1["y"] + c1["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(c1["x"] + c1["width"] / 2 + 80 * scale, c1["y"] + c1["height"] / 2 + 30 * scale, steps=10)
        pg.mouse.up()
        pg.keyboard.up("Alt")
        pg.wait_for_timeout(400)
        kids = pg.evaluate(NODE_IR + ".tree[0].children")
        check("Alt+drag: появился дубликат (4 children)", len(kids) == 4, str(len(kids)))
        check("Alt+drag: оригинал не сдвинулся (x=20)", kids[0]["frame"]["x"] == 20, str(kids[0]))
        dup = kids[1]
        check("Alt+drag: копия рядом с оригиналом",
              abs(dup["frame"]["x"] - 100) <= 4 and abs(dup["frame"]["y"] - 70) <= 4, str(dup))
        check("Alt+drag: выделена копия",
              pg.evaluate("document.querySelectorAll('.dna-editor .geo-box.selected').length === 1"))

        # ---------- 3) undo откатывает Alt+drag одним шагом ----------
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        # Ctrl+Z — глобальный хоткей DNA-редактора (editor.js), выделение ноды не нужно
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(400)
        kids = pg.evaluate(NODE_IR + ".tree[0].children")
        check("undo: Alt+drag откатился одним шагом", len(kids) == 3, str(len(kids)))

        # ---------- 4) Alt+drag в auto-родителе: копия в поток ----------
        a0 = bb('.dna-editor [data-ir-sec="1"] [data-ir-path="children.0"]')
        pg.mouse.click(a0["x"] + a0["width"] / 2, a0["y"] + a0["height"] / 2)
        pg.wait_for_timeout(250)
        pg.keyboard.down("Alt")
        pg.mouse.move(a0["x"] + a0["width"] / 2, a0["y"] + a0["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(a0["x"] + a0["width"] / 2 + 40, a0["y"] + a0["height"] / 2 + 20, steps=8)
        pg.mouse.up()
        pg.keyboard.up("Alt")
        pg.wait_for_timeout(400)
        akids = pg.evaluate(NODE_IR + ".tree[1].children")
        check("Alt+drag auto: копия в потоке (3 children)", len(akids) == 3, str(len(akids)))
        check("Alt+drag auto: копия без x/y (в раскладке)",
              "x" not in (akids[1].get("frame") or {}) , str(akids[1]))

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL P1-DRAG CHECKS PASSED")


if __name__ == "__main__":
    main()
