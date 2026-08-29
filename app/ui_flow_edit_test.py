"""Smoke-тест thin Edit-ноды в React Flow.

Новый контракт: нода «Редактор (DNA)» внутри графа показывает только read-only
preview и кнопку открытия. GeoEdit/Inspector/Layers/Tools живут только в
полноэкранном DNA Editor.
"""
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"

SMALL_IR = {
    "frame": {"width": 960, "height": 800},
    "tokens": {"color": {"primary": "#5b5bd6", "background": "#ffffff"}},
    "tree": [
        {
            "id": "cta",
            "type": "cta",
            "variant": "centered",
            "props": {
                "heading": "Thin Edit Node",
                "subheading": "Нода показывает только превью",
                "ctaPrimary": {"text": "Открыть", "variant": "primary"},
            },
        }
    ],
}

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 900})
        pg.route(
            "**/api/project/load",
            lambda route: route.fulfill(status=200, content_type="application/json",
                                        body='{"project":null,"updated_at":null}'),
        )
        pg.route(
            "**/api/project/save",
            lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'),
        )

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
        pg.wait_for_function("window.GraphDev && window.IRRenderer && window.DNAEditor")

        e1 = pg.evaluate("window.GraphDev.add('edit', 80, 60).id")
        e2 = pg.evaluate("window.GraphDev.add('edit', 620, 60).id")
        n1 = f'.svelte-flow__node[data-id="{e1}"]'
        pg.evaluate(f"window.GraphDev.connect({e1}, 'ir', {e2}, 'a')")
        pg.evaluate(f"window.GraphDev.setIR({e1}, {json.dumps(SMALL_IR)})")

        pg.wait_for_selector(f'{n1} .f-preview .ir-preview-inner div[class^="ir-"]', timeout=5000)
        check("Edit-нода: IR отрендерился как preview", True)
        check("Edit-нода: propagate положил IR в downstream-ноду", pg.evaluate(f"!!window.GraphDev.node({e2}).data.ir"))
        check("Edit-нода: нет inline GeoEdit overlay", pg.locator(f"{n1} .geo-overlay").count() == 0)
        check("Edit-нода: нет inline Inspector", pg.locator(f"{n1} .edit-inspector").count() == 0)
        check("Edit-нода: нет inline zoom/frame tools", pg.locator(f"{n1} .geo-tools").count() == 0)
        check(
            "Edit-нода: компактная ширина preview-ноды",
            pg.evaluate(f"document.querySelector('{n1} .node').getBoundingClientRect().width <= 460"),
        )

        pg.click(f"{n1} .f-open-editor")
        pg.wait_for_selector('.dna-editor .fe-canvas-inner div[class^="ir-"]', timeout=5000)
        check("DNA-редактор: открылся из thin-ноды", pg.evaluate("document.querySelector('.dna-editor').style.display !== 'none'"))
        check("DNA-редактор: слои доступны", pg.evaluate("document.querySelectorAll('.dna-editor .fe-layer').length > 0"))
        check("DNA-редактор: toolbar/rail доступны", pg.evaluate("document.querySelectorAll('.dna-editor .fe-rail [data-tool]').length === 8"))

        pg.click('.dna-editor [data-act="save"]')
        pg.wait_for_timeout(300)
        check("DNA-редактор: сохранение закрыло редактор", pg.evaluate("document.querySelector('.dna-editor').style.display === 'none'"))
        check("DNA-редактор: IR остался в ноде", pg.evaluate(f"!!window.GraphDev.node({e1}).data.ir"))

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
