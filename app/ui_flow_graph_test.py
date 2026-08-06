"""Playwright-тест ядра нодового редактора на React Flow (Спринт 5, Фаза B1).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_graph_test.py

Проверяет: маршруты /flow, /, /nodes; правый клик по канвасу — контекстное меню;
создание нод Промпт/Референс/Генератор; ввод текста в Промпт; провода мышью
prompt.out -> generator.prompt и reference.out -> generator.style (оба text->text,
валидны по правилам legacy connect); после перезагрузки граф сохранён.
Провод prompt.out -> reference.ir отклоняется (правило совпадения kind).
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
PROMPT_TEXT = "Сгенерируй шапку маркетплейса объявлений"

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag_wire(pg, src_sel, dst_sel):
    """Протянуть провод мышью: pointerdown на handle-источнике, drop на приёмнике."""
    src = pg.wait_for_selector(src_sel)
    dst = pg.wait_for_selector(dst_sel)
    sx, sy = center(src.bounding_box())
    dx, dy = center(dst.bounding_box())
    pg.mouse.move(sx, sy)
    pg.mouse.down()
    pg.mouse.move(dx, dy, steps=14)
    pg.mouse.up()
    pg.wait_for_timeout(300)


def main():
    with sync_playwright() as p:
        # доступность маршрутов страниц
        api = p.request.new_context()
        for path in ("/flow", "/", "/nodes"):
            try:
                r = api.get(BASE + path)
                check(f"GET {path} -> 200", r.status == 200, str(r.status))
            except Exception as e:
                check(f"GET {path} -> 200", False, str(e))
        api.dispose()

        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 950})
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

        # правый клик по канвасу — контекстное меню создания ноды
        pg.click(".react-flow__pane", button="right", position={"x": 320, "y": 300})
        check("контекстное меню открыто", pg.is_visible("#ctx-menu"))
        # 9 типов: 7 базовых + BlockParse и Reskin (бриф W11)
        check("в меню 9 типов нод", pg.evaluate("document.querySelectorAll('#ctx-menu .ctx-item').length === 9"))

        # создать Промпт
        pg.click("#ctx-menu .ctx-item[data-type='prompt']")
        pg.wait_for_selector(".n-prompt")
        check("меню закрылось после выбора", not pg.is_visible("#ctx-menu"))

        # Референс и Генератор — правее (с запасом: нода Референса ~300px высотой)
        pg.click(".react-flow__pane", button="right", position={"x": 700, "y": 180})
        pg.click("#ctx-menu .ctx-item[data-type='reference']")
        pg.wait_for_selector(".n-reference")
        pg.click(".react-flow__pane", button="right", position={"x": 760, "y": 620})
        pg.click("#ctx-menu .ctx-item[data-type='generator']")
        pg.wait_for_selector(".n-generator")
        check("созданы 3 ноды", pg.evaluate("window.GraphDev.state().nodes.length === 3"))

        # ввод текста в Промпт
        pg.fill(".n-prompt .f-text", PROMPT_TEXT)
        pg.wait_for_timeout(150)
        text_ok = pg.evaluate(
            "(expected) => { const n = window.GraphDev.state().nodes.find(x => x.type === 'prompt');"
            " return !!n && window.GraphDev.node(n.id).data.text === expected; }",
            PROMPT_TEXT,
        )
        check("текст Промпта записан в data", bool(text_ok))

        # провода мышью: оба text->text, валидны по правилам legacy connect
        drag_wire(pg, ".n-prompt .pp-out-out", ".n-generator .pp-in-prompt")
        drag_wire(pg, ".n-reference .pp-out-out", ".n-generator .pp-in-style")
        check("протянуты 2 провода", pg.evaluate("window.GraphDev.state().edges.length === 2"))
        check("провода видны на канвасе", pg.evaluate("document.querySelectorAll('.react-flow__edge').length === 2"))
        edges_ok = pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const byType = (t) => st.nodes.find(n => n.type === t);
            const pr = byType('prompt'), ref = byType('reference'), g = byType('generator');
            const has = (fn, fp, tn, tp) => st.edges.some(e =>
                e.from.node === fn.id && e.from.port === fp && e.to.node === tn.id && e.to.port === tp);
            return has(pr, 'out', g, 'prompt') && has(ref, 'out', g, 'style');
        })()""")
        check("провода: prompt.out→generator.prompt и reference.out→generator.style", bool(edges_ok))

        # правило 3 (совпадение kind, nodes.js:1055-1058): text->ir отклоняется
        rejected = pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const pr = st.nodes.find(n => n.type === 'prompt');
            const ref = st.nodes.find(n => n.type === 'reference');
            return window.GraphDev.connect(pr.id, 'out', ref.id, 'ir') === false;
        })()""")
        check("правило kind: провод prompt.out→reference.ir отклонён", bool(rejected))
        check("лишний провод не создан", pg.evaluate("window.GraphDev.state().edges.length === 2"))

        # автосейв (debounce 300 мс) и перезагрузка — граф должен сохраниться
        pg.wait_for_timeout(600)
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.wait_for_selector(".n-prompt")
        pg.wait_for_selector(".n-generator")
        check("после перезагрузки: 3 ноды", pg.evaluate("window.GraphDev.state().nodes.length === 3"))
        check("после перезагрузки: 2 провода", pg.evaluate("window.GraphDev.state().edges.length === 2"))
        check(
            "после перезагрузки: текст Промпта на месте",
            pg.evaluate("document.querySelector('.n-prompt .f-text').value") == PROMPT_TEXT,
        )
        check(
            "сейв в отдельном ключе, legacy-граф не затронут",
            pg.evaluate(
                "localStorage.getItem('designai-flow-v1') !== null && "
                "localStorage.getItem('designai-graph-v1') === null"
            ),
        )

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
