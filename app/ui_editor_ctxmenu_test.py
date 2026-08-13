"""UI-тест контекстного меню канваса (правый клик) в DNA-редакторе —
паттерн OpenPencil/Figma: меню с copy/cut/paste/duplicate, z-order,
group/ungroup, delete и копированием IR-пути.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_ctxmenu_test.py
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
        pg.wait_for_timeout(500)

        def wait_ir_ready(sel, polls=3, interval=150):
            hits = 0
            for _ in range(80):
                st = pg.evaluate("document.fonts ? document.fonts.status : 'loaded'")
                hits = hits + 1 if st == "loaded" else 0
                if hits >= polls:
                    break
                pg.wait_for_timeout(interval)
            last, stable = None, 0
            for _ in range(50):
                r = pg.evaluate(
                    "(s) => { const el = document.querySelector(s); if (!el) return null;"
                    " const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }",
                    sel)
                if r is not None and r == last:
                    stable += 1
                    if stable >= polls:
                        return
                else:
                    stable = 0
                last = r
                pg.wait_for_timeout(interval)

        wait_ir_ready('.n-edit .edit-inner [class^="ir-"]')
        pg.click(".n-edit .f-open-editor")
        pg.wait_for_selector('.dna-editor[style*="flex"]')
        pg.wait_for_timeout(600)

        CARD_COUNT = "window.GraphDev.node(%d).data.ir.tree[0].children.length" % nid

        def click_card():
            card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + 12, cb["y"] + 12)
            pg.wait_for_timeout(250)

        def right_click_card():
            card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2, button="right")
            pg.wait_for_timeout(250)

        def menu_item(label):
            return pg.query_selector('.geo-ctx-menu .geo-ctx-item:has-text("%s")' % label)

        def item_disabled(label):
            el = menu_item(label)
            return (el is None) or el.evaluate("el => el.classList.contains('disabled')")

        # --- 1. меню открывается на элементе ---
        click_card()
        right_click_card()
        menu = pg.query_selector(".geo-ctx-menu")
        check("меню открылось по правому клику", menu is not None)
        items = pg.query_selector_all(".geo-ctx-menu .geo-ctx-item")
        check("состав меню: 10 пунктов", len(items) == 10, f"пунктов={len(items)}")
        check("пустой буфер: Вставить disabled", item_disabled("Вставить"))
        check("один выделенный: Группа disabled", item_disabled("Группа"))
        check("не free-контейнер: Разгруппировать disabled", item_disabled("Разгруппировать"))
        check("IR-путь в меню", menu_item("Копировать IR-путь") is not None)

        # --- 2. Esc закрывает меню, не трогая выделение ---
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check("Esc закрыл меню", pg.query_selector(".geo-ctx-menu") is None)
        check("выделение после Esc сохранено",
              pg.query_selector(".geo-box.selected") is not None)

        # --- 3. Копировать через меню -> буфер ---
        right_click_card()
        mi = menu_item("Копировать")
        mi.click()
        pg.wait_for_timeout(250)
        check("меню закрылось после действия", pg.query_selector(".geo-ctx-menu") is None)

        # --- 4. Вставить через меню ---
        right_click_card()
        check("буфер полон: Вставить enabled", not item_disabled("Вставить"))
        before = pg.evaluate(CARD_COUNT)
        menu_item("Вставить").click()
        pg.wait_for_timeout(300)
        after = pg.evaluate(CARD_COUNT)
        check("Вставить: children +1", after == before + 1, f"{before} -> {after}")

        # --- 5. Дублировать через меню ---
        right_click_card()
        before = pg.evaluate(CARD_COUNT)
        menu_item("Дублировать").click()
        pg.wait_for_timeout(300)
        after = pg.evaluate(CARD_COUNT)
        check("Дублировать: children +1", after == before + 1, f"{before} -> {after}")

        # --- 6. Удалить через меню ---
        right_click_card()
        before = pg.evaluate(CARD_COUNT)
        menu_item("Удалить").click()
        pg.wait_for_timeout(300)
        after = pg.evaluate(CARD_COUNT)
        check("Удалить: children -1", after == before - 1, f"{before} -> {after}")

        # --- 7. правый клик по невыделенному выделяет его (Figma) ---
        # deleteSelections уже снял выделение; Esc здесь звать нельзя —
        # consumeEscape вернёт false и контроллер закроет редактор
        check("выделение снято после Удалить", pg.query_selector(".geo-box.selected") is None)
        right_click_card()
        check("правый клик выделил элемент", pg.query_selector(".geo-box.selected") is not None)
        check("и открыл меню", pg.query_selector(".geo-ctx-menu") is not None)

        # --- 8. клик мимо меню закрывает его ---
        canvas = pg.query_selector(".fe-canvas-inner")
        cbb = canvas.bounding_box()
        pg.mouse.click(cbb["x"] + 8, cbb["y"] + 8)
        pg.wait_for_timeout(200)
        check("клик вне меню закрыл его", pg.query_selector(".geo-ctx-menu") is None)

        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_timeout(400)
        browser.close()

    if FAILS:
        print("\nFAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("\nALL CONTEXT MENU CHECKS PASSED")


if __name__ == "__main__":
    main()
