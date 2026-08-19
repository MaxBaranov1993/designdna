"""UI-тест color picker в инспекторе DNA-редактора (по мотивам OpenPencil):
SV-поле, hue-слайдер, HEX-ввод, свотчи design-токенов, батчинг undo при
потоковых записях стиля, закрытие по Esc/клику вне.

Важно: undo/redo в контроллере восстанавливают снапшот IR, делают sel=[] и
перестраивают инспектор — пикер при этом закрывается (легаси-поведение).
Поэтому undo-проверки идут отдельными фазами с повторным выделением.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_colorpicker_test.py
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
        context = browser.new_context(viewport={"width": 1700, "height": 1000})
        pg = context.new_page()
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

        STYLE_BG = ("(() => { const d = window.GraphDev.node(%d).data; const n = (d._editorDraft?.ir || d.ir).tree[0].children[0];"
                    " return (n.style && n.style.background) || null; })()" % nid)

        def click_card():
            card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + 12, cb["y"] + 12)
            pg.wait_for_timeout(300)
            manual = pg.query_selector(".manual-controls")
            if manual is not None and manual.get_attribute("open") is None:
                pg.click(".manual-controls summary")

        def open_picker():
            sw = pg.query_selector('.fe-inspector .pi-cp-swatch')
            if sw is None:
                return False
            sw.click()
            pg.wait_for_timeout(250)
            return pg.query_selector(".pi-cp-pop") is not None

        # ================= Фаза 1: устройство пикера + запись без undo =================
        click_card()
        check("свотч Fill в инспекторе", pg.query_selector('.fe-inspector .pi-cp-swatch') is not None)
        check("пикер открылся", open_picker())
        check("SV-поле есть", pg.query_selector(".pi-cp-sv") is not None)
        check("hue-слайдер есть", pg.query_selector(".pi-cp-hue") is not None)
        check("HEX-поле есть", pg.query_selector(".pi-cp-hex") is not None)
        tokens = pg.query_selector_all(".pi-cp-token")
        check("свотчи токенов IR (8)", len(tokens) == 8, f"токенов={len(tokens)}")

        pg.fill(".pi-cp-hex", "ff6600")
        pg.press(".pi-cp-hex", "Enter")
        pg.wait_for_timeout(250)
        v = pg.evaluate(STYLE_BG)
        check("HEX ff6600 записан", v == "#ff6600", f"v={v!r}")
        pg.wait_for_timeout(450)  # разорвать undo-сессию (батчинг 300 мс)

        pg.query_selector_all(".pi-cp-token")[0].click()
        pg.wait_for_timeout(250)
        v = pg.evaluate(STYLE_BG)
        check("токен записан (#0e7a5f)", v == "#0e7a5f", f"v={v!r}")
        pg.wait_for_timeout(450)

        # ================= Фаза 2: SV-drag — поток записей = один undo-шаг ============
        sv = pg.query_selector(".pi-cp-sv").bounding_box()
        pg.mouse.move(sv["x"] + sv["width"] * 0.7, sv["y"] + sv["height"] * 0.3)
        pg.mouse.down()
        pg.mouse.move(sv["x"] + sv["width"] * 0.4, sv["y"] + sv["height"] * 0.6, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(450)
        v_drag = pg.evaluate(STYLE_BG)
        check("SV-drag изменил цвет", v_drag not in (None, "#0e7a5f"), f"v={v_drag!r}")

        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(350)
        v_undo = pg.evaluate(STYLE_BG)
        check("один Ctrl+Z откатил всю серию drag до токена", v_undo == "#0e7a5f", f"v={v_undo!r}")

        pg.keyboard.press("Control+Shift+Z")
        pg.wait_for_timeout(350)
        v_redo = pg.evaluate(STYLE_BG)
        check("redo вернул результат drag", v_redo == v_drag, f"v={v_redo!r}, ждём {v_drag!r}")

        # ================= Фаза 3: hue-слайдер (пикер переоткрываем) ==================
        # undo/redo сняли выделение и закрыли пикер — выделяем заново
        click_card()
        check("пикер переоткрылся", open_picker())
        pg.wait_for_timeout(450)
        have_hue = pg.evaluate("!!document.querySelector('.pi-cp-hue')")
        check("hue-слайдер на месте после переоткрытия", have_hue)
        pg.evaluate("(() => { const el = document.querySelector('.pi-cp-hue');"
                    " if (!el) return;"
                    " const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');"
                    " desc.set.call(el, '210');"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); })()")
        pg.wait_for_timeout(250)
        v_hue = pg.evaluate(STYLE_BG)
        check("hue-слайдер изменил цвет", v_hue not in (None, v_drag) and str(v_hue).startswith("#"),
              f"v={v_hue!r}, до={v_drag!r}")

        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(350)
        v_hue_undo = pg.evaluate(STYLE_BG)
        check("undo hue вернул цвет drag", v_hue_undo == v_drag,
              f"v={v_hue_undo!r}, ждём {v_drag!r}")

        # ================= Фаза 4: Esc закрывает пикер, выделение живо ================
        click_card()
        check("пикер открыт перед Esc-проверкой", open_picker())
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
        check("Esc закрыл пикер", pg.query_selector(".pi-cp-pop") is None)
        check("выделение после Esc сохранено", pg.query_selector(".geo-box.selected") is not None)

        # ================= Фаза 5: клик вне пикера закрывает его ======================
        check("пикер снова открыт", open_picker())
        canvas = pg.query_selector(".fe-canvas-inner")
        cbb = canvas.bounding_box()
        pg.mouse.click(cbb["x"] + 8, cbb["y"] + 8)
        pg.wait_for_timeout(250)
        check("клик вне закрыл пикер", pg.query_selector(".pi-cp-pop") is None)

        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_timeout(400)
        pg.close(run_before_unload=False)
        context.close()
        browser.close()

    if FAILS:
        print("\nFAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("\nALL COLOR PICKER CHECKS PASSED")


if __name__ == "__main__":
    main()
