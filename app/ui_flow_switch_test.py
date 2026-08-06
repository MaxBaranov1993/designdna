"""Playwright-тест маршрутов после снятия legacy /nodes (Спринт 5 закрыт).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_switch_test.py

Проверяет: GET / → 200 и новый UI (.react-flow__pane, шим window.GraphDev,
легаси-маркеры nodes.html отсутствуют); GET /flow → 200, поведение не
изменилось; GET /nodes → 307-редирект на / (legacy-граф снят, nodes.*
удалены): браузер и API-клиент приходят в новый UI, legacy-ключ
designai-graph-v1 больше не создаётся и designai-flow-v1 не трогается;
граф, созданный на `/`, виден после перезагрузки и разделяется с /flow
(ключ designai-flow-v1).
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"

FAILS = []


def check(name, cond, extra=""):
    tag = "OK " if cond else "FAIL"
    print(f"[{tag}] {name}" + ((" — " + extra) if (extra and not cond) else ""))
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


def no_legacy_markers(pg):
    return pg.evaluate(
        "!document.querySelector('#viewport') && !document.querySelector('#wires') && "
        "!document.querySelector('script[src*=\"nodes.js\"]') && "
        "document.title === 'DesignAI — нодовый редактор'"
    )


def main():
    with sync_playwright() as p:
        # доступность маршрутов страниц (API-клиент следует редиректам)
        api = p.request.new_context()
        for path in ("/", "/flow"):
            try:
                r = api.get(BASE + path)
                check(f"GET {path} -> 200", r.status == 200, str(r.status))
            except Exception as e:
                check(f"GET {path} -> 200", False, str(e))
        try:
            r = api.get(BASE + "/nodes")
            check("GET /nodes -> 200 (через редирект на /)", r.status == 200, str(r.status))
            check("GET /nodes: финальный URL — /", r.url.rstrip("/") == BASE, r.url)
        except Exception as e:
            check("GET /nodes -> 200 (через редирект на /)", False, str(e))
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
        check("на / нет легаси-маркеров nodes.html", no_legacy_markers(pg))

        # граф, созданный на `/`: автосейв в designai-flow-v1, legacy-ключ не трогается
        added = pg.evaluate("window.GraphDev.add('prompt', 140, 160)")
        check("на / создана нода (GraphDev.add работает)",
              bool(added) and isinstance(added.get("id"), int))
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

        # GET /nodes — legacy снят: редирект приводит в новый UI
        pg.goto(BASE + "/nodes")
        wait_flow_ready(pg)
        check("/nodes: браузер выведен на / (редирект)", pg.url.rstrip("/") == BASE, pg.url)
        check("/nodes: рендерится новый UI (.react-flow__pane)",
              pg.is_visible(".react-flow__pane"))
        check("/nodes: легаси-маркеров nodes.html нет", no_legacy_markers(pg))
        pg.wait_for_timeout(600)  # автосейв после loadGraph
        check("/nodes: legacy-ключ designai-graph-v1 не создаётся",
              pg.evaluate("localStorage.getItem('designai-graph-v1') === null"))
        check("/nodes: designai-flow-v1 не тронут",
              pg.evaluate("(v) => localStorage.getItem('designai-flow-v1') === v", flow_saved))

        # возврат на / — граф цел
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
