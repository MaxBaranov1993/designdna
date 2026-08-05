"""Playwright-тест run-based нод React Flow-редактора (Спринт 5, Фаза B2).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_nodes_test.py

БЕЗ реальных LLM-вызовов: POST /api/generate, /api/mix, /api/clone, /api/reproduce
перехватываются через page.route и возвращают маленький валидный IR.

Проверяет: создание Генератора; провод Промпт->generator.prompt; клик
«Сгенерировать» -> спиннер -> превью; ir дошёл до превью Edit-ноды ниже по графу;
payload-ы legacy-формы ({brief,count,provider,styleHint} / {irs,weights} /
{url,component,provider} / {image,url,provider}); run Клона, Микса и Reproduce;
после перезагрузки граф сохранён.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
PROMPT_TEXT = "Сгенерируй шапку маркетплейса объявлений"
CLONE_URL = "https://example.com/page"
REPRO_URL = "https://example.com/repro"

# Маленький валидный IR: секция cta — рендерится renderer.js без LLM
SMALL_IR = {
    "frame": {"width": 960},
    "tokens": {"color": {"primary": "#5b5bd6", "background": "#ffffff"}},
    "tree": [
        {
            "id": "cta",
            "type": "cta",
            "variant": "centered",
            "props": {
                "heading": "Мок-заголовок",
                "subheading": "Тестовый IR без LLM",
                "ctaPrimary": {"text": "Кнопка", "variant": "primary"},
            },
        }
    ],
}

FAILS = []
CAPTURED = {}


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


# ---------- перехват API: никаких реальных LLM-вызовов ----------

def route_generate(route):
    CAPTURED["generate"] = route.request.post_data_json
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"variants": [SMALL_IR], "errors": []}),
    )


def route_mix(route):
    CAPTURED["mix"] = route.request.post_data_json
    route.fulfill(status=200, content_type="application/json", body=json.dumps({"ir": SMALL_IR}))


def route_clone(route):
    CAPTURED["clone"] = route.request.post_data_json
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"ir": SMALL_IR, "cached": False}),
    )


def route_reproduce(route):
    CAPTURED["reproduce"] = route.request.post_data_json
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "ir": SMALL_IR,
                "html": "<div>mock</div>",
                "diff": {"overall_pct": 2.5, "mean_rgb": [1.1, 2.2, 3.3]},
                "colors": {"colors": {"primary": {"hex": "#5b5bd6", "pixels": 100}}},
                "repro_png": "",
                "icons_count": 1,
                "cached": False,
                "provider_used": "mock",
            }
        ),
    )


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        pg.route("**/api/generate", route_generate)
        pg.route("**/api/mix", route_mix)
        pg.route("**/api/clone", route_clone)
        pg.route("**/api/reproduce", route_reproduce)

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

        # создание Генератора через контекстное меню (правый клик по канвасу)
        pg.click(".react-flow__pane", button="right", position={"x": 520, "y": 100})
        pg.click("#ctx-menu .ctx-item[data-type='generator']")
        pg.wait_for_selector(".n-generator")
        check("Генератор создан", pg.evaluate("window.GraphDev.state().nodes.some(n => n.type === 'generator')"))

        # остальные ноды — через GraphDev (создание уже покрыто тестом ui_flow_graph_test)
        pg.evaluate("""(() => {
            window.GraphDev.add('prompt', 80, 60);
            window.GraphDev.add('edit', 830, 60);
            window.GraphDev.add('clone', 80, 560);
            window.GraphDev.add('mix', 460, 560);
            window.GraphDev.add('reproduce', 840, 560);
        })()""")
        pg.wait_for_selector(".n-prompt")
        pg.wait_for_selector(".n-edit")
        pg.wait_for_selector(".n-clone")
        pg.wait_for_selector(".n-mix")
        pg.wait_for_selector(".n-reproduce")
        check("созданы 6 нод", pg.evaluate("window.GraphDev.state().nodes.length === 6"))

        # текст Промпта — источник брифа для генератора
        pg.fill(".n-prompt .f-text", PROMPT_TEXT)
        pg.wait_for_timeout(150)

        # провода: prompt.out→generator.prompt, generator.ir→edit.ir,
        # clone.ir→mix.a, generator.ir→mix.b
        drag_wire(pg, ".n-prompt .pp-out-out", ".n-generator .pp-in-prompt")
        drag_wire(pg, ".n-generator .pp-out-ir", ".n-edit .pp-in-ir")
        drag_wire(pg, ".n-clone .pp-out-ir", ".n-mix .pp-in-a")
        drag_wire(pg, ".n-generator .pp-out-ir", ".n-mix .pp-in-b")
        check("протянуты 4 провода", pg.evaluate("window.GraphDev.state().edges.length === 4"))
        edges_ok = pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const byType = (t) => st.nodes.find(n => n.type === t);
            const pr = byType('prompt'), g = byType('generator'), ed = byType('edit'),
                  cl = byType('clone'), mx = byType('mix');
            const has = (fn, fp, tn, tp) => st.edges.some(e =>
                e.from.node === fn.id && e.from.port === fp && e.to.node === tn.id && e.to.port === tp);
            return has(pr, 'out', g, 'prompt') && has(g, 'ir', ed, 'ir') &&
                   has(cl, 'ir', mx, 'a') && has(g, 'ir', mx, 'b');
        })()""")
        check("провода: prompt→генератор, генератор→редактор, клон→микс.a, генератор→микс.b", bool(edges_ok))

        # Клон: заполняем url + компонент, запускаем (перехваченный /api/clone)
        pg.fill(".n-clone .f-url", CLONE_URL)
        pg.fill(".n-clone .f-component", "шапка с навигацией")
        pg.click(".n-clone .f-run")
        pg.wait_for_selector('.n-clone .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Клон: превью появилось", True)
        check(
            "Клон: payload {url, component, provider}",
            CAPTURED.get("clone", {}).get("url") == CLONE_URL
            and CAPTURED.get("clone", {}).get("component") == "шапка с навигацией"
            and CAPTURED.get("clone", {}).get("provider") == "qwen",
        )

        # Генератор: задержка разрешения fetch внутри страницы, чтобы спиннер был виден
        pg.evaluate("""(() => {
            const orig = window.fetch;
            window.fetch = (url, opts) => {
                const p = orig(url, opts);
                if (String(url).includes('/api/generate')) {
                    return p.then(resp => new Promise(res => setTimeout(() => res(resp), 700)));
                }
                return p;
            };
        })()""")
        pg.click(".n-generator .f-run")
        try:
            pg.wait_for_selector(".n-generator .f-run .spinner", timeout=3000)
            spin_ok = True
        except Exception:
            spin_ok = False
        check("Генератор: спиннер виден во время запроса", spin_ok)
        pg.wait_for_selector('.n-generator .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Генератор: превью появилось после ответа", True)
        check(
            "Генератор: payload {brief, count, provider} — бриф из провода",
            CAPTURED.get("generate", {}).get("brief") == PROMPT_TEXT
            and CAPTURED.get("generate", {}).get("count") == 2
            and CAPTURED.get("generate", {}).get("provider") == "qwen",
        )
        check(
            "Генератор: variants записаны в data",
            pg.evaluate(
                "(() => { const g = window.GraphDev.state().nodes.find(n => n.type === 'generator');"
                " return window.GraphDev.node(g.id).data.variants.length === 1; })()"
            ),
        )

        # ir дошёл до превью Edit-ноды ниже по графу (propagate кладёт клон в data.ir)
        pg.wait_for_selector('.n-edit .f-preview .ir-preview-inner div[class^="ir-"]', timeout=5000)
        check("Edit: превью отрисовано из IR генератора", True)
        check(
            "Edit: data.ir — клон варианта генератора",
            pg.evaluate(
                "(() => { const ed = window.GraphDev.state().nodes.find(n => n.type === 'edit');"
                " const d = window.GraphDev.node(ed.id).data;"
                " return !!d.ir && Array.isArray(d.ir.tree) && d.ir.tree.length === 1; })()"
            ),
        )

        # Микс: два подключённых IR-входа (клон + генератор), веса 70/30
        pg.click(".n-mix .f-run")
        pg.wait_for_selector('.n-mix .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Микс: превью появилось", True)
        check(
            "Микс: payload {irs, weights} — 2 IR, веса нормированы",
            len(CAPTURED.get("mix", {}).get("irs", [])) == 2
            and len(CAPTURED.get("mix", {}).get("weights", [])) == 2
            and abs(sum(CAPTURED.get("mix", {}).get("weights", [0, 0])) - 1.0) < 1e-6,
        )

        # Reproduce: URL вместо скриншота
        pg.fill(".n-reproduce .f-url", REPRO_URL)
        pg.click(".n-reproduce .f-run")
        pg.wait_for_selector('.n-reproduce .f-preview .ir-preview-inner div[class^="ir-"]', timeout=8000)
        check("Reproduce: превью появилось", True)
        check(
            "Reproduce: payload {image:'', url, provider}",
            CAPTURED.get("reproduce", {}).get("url") == REPRO_URL
            and CAPTURED.get("reproduce", {}).get("image") == ""
            and CAPTURED.get("reproduce", {}).get("provider") == "qwen",
        )
        check(
            "Reproduce: result целиком в data, ir на выходе",
            pg.evaluate(
                "(() => { const r = window.GraphDev.state().nodes.find(n => n.type === 'reproduce');"
                " const d = window.GraphDev.node(r.id).data;"
                " return !!d.result && !!d.result.ir && d.result.diff.overall_pct === 2.5; })()"
            ),
        )

        # автосейв (debounce 300 мс) и перезагрузка — граф должен сохраниться
        pg.wait_for_timeout(700)
        pg.reload()
        pg.wait_for_selector(".react-flow__pane")
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        pg.wait_for_selector(".n-generator")
        check("после перезагрузки: 6 нод", pg.evaluate("window.GraphDev.state().nodes.length === 6"))
        check("после перезагрузки: 4 провода", pg.evaluate("window.GraphDev.state().edges.length === 4"))
        check(
            "после перезагрузки: variants генератора на месте",
            pg.evaluate(
                "(() => { const g = window.GraphDev.state().nodes.find(n => n.type === 'generator');"
                " return window.GraphDev.node(g.id).data.variants.length === 1; })()"
            ),
        )
        check(
            "после перезагрузки: ir редактора на месте",
            pg.evaluate(
                "(() => { const ed = window.GraphDev.state().nodes.find(n => n.type === 'edit');"
                " return !!window.GraphDev.node(ed.id).data.ir; })()"
            ),
        )
        check(
            "после перезагрузки: превью редактора снова отрисовано",
            bool(
                pg.wait_for_selector(
                    '.n-edit .f-preview .ir-preview-inner div[class^="ir-"]', timeout=5000
                )
            ),
        )

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
