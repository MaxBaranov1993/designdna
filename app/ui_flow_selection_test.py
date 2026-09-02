"""Выделение нод на графовом канвасе и всё, что от него зависит.

Регрессия 2026-09-02: клик по ноде не давал ей класс selected (эффект
«стор → канвас» в FlowCanvas.svelte откатывал bind-массив раньше, чем
«канвас → стор» доносил выделение), поэтому Delete/Backspace и инспектор
графа были мертвы. Тест: клик → selected, инспектор показывает ноду,
Delete удаляет вместе с ребром, Ctrl+Z возвращает одним шагом, drag
сохраняет выделение.

Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_selection_test.py
"""
from __future__ import annotations

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK ] " if ok else "[FAIL] ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def counts(pg) -> tuple[int, int]:
    st = pg.evaluate("window.GraphDev.state()")
    return len(st["nodes"]), len(st["edges"])


def selected_ids(pg) -> list[str]:
    return [n["id"] for n in pg.evaluate("window.GraphDev.canvasNodes()") if n["selected"]]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 950})
        pg.route("**/api/project/load", lambda r: r.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null,"revision":"r1"}'))
        pg.route("**/api/project/save", lambda r: r.fulfill(
            status=200, content_type="application/json", body='{"ok":true,"revision":"r2"}'))
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
        pg.wait_for_function("window.GraphDev && typeof window.GraphDev.canvasNodes === 'function'")
        pg.evaluate("window.GraphDev.clear()")
        pg.wait_for_timeout(200)

        prompt_id = pg.evaluate("window.GraphDev.add('prompt', 120, 120).id")
        gen_id = pg.evaluate("window.GraphDev.add('generator', 560, 120).id")
        gen_sel = f'.svelte-flow__node[data-id="{gen_id}"]'
        pg.wait_for_selector(gen_sel)
        pg.evaluate("(v) => window.GraphDev.connect(v.a, 'out', v.b, 'prompt')", {"a": prompt_id, "b": gen_id})
        pg.wait_for_timeout(300)
        check("исходный граф: 2 ноды, 1 ребро", counts(pg) == (2, 1), str(counts(pg)))

        # ---------- клик выделяет ----------
        pg.click(gen_sel + " .node-head")
        pg.wait_for_timeout(250)
        check("клик по ноде даёт класс selected", pg.evaluate(f"document.querySelector('{gen_sel}').classList.contains('selected')"))
        check("Svelte Flow видит ноду выделенной", selected_ids(pg) == [str(gen_id)], str(selected_ids(pg)))
        check("стор получил selected", pg.evaluate(
            f"!!window.__flowStore.getState().nodes.find(n => n.id === '{gen_id}')?.selected"))
        check("инспектор показывает выделенную ноду", "Генератор" in pg.locator(".dna-insp .dna-insp-title strong").inner_text())

        # клик по другой ноде переключает выделение
        pg.click(f'.svelte-flow__node[data-id="{prompt_id}"] .node-head')
        pg.wait_for_timeout(250)
        check("клик по другой ноде переносит выделение", selected_ids(pg) == [str(prompt_id)], str(selected_ids(pg)))

        # ---------- drag сохраняет выделение ----------
        box = pg.locator(gen_sel + " .node-head").bounding_box()
        pg.mouse.move(box["x"] + 40, box["y"] + 10)
        pg.mouse.down()
        pg.mouse.move(box["x"] + 140, box["y"] + 90, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(350)
        moved = pg.evaluate("(id) => window.GraphDev.node(id)", gen_id)
        check("drag сдвинул ноду в сторе", moved["x"] > 560 and moved["y"] > 120, str((moved["x"], moved["y"])))
        check("после drag нода остаётся выделенной", selected_ids(pg) == [str(gen_id)], str(selected_ids(pg)))

        # ---------- Delete удаляет выделенную ноду с ребром, Ctrl+Z возвращает ----------
        pg.keyboard.press("Delete")
        pg.wait_for_timeout(300)
        check("Delete удалил выделенную ноду и её ребро", counts(pg) == (1, 0), str(counts(pg)))
        check("тост предлагает вернуть", pg.locator("#toasts .toast", has_text="Нода удалена").count() == 1)
        pg.locator("body").focus()
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        check("Ctrl+Z вернул ноду и ребро одним шагом", counts(pg) == (2, 1), str(counts(pg)))
        check("восстановленное ребро видно на канвасе", pg.evaluate("document.querySelectorAll('.svelte-flow__edge').length") == 1)

        # Backspace — тот же путь
        pg.click(gen_sel + " .node-head")
        pg.wait_for_timeout(250)
        pg.keyboard.press("Backspace")
        pg.wait_for_timeout(300)
        check("Backspace тоже удаляет выделенную ноду", counts(pg) == (1, 0), str(counts(pg)))
        pg.locator("body").focus()
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(300)
        check("undo после Backspace", counts(pg) == (2, 1), str(counts(pg)))

        # клик по пустому месту снимает выделение
        pg.click(gen_sel + " .node-head")
        pg.wait_for_timeout(200)
        pane = pg.locator(".svelte-flow__pane").bounding_box()
        pg.mouse.click(pane["x"] + 80, pane["y"] + pane["height"] - 80)  # пустой угол пейна, не инспектор
        pg.wait_for_timeout(250)
        check("клик по пейну снимает выделение", selected_ids(pg) == [], str(selected_ids(pg)))

        browser.close()

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("ALL SELECTION CHECKS PASSED")


if __name__ == "__main__":
    main()
