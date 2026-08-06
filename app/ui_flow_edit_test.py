"""Playwright-тест GeoEdit + Inspector + IRHistory + Editor.open внутри ноды
«Редактор (DNA)» нового UI /flow (Спринт 5, Фаза B3).
Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_edit_test.py

БЕЗ реальных LLM-вызовов: IR кладётся в ноду через window.GraphDev.setIR.

Проверяет: IR рендерится в edit-ноде и уходит propagate-ом вниз по графу;
GeoEdit выделяет элемент кликом (рамка + чип), marquee работает; drag/resize
меняет геометрию IR (_frames по data-ir-path), мутация уходит в сейв
(localStorage designai-flow-v1) и в ноду ниже по проводу; инспектор показывает
выбранный элемент и реагирует на снятие выделения; Ctrl+Z/Ctrl+Y откатывает и
повторяет правку IR; «Открыть DNA-редактор» открывает полноэкранный редактор,
сохранение возвращает IR в ноду; Delete при выделенном элементе IR удаляет
элемент IR, но не ноду графа.
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"

# Валидный IR: секция cta (рендерится renderer.js без LLM). Высота корневого
# фрейма 800 даёт пустую зону артборда под секцией — для marquee и deselect.
SMALL_IR = {
    "frame": {"width": 960, "height": 800},
    "tokens": {"color": {"primary": "#5b5bd6", "background": "#ffffff"}},
    "tree": [
        {
            "id": "cta",
            "type": "cta",
            "variant": "centered",
            "props": {
                "heading": "Мок-заголовок B3",
                "subheading": "Тестовый IR без LLM",
                "ctaPrimary": {"text": "Кнопка", "variant": "primary"},
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


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})

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
        pg.wait_for_function(
            "window.IRRenderer && window.GeoEdit && window.Inspector && window.IRHistory && window.Editor"
        )
        check("legacy-глобалы подключены (renderer/geoedit/inspector/irhistory/editor)", True)

        # две edit-ноды: e1 получает IR, e2 — ниже по графу (проверка propagate)
        e1 = pg.evaluate("window.GraphDev.add('edit', 80, 60).id")
        e2 = pg.evaluate("window.GraphDev.add('edit', 950, 60).id")
        N1 = f'.react-flow__node[data-id="{e1}"]'
        pg.evaluate(f"window.GraphDev.connect({e1}, 'ir', {e2}, 'ir')")
        pg.evaluate(f"window.GraphDev.setIR({e1}, {json.dumps(SMALL_IR)})")

        pg.wait_for_selector(f'{N1} .f-preview .ir-preview-inner div[class^="ir-"]', timeout=5000)
        check("Edit: IR отрендерился в ноде (f-preview/ir-preview-inner — совместимо с B2)", True)
        check(
            "Edit: propagate положил клон IR в ноду ниже по проводу",
            pg.evaluate(f"!!window.GraphDev.node({e2}).data.ir"),
        )

        def heading_frames():
            return pg.evaluate(
                f"(() => {{ const d = window.GraphDev.node({e1}).data;"
                " return (d.ir.tree[0]._frames || {})['props.heading'] || null; })()"
            )

        # выделить ноду в графе (клик по шапке) — нужно для Ctrl+Z/Ctrl+Y
        pg.click(f"{N1} .node-head")
        check(
            "Edit: клик по шапке выделяет ноду в графе",
            bool(pg.wait_for_selector(f"{N1}.selected", timeout=2000)),
        )

        # клик по элементу IR — GeoEdit выделяет его (рамка + чип)
        heading = pg.wait_for_selector(f'{N1} .f-preview [data-ir-path="props.heading"]')
        hx, hy = center(heading.bounding_box())
        pg.mouse.click(hx, hy)
        pg.wait_for_selector(f"{N1} .geo-overlay .geo-box.selected", timeout=3000)
        check("GeoEdit: клик выделил элемент (рамка .geo-box.selected)", True)
        chip = pg.text_content(f"{N1} .geo-overlay .geo-chip")
        check("GeoEdit: чип выделения с подписью", bool(chip and chip.strip()))
        sel_label = (pg.text_content(f"{N1} .geo-tools .sel-label") or "").strip()
        check("GeoEdit: sel-label показал выделение", bool(sel_label) and sel_label != "—")

        # инспектор показывает выбранный элемент
        check(
            "Inspector: показывает выбранный элемент (pi-type = sel-label)",
            (pg.text_content(f"{N1} .edit-inspector .pi-type") or "").strip() == sel_label,
        )
        check(
            "Inspector: поля X/Y доступны для не-корня",
            pg.locator(f'{N1} .edit-inspector input[data-pi="x"]').count() == 1
            and not pg.locator(f'{N1} .edit-inspector input[data-pi="x"]').is_disabled(),
        )

        # клик по пустой зоне артборда — снятие выделения, инспектор пустеет
        inner_box = pg.locator(f"{N1} .edit-inner").bounding_box()
        sec_box = pg.locator(f'{N1} .f-preview [data-ir-sec="0"]').bounding_box()
        empty_y = min(sec_box["y"] + sec_box["height"] + 40, inner_box["y"] + inner_box["height"] - 10)
        pg.mouse.click(inner_box["x"] + 40, empty_y)
        pg.wait_for_selector(f"{N1} .edit-inspector .pi-empty", timeout=3000)
        check("Inspector: реагирует на снятие выделения (pi-empty)", True)

        # drag заголовка: геометрия уходит в _frames по data-ir-path
        pg.mouse.click(hx, hy)
        pg.wait_for_selector(f"{N1} .geo-overlay .geo-box.selected", timeout=3000)
        pg.mouse.move(hx, hy)
        pg.mouse.down()
        pg.mouse.move(hx + 40, hy + 25, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(250)
        fr = heading_frames()
        check(
            "GeoEdit: drag элемента изменил геометрию IR (_frames props.heading x/y)",
            bool(fr) and isinstance(fr.get("x"), (int, float)) and isinstance(fr.get("y"), (int, float)),
            extra=f"frames={fr}",
        )

        # resize за правый-нижний хендл
        hse = pg.wait_for_selector(f"{N1} .geo-overlay .geo-h.h-se", timeout=3000)
        sx, sy = center(hse.bounding_box())
        w0, h0 = (fr or {}).get("width", 0), (fr or {}).get("height", 0)
        pg.mouse.move(sx, sy)
        pg.mouse.down()
        pg.mouse.move(sx + 20, sy + 15, steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(250)
        fr2 = heading_frames()
        check(
            "GeoEdit: resize изменил width/height в IR",
            bool(fr2)
            and isinstance(fr2.get("width"), (int, float))
            and fr2["width"] > w0
            and fr2["height"] > h0,
            extra=f"frames={fr2} (до w0={w0}, h0={h0})",
        )

        # стрелки: двигают элемент IR, но НЕ ноду графа (развязка с RF)
        def node_x():
            return pg.evaluate(
                f"window.GraphDev.state().nodes.find(n => n.id === {e1}).x"
            )

        pg.click(f"{N1} .node-head")  # фокус/выделение на ноде графа
        nx0 = node_x()
        fr_pre = heading_frames() or {}
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(200)
        fr_post = heading_frames() or {}
        check(
            "Стрелки: nudge двигает элемент IR (+1px по X)",
            fr_post.get("x") == (fr_pre.get("x") or 0) + 1,
            extra=f"pre={fr_pre} post={fr_post}",
        )
        check("Стрелки: нода графа не сдвинулась", node_x() == nx0)
        fr2 = fr_post

        # мутация ушла в сейв (debounce 300 мс) и propagate-ом в e2
        pg.wait_for_timeout(700)
        saved = pg.evaluate(
            """(() => {
                const raw = localStorage.getItem('designai-flow-v1');
                if (!raw) return null;
                const g = JSON.parse(raw);
                const n = g.nodes.find(x => x.id === %d);
                return n && n.data.ir ? (n.data.ir.tree[0]._frames || {})['props.heading'] || null : null;
            })()"""
            % e1
        )
        check(
            "Сейв: мутация геометрии в localStorage designai-flow-v1",
            bool(saved) and isinstance(saved.get("x"), (int, float)),
            extra=f"saved={saved}",
        )
        check(
            "Сейв: runtime-поля (geo/history/editZoom) не попали в data",
            pg.evaluate(
                f"""(() => {{
                    const g = JSON.parse(localStorage.getItem('designai-flow-v1'));
                    const n = g.nodes.find(x => x.id === {e1});
                    return n && !('geo' in n) && !('history' in n) && !('editZoom' in n)
                        && !('geo' in n.data) && !('history' in n.data) && !('editZoom' in n.data);
                }})()"""
            ),
        )
        expected_x = (fr2 or {}).get("x")
        check(
            "Propagate: мутация дошла до ноды ниже по проводу",
            expected_x is not None
            and pg.evaluate(
                f"""(() => {{
                    const d = window.GraphDev.node({e2}).data;
                    const f = ((d.ir.tree[0] || {{}})._frames || {{}})['props.heading'];
                    return !!f && f.x === {expected_x};
                }})()"""
            ),
        )

        # Ctrl+Z откатывает правку до исходного IR, Ctrl+Y повторяет
        for _ in range(6):
            if heading_frames() is None:
                break
            pg.keyboard.press("Control+z")
            pg.wait_for_timeout(150)
        check("Ctrl+Z: откатил правку IR к исходному состоянию", heading_frames() is None)
        pg.keyboard.press("Control+y")
        pg.wait_for_timeout(250)
        check("Ctrl+Y: повторил правку IR", heading_frames() is not None)

        # «Открыть DNA-редактор» → полноэкранный редактор → сохранение возвращает IR
        pg.click(f"{N1} .f-open-editor")
        pg.wait_for_selector('.dna-editor .fe-canvas-inner div[class^="ir-"]', timeout=5000)
        check(
            "DNA-редактор: открылся (превью в fe-canvas-inner)",
            pg.evaluate("document.querySelector('.dna-editor').style.display !== 'none'"),
        )
        pg.click('.dna-editor [data-act="save"]')
        pg.wait_for_timeout(300)
        check(
            "DNA-редактор: сохранение закрыло редактор",
            pg.evaluate("document.querySelector('.dna-editor').style.display === 'none'"),
        )
        check(
            "DNA-редактор: тост «IR сохранён из редактора»",
            pg.evaluate(
                "[...document.querySelectorAll('#toasts .toast')]"
                ".some(t => t.textContent.includes('IR сохранён из редактора'))"
            ),
        )
        check(
            "DNA-редактор: IR остался в ноде",
            pg.evaluate(f"!!window.GraphDev.node({e1}).data.ir"),
        )

        # Delete при выделенном элементе IR: удаляет IR, не ноду графа.
        # Выделение — marquee по диагонали артборда (старт в пустой зоне под секцией)
        pg.mouse.move(inner_box["x"] + 10, inner_box["y"] + inner_box["height"] - 8)
        pg.mouse.down()
        pg.mouse.move(inner_box["x"] + inner_box["width"] - 8, inner_box["y"] + 10, steps=12)
        marquee_seen = pg.locator(f"{N1} .geo-overlay .geo-marquee").count() > 0
        pg.mouse.up()
        check("GeoEdit: marquee рисуется при протяжке", marquee_seen)
        try:
            pg.wait_for_selector(f"{N1} .geo-overlay .geo-box.selected", timeout=3000)
            marquee_sel = True
        except Exception:
            marquee_sel = False
        check("GeoEdit: marquee выделил секцию", marquee_sel)

        nodes_before = pg.evaluate("window.GraphDev.state().nodes.length")
        pg.keyboard.press("Delete")
        pg.wait_for_timeout(300)
        check(
            "Delete: секция удалена из IR",
            pg.evaluate(f"window.GraphDev.node({e1}).data.ir.tree.length === 0"),
        )
        check(
            "Delete: нода графа НЕ удалена",
            pg.evaluate("window.GraphDev.state().nodes.length") == nodes_before,
        )

        browser.close()

    if FAILS:
        print(f"\nFAIL: {len(FAILS)} — {', '.join(FAILS)}")
        sys.exit(1)
    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
