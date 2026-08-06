"""Playwright-тест переключения `/` на новый React Flow UI (Спринт 5, Фаза C).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_switch_test.py

Проверяет: GET / → 200 и новый UI (.react-flow__pane, шим window.GraphDev,
легаси-маркеры nodes.html отсутствуют); GET /nodes → 200 и legacy-редактор
nodes.js (топбар/#viewport/.node, number-id, без react-flow); GET /flow → 200,
поведение не изменилось; граф, созданный на `/`, виден после перезагрузки и
разделяется с /flow (ключ designai-flow-v1); legacy /nodes читает/пишет свой
designai-graph-v1 и не трогает flow-ключ (в обе стороны).
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def wait_flow_ready(pg):
    pg.wait_for_selector(".react-flow__pane")
    pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")


def one_prompt(pg):
    return pg.evaluate(
        "window.GraphDev.state().nodes.length === 1 && "
        "window.GraphDev.state().nodes[0].type === 'prompt'"
    )


def main():
    with sync_playwright() as p:
        # доступность маршрутов страниц
        api = p.request.new_context()
        for path in ("/", "/nodes", "/flow"):
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
                pg.goto(BASE + "/", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        pg.evaluate("localStorage.clear()")
        pg.reload()
        wait_flow_ready(pg)

        # GET / — новый UI (React Flow), легаси-маркеров nodes.html нет
        check("на / рендерится новый UI (.react-flow__pane)", pg.is_visible(".react-flow__pane"))
        check(
            "на / шим window.GraphDev (flow-версия)",
            pg.evaluate(
                "typeof window.GraphDev.add === 'function' && "
                "typeof window.GraphDev.state === 'function'"
            ),
        )
        check(
            "на / нет легаси-маркеров nodes.html",
            pg.evaluate(
                "!document.querySelector('#viewport') && !document.querySelector('#wires') && "
                "!document.querySelector('script[src*=\"nodes.js\"]') && "
                "document.title === 'DesignAI — нодовый редактор'"
            ),
        )

        # граф, созданный на `/`: автосейв в designai-flow-v1, legacy-ключ не трогается
        added = pg.evaluate("window.GraphDev.add('prompt', 140, 160)")
        check("на / создана нода с number-id", bool(added) and isinstance(added.get("id"), int))
        pg.wait_for_timeout(600)  # автосейв, debounce 300 мс (serialize.ts)
        check("автосейв: designai-flow-v1 записан",
              pg.evaluate("localStorage.getItem('designai-flow-v1') !== null"))
        check("автосейв: legacy-ключ designai-graph-v1 не создан",
              pg.evaluate("localStorage.getItem('designai-graph-v1') === null"))

        # перезагрузка `/` — граф на месте
        pg.reload()
        wait_flow_ready(pg)
        check("после перезагрузки /: граф сохранён", one_prompt(pg))

        # тот же граф виден на /flow (общий ключ designai-flow-v1)
        pg.goto(BASE + "/flow")
        wait_flow_ready(pg)
        check("/flow видит тот же граф (общий ключ designai-flow-v1)", one_prompt(pg))
        flow_saved = pg.evaluate("localStorage.getItem('designai-flow-v1')")

        # GET /nodes — legacy-редактор из nodes.js без изменений
        pg.goto(BASE + "/nodes")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        check("legacy: топбар и холст #viewport на месте",
              pg.evaluate("!!document.querySelector('.topbar') && !!document.querySelector('#viewport')"))
        check("legacy: .react-flow__pane отсутствует",
              pg.evaluate("!document.querySelector('.react-flow__pane')"))
        check("legacy: GraphDev c number-id (nodes.js)",
              pg.evaluate("typeof window.GraphDev.add('prompt', 120, 120).id === 'number'"))
        check("legacy: нода отрисована на холсте",
              pg.evaluate("document.querySelectorAll('#world .node').length === 1"))
        pg.wait_for_timeout(600)  # автосейв, debounce 300 мс (nodes.js:1175)
        check("legacy: пишет свой ключ designai-graph-v1",
              pg.evaluate("localStorage.getItem('designai-graph-v1') !== null"))
        check("legacy: не трогает designai-flow-v1",
              pg.evaluate("(v) => localStorage.getItem('designai-flow-v1') === v", flow_saved))

        # в обе стороны: после legacy `/` новый UI на `/` с тем же графом
        pg.goto(BASE + "/")
        wait_flow_ready(pg)
        check("после /nodes граф на / не тронут", one_prompt(pg))

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
