"""Playwright-тест ядра нодового редактора на React Flow (Спринт 5, Фаза B1).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_graph_test.py

Проверяет: маршрут /flow; правый клик по канвасу — контекстное меню;
создание нод Промпт/Референс/Генератор; ввод текста в Промпт; провода мышью
prompt.out -> generator.prompt и reference.out -> generator.style (оба text->text,
валидны по правилам legacy connect); после перезагрузки граф сохранён.
Провод prompt.out -> reference.ir отклоняется (правило совпадения kind).
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
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
        for path in ("/flow",):
            try:
                r = api.get(BASE + path)
                check(f"GET {path} -> 200", r.status == 200, str(r.status))
            except Exception as e:
                check(f"GET {path} -> 200", False, str(e))
        api.dispose()

        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 950})
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

        # правый клик по канвасу — контекстное меню создания ноды
        pg.click(".svelte-flow__pane", button="right", position={"x": 320, "y": 300})
        check("контекстное меню открыто", pg.is_visible("#ctx-menu"))
        # 14 типов: qualitypass/recorder/designui поддерживаются для legacy-графов,
        # но намеренно скрыты из палитры создания.
        check("в меню 14 типов нод", pg.evaluate("document.querySelectorAll('#ctx-menu .ctx-item').length === 14"))
        check("в меню есть Page Bridge", pg.evaluate("!!document.querySelector('#ctx-menu .ctx-item[data-type=\"pagebridge\"]')"))

        # создать Промпт
        pg.click("#ctx-menu .ctx-item[data-type='prompt']")
        pg.wait_for_selector(".n-prompt")
        check("меню закрылось после выбора", not pg.is_visible("#ctx-menu"))

        # Референс и Генератор — правее (с запасом: нода Референса ~300px высотой)
        pg.click(".svelte-flow__pane", button="right", position={"x": 700, "y": 180})
        pg.click("#ctx-menu .ctx-item[data-type='reference']")
        pg.wait_for_selector(".n-reference")
        pg.click(".svelte-flow__pane", button="right", position={"x": 760, "y": 620})
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
        check("провода видны на канвасе", pg.evaluate("document.querySelectorAll('.svelte-flow__edge').length === 2"))
        edges_ok = pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const byType = (t) => st.nodes.find(n => n.type === t);
            const pr = byType('prompt'), ref = byType('reference'), g = byType('generator');
            const has = (fn, fp, tn, tp) => st.edges.some(e =>
                e.from.node === fn.id && e.from.port === fp && e.to.node === tn.id && e.to.port === tp);
            return has(pr, 'out', g, 'prompt') && has(ref, 'out', g, 'style');
        })()""")
        check("провода: prompt.out->generator.prompt и reference.out->generator.style", bool(edges_ok))

        # Контекстное действие снимает только провода; нода и её data остаются.
        pg.click(".n-generator", button="right")
        pg.wait_for_selector("#node-ctx-menu")
        check("контекстное меню ноды показывает 2 связи",
              "2" in pg.locator("#node-ctx-menu .node-ctx-head small").inner_text())
        pg.click('#node-ctx-menu [data-act="disconnect-node"]')
        check("все связи генератора разорваны",
              pg.evaluate("window.GraphDev.state().edges.length === 0"))
        check("сама нода после разрыва сохранена",
              pg.evaluate("window.GraphDev.state().nodes.some(n => n.type === 'generator')"))
        pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const p = st.nodes.find(n => n.type === 'prompt');
            const r = st.nodes.find(n => n.type === 'reference');
            const g = st.nodes.find(n => n.type === 'generator');
            window.GraphDev.connect(p.id, 'out', g.id, 'prompt');
            window.GraphDev.connect(r.id, 'out', g.id, 'style');
        })()""")
        check("связи можно восстановить после разрыва",
              pg.evaluate("window.GraphDev.state().edges.length === 2"))

        # правило 3 (совпадение kind, nodes.js:1055-1058): text->ir отклоняется
        rejected = pg.evaluate("""(() => {
            const st = window.GraphDev.state();
            const pr = st.nodes.find(n => n.type === 'prompt');
            const ref = st.nodes.find(n => n.type === 'reference');
            return window.GraphDev.connect(pr.id, 'out', ref.id, 'ir') === false;
        })()""")
        check("правило kind: провод prompt.out->reference.ir отклонён", bool(rejected))
        check("лишний провод не создан", pg.evaluate("window.GraphDev.state().edges.length === 2"))

        # автосейв (debounce 300 мс + idle-слот до ~1.2 с) и перезагрузка — граф должен сохраниться
        pg.wait_for_timeout(2000)
        pg.reload()
        pg.wait_for_selector(".svelte-flow__pane")
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
            "сейв в pages-ключе, legacy-ключи не пишутся",
            pg.evaluate(
                "localStorage.getItem('designai-flow-pages-v1') !== null && "
                "localStorage.getItem('designai-flow-v1') === null && "
                "localStorage.getItem('designai-graph-v1') === null"
            ),
        )

        # Страницы: у каждой своё полотно, старый граф становится первой страницей.
        first_page = pg.evaluate("window.GraphDev.state().activePageId")
        pg.evaluate("window.GraphDev.createPage('Landing variants')")
        second_page = pg.evaluate("window.GraphDev.state().activePageId")
        check("создана вторая страница", pg.evaluate("window.GraphDev.pages().length === 2"))
        check("новая страница имеет пустое полотно", pg.evaluate("window.GraphDev.state().nodes.length === 0"))
        pg.evaluate("(id) => window.GraphDev.switchPage(id)", first_page)
        pg.wait_for_selector(".n-prompt")
        check("первая страница сохранила свои 3 ноды", pg.evaluate("window.GraphDev.state().nodes.length === 3"))
        pg.evaluate("(id) => window.GraphDev.switchPage(id)", second_page)
        check("вторая страница всё ещё пустая", pg.evaluate("window.GraphDev.state().nodes.length === 0"))

        # Page Bridge: send на одной странице, receive на другой с тем же каналом.
        pg.evaluate("(id) => window.GraphDev.switchPage(id)", first_page)
        edit_id = pg.evaluate("window.GraphDev.add('edit', 80, 420).id")
        send_id = pg.evaluate("window.GraphDev.add('pagebridge', 560, 420).id")
        check("создан Page Bridge send", pg.evaluate("window.GraphDev.state().nodes.some(n => n.type === 'pagebridge')"))
        pg.evaluate(
            """([editId, bridgeId]) => {
                window.GraphDev.setIR(editId, {tree:[{id:'hero', type:'section', props:{title:'Shared hero'}}]});
                window.GraphDev.patchData(bridgeId, {mode:'send', channel:'hero-share'});
                window.GraphDev.connect(editId, 'ir', bridgeId, 'ir');
                window.GraphDev.run(bridgeId);
            }""",
            [edit_id, send_id],
        )
        check("bridge записал канал", pg.evaluate("window.GraphDev.state().channels.includes('hero-share')"))
        pg.evaluate("(id) => window.GraphDev.switchPage(id)", second_page)
        receive_id = pg.evaluate("window.GraphDev.add('pagebridge', 120, 180).id")
        pg.evaluate(
            """(bridgeId) => {
                window.GraphDev.patchData(bridgeId, {mode:'receive', channel:'hero-share'});
                window.GraphDev.run(bridgeId);
            }""",
            receive_id,
        )
        check(
            "receive получил компонент с другой страницы",
            pg.evaluate(
                "(id) => window.GraphDev.node(id).data.ir.tree[0].props.title === 'Shared hero'",
                receive_id,
            ),
        )

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
