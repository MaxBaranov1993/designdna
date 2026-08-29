"""Smoke-тест полноэкранного DNA-редактора после перевода на общий инспектор.
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_test.py
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
            print("server not ready"); sys.exit(2)
        pg.evaluate("localStorage.clear()")
        pg.reload()
        pg.wait_for_selector(".svelte-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        pg.evaluate("window.GraphDev.clear()")
        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)

        # Новый UI: renderer.js асинхронно подгружает Google-шрифты IR и делает
        # reflow превью (в legacy соединение грел page-шрифт nodes.html). Пока
        # шрифты не догружены, геометрия плавает — замеры и drag расходятся.
        # Ждём до открытия редактора: в него IR уходит с уже загруженными шрифтами.
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
        check("редактор открыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'flex'"))
        check("слои построены", pg.evaluate("document.querySelectorAll('.fe-layer').length > 3"))
        wait_ir_ready('.fe-canvas [data-ir-path="children.0"]')

        # выделение карточки на канвасе
        card_selector = '.fe-canvas [data-ir-path="children.0"]'
        cb = pg.evaluate("""(selector) => {
            const box = document.querySelector(selector)?.getBoundingClientRect();
            return box ? { x: box.x, y: box.y, width: box.width, height: box.height } : null;
        }""", card_selector)
        pg.mouse.click(cb["x"] + 8, cb["y"] + 8)
        pg.wait_for_timeout(400)
        check("выделение в редакторе", pg.evaluate("document.querySelectorAll('.fe-canvas .geo-box.selected').length === 1"))

        # общий инспектор внутри fe-inspector
        check("инспектор: общий блок Position/Flex", pg.evaluate(
            "!!document.querySelector('.fe-inspector .fe-shared-insp input[data-pi=\"x\"]')"))
        check("инспектор: Flex Layout", pg.evaluate(
            "!!document.querySelector('.fe-inspector .fe-shared-insp [data-pi-dir=\"column\"]')"))

        # рамка совпадает с элементом
        box = pg.query_selector('.fe-canvas .geo-box.selected').bounding_box()
        cb2 = pg.evaluate("""(selector) => {
            const box = document.querySelector(selector)?.getBoundingClientRect();
            return box ? { x: box.x, y: box.y, width: box.width, height: box.height } : null;
        }""", card_selector)
        d = max(abs(box["x"] - cb2["x"]), abs(box["y"] - cb2["y"]))
        check("рамка выделения совпадает", d < 4, f"d={d:.1f}")

        # gap через инспектор (manual-контролы свёрнуты по умолчанию — раскрываем)
        pg.evaluate("document.querySelector('.manual-controls') && (document.querySelector('.manual-controls').open = true)")
        # gap через инспектор
        gin = pg.query_selector('.fe-inspector .fe-shared-insp input[data-pi="gap"]')
        gin.fill("24")
        pg.evaluate("document.querySelector('.fe-inspector .fe-shared-insp input[data-pi=\"gap\"]').dispatchEvent(new Event('change'))")
        pg.wait_for_timeout(400)
        gp = pg.evaluate("(() => { const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data; return (d._editorDraft?.ir || d.ir).tree[0].children[0].frame.gap; })()")
        check("инспектор редактора: gap=24", gp == 24, str(gp))

        # undo после мутации (снимаем фокус с input, чтобы дошёл хоткей)
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        gp2 = pg.evaluate("(() => { const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data; return (d._editorDraft?.ir || d.ir).tree[0].children[0].frame.gap; })()")
        check("undo откатывает gap", gp2 != 24, str(gp2))

        # левая панель инструментов как в pen.dev
        check("rail: 8 плоских кнопок (хендофф)", pg.evaluate(
            "document.querySelectorAll('.dna-editor .fe-rail [data-tool]').length === 8"))
        pg.click('.dna-editor .fe-rail [data-tool="rect"]')
        pg.wait_for_timeout(200)
        check("rail: rect активен", pg.evaluate(
            "document.querySelector('.dna-editor .fe-rail [data-tool=\"rect\"]').classList.contains('active')"))
        sec = pg.query_selector('.fe-canvas [data-ir-sec="0"]')
        sb = sec.bounding_box()
        pg.mouse.move(sb["x"] + sb["width"] - 140, sb["y"] + 30)
        pg.mouse.down()
        pg.mouse.move(sb["x"] + sb["width"] - 50, sb["y"] + 110, steps=5)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        rects = pg.evaluate("(() => { const out = []; const walk = (n) => (n.children || []).forEach(c => { out.push(c); walk(c); }); const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data; ((d._editorDraft?.ir || d.ir).tree || []).forEach(s => walk(s)); return out.filter(c => c.type === 'rect').length; })()")
        check("rail: rect создан на канвасе", rects == 1, str(rects))

        # hand панорамирует канвас
        tr0 = pg.evaluate("document.querySelector('.fe-canvas-inner').style.transform")
        pg.click('.dna-editor .fe-rail [data-tool="hand"]')
        pg.wait_for_timeout(150)
        pg.mouse.move(sb["x"] + 200, sb["y"] + 150)
        pg.mouse.down()
        pg.mouse.move(sb["x"] + 240, sb["y"] + 190, steps=4)
        pg.mouse.up()
        pg.wait_for_timeout(200)
        tr1 = pg.evaluate("document.querySelector('.fe-canvas-inner').style.transform")
        check("rail: hand панорамирует", tr0 != tr1, f"{tr0} -> {tr1}")

        # хоткей V возвращает select (синхрон с панелью)
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("v")
        pg.wait_for_timeout(200)
        check("rail: хоткей V — select активен", pg.evaluate(
            "document.querySelector('.dna-editor .fe-rail [data-tool=\"select\"]').classList.contains('active')"))

        pg.click('.fe-toolbar [data-act="close"]')
        pg.wait_for_timeout(300)
        check("редактор закрыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'none'"))
        browser.close()

    print()
    if FAILS:
        print("FAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL EDITOR CHECKS PASSED")


if __name__ == "__main__":
    main()
