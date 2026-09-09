"""Smoke-тест Style DNA Inspector в полноэкранном DNA-редакторе.

Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_style_dna_test.py
"""
import pathlib
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
ROOT = pathlib.Path(__file__).resolve().parent.parent

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def make_ir():
    return {
        "version": "1.1",
        "frame": {"width": 400, "height": 120, "layout": "free"},
        "tokens": {
            "mode": "light",
            "color": {
                "primary": "#ff691d",
                "secondary": "#ff691d",
                "accent": "#ff691d",
                "background": "#ffffff",
                "surface": "#f5f5f7",
                "text": "#1a1a1a",
                "textMuted": "#666666",
                "border": "#e0e0e0",
            },
            "font": {
                "display": {"family": "Inter", "weight": 700},
                "body": {"family": "Inter", "weight": 400},
                "scale": "default",
            },
            "radius": {"card": "md", "button": "md", "input": "md"},
            "spacing": {"section": "md", "container": "default"},
            "shadow": "none",
        },
        "tree": [
            {
                "id": "src-header",
                "type": "source-block",
                "variant": "dom-capture",
                "props": {},
                "frame": {"x": 0, "y": 0, "width": 400, "height": 120, "layout": "free", "clip": True},
                "children": [
                    {
                        "type": "card",
                        "role": "source-container",
                        "frame": {"x": 0, "y": 0, "width": 400, "height": 120},
                        "style": {"background": "#ffffff"},
                    },
                    {
                        "type": "button",
                        "text": "Найти",
                        "frame": {"x": 20, "y": 20, "width": 100, "height": 40},
                        "style": {"background": "#ff691d", "color": "#ffffff", "borderRadius": 8, "fontSize": 14},
                    }
                ],
            }
        ],
    }


def main():
    ir = make_ir()
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
        pg.evaluate("(ir) => window.GraphDev.setIR(%d, ir)" % nid, ir)
        pg.wait_for_timeout(500)

        # открываем редактор
        pg.click(".n-edit .f-open-editor")
        pg.wait_for_timeout(500)
        check("редактор открыт", pg.evaluate("document.querySelector('.dna-editor').style.display === 'flex'"))

        # открываем Style DNA Inspector
        pg.click('[data-act="style-dna"]')
        pg.wait_for_timeout(500)
        check("Style DNA панель открыта", pg.evaluate("document.getElementById('feDnaPanel').classList.contains('open')"))

        # проверяем что семантические цвета загрузились
        primary = pg.evaluate("document.querySelector('#feDnaBody input[data-kind=\"color\"][data-key=\"primary\"]')?.value")
        check("primary token отображается", primary == "#ff691d", str(primary))

        # меняем primary
        pg.evaluate("""() => {
          const inp = document.querySelector('#feDnaBody input[data-kind="color"][data-key="primary"]');
          inp.value = '#00aa00';
          inp.dispatchEvent(new Event('input', {bubbles: true}));
        }""")
        pg.wait_for_timeout(200)

        # применяем
        pg.wait_for_function("() => { const b = document.querySelector('[data-act=\"apply-style-dna\"]'); return b && !b.disabled; }")
        pg.click('[data-act="apply-style-dna"]')
        pg.wait_for_timeout(800)

        # проверяем что IR обновился
        bg = pg.evaluate(
            """() => {
              const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data;
              const ir = d._editorDraft?.ir || d.ir;
              return ir.tree[0].children[1].style.background;
            }"""
        )
        check("применение Style DNA меняет button background", bg == "#00aa00", str(bg))

        # проверяем что binding появился
        token = pg.evaluate(
            """() => {
              const d = window.GraphDev.node(Number(document.querySelector('.n-edit').dataset.id)).data;
              const ir = d._editorDraft?.ir || d.ir;
              return ir.tree[0].children[1].styleBindings.background.token;
            }"""
        )
        check("styleBinding указывает на semantic.primary", token == "semantic.primary", str(token))

        pg.click('[data-act="close-style-dna"]')
        pg.wait_for_timeout(200)
        check("Style DNA панель закрыта", not pg.evaluate("document.getElementById('feDnaPanel').classList.contains('open')"))

        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL STYLE DNA CHECKS PASSED")


if __name__ == "__main__":
    main()
