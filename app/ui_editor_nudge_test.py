"""UI-тест паттернов, заимствованных из OpenPencil (MIT):
1) батчинг nudge-undo — серия стрелок с интервалом < 300 мс откатывается
   ОДНИМ Ctrl+Z (core/editor/nudge.ts: debounce-коммит);
2) Ctrl+D — дубликат выделения in-place, не трогая буфер обмена (Figma-стандарт).
Ретаргетинг после снятия legacy /nodes: edit-нода живёт в новом React Flow UI на /flow.
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_editor_nudge_test.py
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

        CARD_X = ("(() => { const f = window.GraphDev.node(%d).data.ir.tree[0].children[0].frame;"
                  " return typeof f.x === 'number' ? f.x : null; })()" % nid)
        CARD_COUNT = "window.GraphDev.node(%d).data.ir.tree[0].children.length" % nid

        def select_card():
            card = pg.query_selector('.fe-canvas [data-ir-path="children.0"]')
            cb = card.bounding_box()
            pg.mouse.click(cb["x"] + 12, cb["y"] + 12)
            pg.wait_for_timeout(250)

        select_card()
        x0 = pg.evaluate(CARD_X)
        check("card без x до nudge", x0 is None, f"x={x0!r}")

        # --- 1. серия из 5 стрелок -> один undo-шаг ---
        # Первый nudge освобождает auto-layout-родителя (ensureParentFree пишет
        # измеренную позицию в frame), поэтому базой служит x после первого шага.
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(60)
        xa = pg.evaluate(CARD_X)
        check("первый nudge: x материализован", isinstance(xa, int), f"x={xa!r}")
        for _ in range(4):
            pg.keyboard.press("ArrowRight")
            pg.wait_for_timeout(30)
        pg.wait_for_timeout(300)
        x1 = pg.evaluate(CARD_X)
        check("ещё 4x ArrowRight: x=база+4", x1 == xa + 4, f"x={x1!r}, база={xa}")

        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        x2 = pg.evaluate(CARD_X)
        check("nudge-батчинг: один Ctrl+Z откатил всю серию", x2 is None, f"x={x2!r}")

        pg.keyboard.press("Control+Shift+Z")
        pg.wait_for_timeout(300)
        x3 = pg.evaluate(CARD_X)
        check("redo вернул серию целиком", x3 == xa + 4, f"x={x3!r}, ждём {xa + 4}")

        # --- 2. Ctrl+D: дубликат выделения ---
        select_card()
        before = pg.evaluate(CARD_COUNT)
        pg.keyboard.press("Control+d")
        pg.wait_for_timeout(300)
        after = pg.evaluate(CARD_COUNT)
        check("Ctrl+D: children +1", after == before + 1, f"{before} -> {after}")

        dup_x = pg.evaluate(
            "(() => { const f = window.GraphDev.node(%d).data.ir.tree[0].children[1].frame;"
            " return typeof f.x === 'number' ? f.x : null; })()" % nid)
        check("дубликат со сдвигом +16", dup_x == xa + 4 + 16,
              f"x={dup_x!r}, ждём {xa + 4 + 16}")

        dup_key = pg.evaluate("window.GraphDev.node(%d).data.ir.tree[0].children[1].sourceKey" % nid)
        check("дубликат получил sourceKey", bool(dup_key), f"sourceKey={dup_key!r}")

        # выделен именно дубликат: Delete убирает копию, оригинал остаётся
        pg.keyboard.press("Delete")
        pg.wait_for_timeout(300)
        after_del = pg.evaluate(CARD_COUNT)
        x_orig = pg.evaluate(CARD_X)
        check("Delete после Ctrl+D удалил дубликат", after_del == before, f"children={after_del}")
        check("оригинал на месте", x_orig == xa + 4, f"x={x_orig!r}, ждём {xa + 4}")

        # буфер обмена Ctrl+D не трогал: Ctrl+V с пустым буфером ничего не вставляет
        pg.keyboard.press("Control+v")
        pg.wait_for_timeout(300)
        after_v = pg.evaluate(CARD_COUNT)
        check("Ctrl+D не пишет в буфер (Ctrl+V — без эффекта)", after_v == before,
              f"children={after_v}")

        # --- 3. пауза > 300 мс разрывает серию на два undo-шага ---
        select_card()
        base = pg.evaluate(CARD_X)
        for _ in range(2):
            pg.keyboard.press("ArrowRight")
            pg.wait_for_timeout(30)
        pg.wait_for_timeout(450)  # серия истекла
        for _ in range(2):
            pg.keyboard.press("ArrowRight")
            pg.wait_for_timeout(30)
        pg.wait_for_timeout(300)
        x4 = pg.evaluate(CARD_X)
        check("две серии по 2: +4 суммарно", x4 == base + 4, f"x={x4!r}, база={base}")
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        x5 = pg.evaluate(CARD_X)
        check("undo откатил только вторую серию", x5 == base + 2, f"x={x5!r}, ждём {base + 2}")

        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_timeout(400)
        browser.close()

    if FAILS:
        print("\nFAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("\nALL NUDGE/DUPLICATE CHECKS PASSED")


if __name__ == "__main__":
    main()
