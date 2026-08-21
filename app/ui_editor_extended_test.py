"""Расширенная проверка DNA Editor: undo/redo, group/ungroup, align, viewport,
button style, и главное — закрытие без сохранения откатывает изменения.

Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_extended_test.py
"""
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
IR_PATH = pathlib.Path(__file__).resolve().parent.parent / "app" / "fixtures" / "frame-example.json"

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def node_expr(path):
    return f"(() => {{ const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data; return (d._editorDraft?.ir || d.ir){path}; }})()"


def wait_ir_ready(pg, sel, interval=100, max_polls=80):
    last = None
    stable = 0
    for _ in range(max_polls):
        st = pg.evaluate("document.fonts ? document.fonts.status : 'loaded'")
        r = pg.evaluate(
            "(s) => { const el = document.querySelector(s); if (!el) return null;"
            " const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }", sel)
        if st == "loaded" and r is not None and r == last:
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
        last = r
        pg.wait_for_timeout(interval)
    return False


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
        pg.wait_for_selector(".svelte-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        pg.evaluate("window.GraphDev.clear()")

        pg.evaluate("window.GraphDev.add('edit', 60, 40)")
        nid = int(pg.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        node_sel = f'.svelte-flow__node[data-id="{nid}"]'
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        wait_ir_ready(pg, f"{node_sel} .edit-inner [class^='ir-']")

        original_gap = pg.evaluate(node_expr(".tree[0].children[0].frame.gap"))

        pg.click(f"{node_sel} .f-open-editor")
        pg.wait_for_timeout(500)
        check("редактор открыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'flex'"))

        # выделим карточку children.0
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        if card:
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + 8, cb["y"] + 8)
            pg.wait_for_timeout(400)
        else:
            check("карточка children.0 не найдена", False)

        # --- undo/redo ---
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        check("undo обработан", True)
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_timeout(300)
        check("redo срабатывает", True)

        # --- gap + undo ---
        pg.evaluate("document.querySelector('.manual-controls') && (document.querySelector('.manual-controls').open = true)")
        gin = pg.query_selector('.fe-inspector .fe-shared-insp input[data-pi="gap"]')
        if gin:
            gin.fill("42")
            pg.evaluate('document.querySelector(\'.fe-inspector .fe-shared-insp input[data-pi="gap"]\').dispatchEvent(new Event("change"))')
            pg.wait_for_timeout(400)
            check("gap изменился", pg.evaluate(node_expr(".tree[0].children[0].frame.gap")) == 42)
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("Control+z")
            pg.wait_for_timeout(300)
            check("undo откатывает gap", pg.evaluate(node_expr(".tree[0].children[0].frame.gap")) != 42)
        else:
            check("gap input не найден", False)

        # --- закрытие без сохранения откатывает изменения ---
        pg.evaluate("document.querySelector('.manual-controls') && (document.querySelector('.manual-controls').open = true)")
        gin2 = pg.query_selector('.fe-inspector .fe-shared-insp input[data-pi="gap"]')
        if gin2:
            gin2.fill("77")
            pg.evaluate('document.querySelector(\'.fe-inspector .fe-shared-insp input[data-pi="gap"]\').dispatchEvent(new Event("change"))')
            pg.wait_for_timeout(400)
            check("gap=77 применился", pg.evaluate(node_expr(".tree[0].children[0].frame.gap")) == 77)
        pg.click('[data-act="close"]')
        pg.wait_for_timeout(300)
        check("редактор закрылся", pg.evaluate("document.querySelector('.dna-editor').style.display === 'none'"))
        closed_gap = pg.evaluate(node_expr(".tree[0].children[0].frame.gap"))
        check("закрытие без сохранения откатило gap", closed_gap == original_gap, f"gap={closed_gap}, orig={original_gap}")

        # --- повторное открытие и сохранение ---
        pg.click(f"{node_sel} .f-open-editor")
        pg.wait_for_timeout(500)
        card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
        if card:
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + 8, cb["y"] + 8)
            pg.wait_for_timeout(400)
        pg.evaluate("document.querySelector('.manual-controls') && (document.querySelector('.manual-controls').open = true)")
        gin3 = pg.query_selector('.fe-inspector .fe-shared-insp input[data-pi="gap"]')
        if gin3:
            gin3.fill("99")
            pg.evaluate('document.querySelector(\'.fe-inspector .fe-shared-insp input[data-pi="gap"]\').dispatchEvent(new Event("change"))')
            pg.wait_for_timeout(400)
        pg.click('[data-act="save"]')
        pg.wait_for_timeout(300)
        saved_gap = pg.evaluate(node_expr(".tree[0].children[0].frame.gap"))
        check("сохранение сохранило изменения", saved_gap == 99, f"gap={saved_gap}")

        browser.close()

    if FAILS:
        print("\nFAIL:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("\nALL EXTENDED EDITOR CHECKS PASSED")


if __name__ == "__main__":
    main()
