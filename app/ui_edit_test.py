"""UI-тест thin-ноды «Редактор»: только preview + вход в DNA Editor.

Детальная Figma/Pen.dev-механика проверяется в app/ui_editor_test.py.
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
SHOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "results"

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
        pg = browser.new_page(viewport={"width": 1500, "height": 900})
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
        node = f'.svelte-flow__node[data-id="{nid}"]'
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_selector(f'{node} .f-preview .ir-preview-inner div[class^="ir-"]', timeout=5000)

        check("preview отрендерился", True)
        check("inline Inspector не монтируется", pg.locator(f"{node} .edit-inspector").count() == 0)
        check("inline GeoEdit не монтируется", pg.locator(f"{node} .geo-overlay").count() == 0)
        check("кнопка открытия редактора есть", pg.locator(f"{node} .f-open-editor").count() == 1)

        pg.click(f"{node} .f-open-editor")
        pg.wait_for_selector(".dna-editor .fe-canvas", timeout=5000)
        check("fullscreen DNA Editor открылся", pg.evaluate("document.querySelector('.dna-editor').style.display === 'flex'"))

        SHOT_DIR.mkdir(exist_ok=True)
        pg.screenshot(path=str(SHOT_DIR / "ui_edit_node.png"), full_page=False)
        browser.close()

    if FAILS:
        print("\nFAILURES:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("\nALL UI CHECKS PASSED")


if __name__ == "__main__":
    main()
