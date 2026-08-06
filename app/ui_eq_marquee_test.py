"""UI-тест задачи 5: фиолетовые equal-spacing метки при drag + marquee для
вложенных (children любой глубины) и props-элементов.
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_eq_marquee_test.py
"""
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"

FAILS = []

# три карточки в ряд: gap(card1,card2)=40, gap(card2,card3)=20 —
# при сдвиге card3 на +20 зазоры становятся равны и должны появиться geo-eq метки
IR = {
    "version": "1.0",
    "meta": {"name": "Задача 5: eq-spacing + marquee", "description": "тестовая фикстура",
             "styleTags": ["test"]},
    "frame": {"width": 960, "height": 760},
    "tokens": {
        "mode": "light",
        "color": {"primary": "#0E7A5F", "secondary": "#134E48", "accent": "#E85D26",
                  "background": "#FFFFFF", "surface": "#F6F7F8", "text": "#17201D",
                  "textMuted": "#5D6B66", "border": "#E2E7E5"},
        "font": {"display": {"family": "Manrope", "weight": 800},
                 "body": {"family": "Inter", "weight": 400}, "scale": "default"},
        "radius": {"card": "lg", "button": "full", "input": "md"},
        "spacing": {"section": "md", "container": "default"},
        "shadow": "sm",
    },
    "tree": [
        {
            "id": "hero-sec", "type": "hero",
            "props": {"heading": "Равные зазоры",
                      "subheading": "Проверка фиолетовых меток и marquee очень длинной строкой текста",
                      "ctaPrimary": {"text": "Старт", "variant": "primary"},
                      "ctaSecondary": {"text": "Демо", "variant": "outline"}},
            "frame": {"width": "fill", "padding": 40},
        },
        {
            "id": "cards-row", "type": "feature-grid",
            "frame": {"width": "fill", "height": 240, "layout": "free", "padding": 0},
            "children": [
                {"type": "card",
                 "frame": {"x": 20, "y": 40, "width": 200, "height": 120,
                           "layout": "free", "padding": 0},
                 "children": [
                     {"type": "rect", "fill": "#8B5CF6", "radius": 8,
                      "frame": {"x": 12, "y": 12, "width": 120, "height": 28}}
                 ]},
                {"type": "card", "frame": {"x": 260, "y": 40, "width": 200, "height": 120}},
                {"type": "card", "frame": {"x": 480, "y": 40, "width": 200, "height": 120}},
            ],
        },
    ],
}


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def chips(pg):
    return pg.evaluate(
        "Array.from(document.querySelectorAll('.n-edit .geo-box.selected .geo-chip'))"
        ".map(c => c.textContent)")


def marquee(pg, x0, y0, x1, y1, modifier=None):
    if modifier:
        pg.keyboard.down(modifier)
    pg.mouse.move(x0, y0)
    pg.mouse.down()
    pg.mouse.move(x1, y1, steps=8)
    pg.mouse.up()
    if modifier:
        pg.keyboard.up(modifier)
    pg.wait_for_timeout(350)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1700, "height": 1000})
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
        # шрифты не догружены, геометрия плавает — замеры и marquee расходятся.
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

        # экранный масштаб превью (screen px / canvas px)
        scale = pg.evaluate(
            "(() => { const el = document.querySelector('.n-edit [data-ir-sec=\"1\"]');"
            " return el.getBoundingClientRect().width / el.offsetWidth; })()")

        # ---------- 1) equal spacing: drag третьей карточки до равных gap ----------
        card3 = pg.query_selector('.n-edit [data-ir-sec="1"] [data-ir-path="children.2"]')
        cb = card3.bounding_box()
        cx, cy = cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2
        pg.mouse.click(cx, cy)
        pg.wait_for_timeout(250)
        check("card3 выделена", pg.evaluate(
            "document.querySelectorAll('.n-edit .geo-box.selected').length === 1"))

        pg.mouse.move(cx, cy)
        pg.mouse.down()
        pg.mouse.move(cx + 20 * scale, cy, steps=12)
        pg.wait_for_timeout(300)
        eqn = pg.evaluate("document.querySelectorAll('.n-edit .geo-eq').length")
        labels = pg.evaluate(
            "Array.from(document.querySelectorAll('.n-edit .geo-eq-label')).map(e => e.textContent)")
        check("eq-метки появились при равных зазорах", eqn >= 2, f"n={eqn}")
        check("eq-метка показывает величину зазора (40px)",
              any("40" in t for t in labels), str(labels))
        SHOT_DIR.mkdir(exist_ok=True)
        pg.screenshot(path=str(SHOT_DIR / "ui_eq_spacing.png"), full_page=False)
        pg.mouse.up()
        pg.wait_for_timeout(350)
        check("eq-метки убраны после drop",
              pg.evaluate("document.querySelectorAll('.n-edit .geo-eq').length === 0"))
        fx = pg.evaluate("window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id))"
                         ".data.ir.tree[1].children[2].frame.x")
        check("drag записал frame.x ≈ 500", isinstance(fx, (int, float)) and 497 <= fx <= 503,
              str(fx))

        # ---------- 2) marquee: вложенный элемент (children.children) ----------
        nested = pg.query_selector('.n-edit [data-ir-path="children.0.children.0"]')
        nb = nested.bounding_box()
        art = pg.query_selector('.n-edit [class^="ir-"]').bounding_box()
        band_y = art["y"] + art["height"] - 6 * scale  # пустая зона под секциями
        marquee(pg, nb["x"] + nb["width"] + 3, band_y, nb["x"] - 3, nb["y"] - 3)
        cs = chips(pg)
        check("marquee выделил вложенный rect", any(c.startswith("rect ·") for c in cs), str(cs))
        check("marquee: секция и карточка-родитель (пересечение)",
              any(c.startswith("section ·") for c in cs) and any(c.startswith("card ·") for c in cs),
              str(cs))
        check("marquee: только 3 объекта (без чужих карточек)", len(cs) == 3, str(cs))
        pg.screenshot(path=str(SHOT_DIR / "ui_marquee_nested.png"), full_page=False)

        # ---------- 3) marquee: props-элементы секции ----------
        head = pg.query_selector('.n-edit [data-ir-path="props.heading"]').bounding_box()
        marquee(pg, head["x"] + head["width"] + 4, band_y, head["x"] - 4, head["y"] - 4)
        cs = chips(pg)
        check("marquee выделил props.heading", any(c.startswith("heading ·") for c in cs), str(cs))
        check("marquee: широкий subheading НЕ внутри узкой рамки",
              not any(c.startswith("subheading ·") for c in cs), str(cs))

        # ---------- 4) большой marquee: всё содержимое ----------
        marquee(pg, art["x"] + art["width"] - 8 * scale, band_y,
                art["x"] + 6 * scale, art["y"] + 6 * scale)
        cs = chips(pg)
        check("большой marquee: вложенные + props + карточки",
              len(cs) >= 8
              and any(c.startswith("rect ·") for c in cs)
              and any(c.startswith("heading ·") for c in cs)
              and any(c.startswith("subheading ·") for c in cs)
              and sum(1 for c in cs if c.startswith("card ·")) == 3,
              str(cs))

        # ---------- 5) deep-логика (Ctrl+click) не конфликтует с marquee ----------
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
        check("Esc снимает выделение после marquee", len(chips(pg)) == 0)
        nx, ny = nb["x"] + nb["width"] / 2, nb["y"] + nb["height"] / 2
        pg.keyboard.down("Control")
        pg.mouse.click(nx, ny)
        pg.keyboard.up("Control")
        pg.wait_for_timeout(300)
        cs = chips(pg)
        check("Ctrl+click после marquee: один вложенный элемент",
              len(cs) == 1 and cs[0].startswith("rect ·"), str(cs))

        # ---------- 6) Shift+marquee добирает к существующему выделению ----------
        c2 = pg.query_selector('.n-edit [data-ir-sec="1"] [data-ir-path="children.1"]').bounding_box()
        # старт в пустой зоне слева-снизу, конец справа-сверху — рамка накрывает card2
        marquee(pg, c2["x"] - 12, band_y, c2["x"] + c2["width"] + 12, c2["y"] - 4,
                modifier="Shift")
        cs = chips(pg)
        check("Shift+marquee: прежнее выделение сохранено и дополнено",
              any(c.startswith("rect ·") for c in cs) and any(c.startswith("card ·") for c in cs),
              str(cs))

        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL TASK5 CHECKS PASSED")


if __name__ == "__main__":
    main()
