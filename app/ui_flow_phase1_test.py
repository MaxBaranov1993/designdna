"""Playwright-тест «быстрых побед» фазы 1 (docs/IMPROVEMENT-PLAN.md):
undo/redo графа, тост с действием «Вернуть», защита черновика DNA-редактора,
диалог разрешения конфликта автосейва (409), честный прогресс без процентов.

Нужен запущенный сервер: .venv/Scripts/python app/server.py (порт 8420)
Запуск: .venv/Scripts/python app/ui_flow_phase1_test.py
"""
from __future__ import annotations

import json
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


def document(text: str, gap: int = 13) -> dict:
    return {
        "version": "1.1",
        "tokens": {"color": {"background": "#fff", "text": "#111", "primary": "#4f46e5"}},
        "frame": {"width": 1200, "layout": "auto", "direction": "column"},
        "tree": [{
            "id": "hero", "type": "hero", "variant": "default",
            "frame": {"width": "fill", "layout": "auto", "direction": "column", "gap": gap},
            "children": [{"type": "text", "text": text, "frame": {"width": 300, "height": 40}}],
        }],
    }


DB_PROJECT = {
    "version": "designai-pages-v1",
    "activePageId": "page-1",
    "pages": [{
        "id": "page-1", "name": "Page 1",
        "graph": {
            "nodes": [{"id": 1, "type": "prompt", "x": 120, "y": 120, "data": {"text": "версия из базы"}}],
            "edges": [], "view": {"x": 0, "y": 0, "zoom": 1}, "nextId": 2,
        },
    }],
    "channels": {},
}


def graph_counts(pg) -> tuple[int, int]:
    st = pg.evaluate("window.GraphDev.state()")
    return len(st["nodes"]), len(st["edges"])


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1600, "height": 950})

        # Сценарий сейва управляется тестом: сначала всё ок, потом один 409.
        save_mode = {"value": "ok", "requests": []}
        load_mode = {"value": "empty"}

        def on_save(route):
            body = json.loads(route.request.post_data or "{}")
            save_mode["requests"].append(body.get("expectedRevision"))
            if save_mode["value"] == "conflict":
                save_mode["value"] = "ok"
                route.fulfill(status=409, content_type="application/json",
                              body='{"ok":false,"stale":true,"revision":"srv-2"}')
                return
            route.fulfill(status=200, content_type="application/json", body='{"ok":true,"revision":"srv-3"}')

        def on_load(route):
            if load_mode["value"] == "project":
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"project": DB_PROJECT, "updated_at": "now", "revision": "srv-2"}))
                return
            route.fulfill(status=200, content_type="application/json",
                          body='{"project":null,"updated_at":null,"revision":"srv-1"}')

        pg.route("**/api/project/load", on_load)
        pg.route("**/api/project/save", on_save)
        pg.route("**/api/quality-gate", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({
                "passed": False,
                "violations": [{"rule": "grid-8", "path": "tree.0.frame.gap", "severity": "minor"}],
                "fixed_ir": document("Original", 16),
                "journal": [{"path": "tree.0.frame.gap", "from": 13, "to": 16}],
            }),
        ))
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
        pg.wait_for_function("window.GraphDev && window.DNAEditor && typeof window.GraphDev.add === 'function'")
        pg.evaluate("window.GraphDev.clear()")
        pg.wait_for_timeout(200)

        # ---------- 1. undo/redo графа ----------
        check("после clear кнопка Undo неактивна", pg.locator("#btn-undo").is_disabled())
        prompt_id = pg.evaluate("window.GraphDev.add('prompt', 120, 120).id")
        gen_id = pg.evaluate("window.GraphDev.add('generator', 560, 120).id")
        pg.wait_for_selector(f'.svelte-flow__node[data-id="{gen_id}"]')
        check("connect prompt.out → generator.prompt",
              pg.evaluate("(v) => window.GraphDev.connect(v.a, 'out', v.b, 'prompt')", {"a": prompt_id, "b": gen_id}))
        check("граф: 2 ноды, 1 ребро", graph_counts(pg) == (2, 1), str(graph_counts(pg)))
        check("после изменений Undo активна", pg.locator("#btn-undo").is_enabled())

        # удаление крестиком на ноде — обратимо, тост предлагает «Вернуть»
        pg.click(f'.svelte-flow__node[data-id="{gen_id}"] .n-x')
        pg.wait_for_timeout(150)
        check("нода удалена вместе с ребром", graph_counts(pg) == (1, 0), str(graph_counts(pg)))
        toast = pg.locator("#toasts .toast", has_text="Нода удалена")
        check("тост об удалении показан", toast.count() == 1)
        check("у тоста есть кнопка «Вернуть»", toast.locator(".toast-action", has_text="Вернуть").count() == 1)
        check("у тоста есть кнопка закрытия", toast.locator(".toast-close").count() == 1)
        toast.locator(".toast-action").click()
        pg.wait_for_timeout(200)
        check("«Вернуть» восстановил ноду и ребро", graph_counts(pg) == (2, 1), str(graph_counts(pg)))
        check("восстановленное ребро видно на канвасе", pg.evaluate("document.querySelectorAll('.svelte-flow__edge').length") == 1)

        # клавиатура: Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z на канвасе
        pg.click(f'.svelte-flow__node[data-id="{gen_id}"] .n-x')
        pg.wait_for_timeout(150)
        pg.locator("body").focus()
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(200)
        check("Ctrl+Z вернул удалённую ноду", graph_counts(pg) == (2, 1), str(graph_counts(pg)))
        pg.keyboard.press("Control+y")
        pg.wait_for_timeout(200)
        check("Ctrl+Y повторил удаление", graph_counts(pg) == (1, 0), str(graph_counts(pg)))
        check("Redo после Ctrl+Y неактивна", pg.locator("#btn-redo").is_disabled())
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(200)
        check("Ctrl+Z после redo снова вернул", graph_counts(pg) == (2, 1), str(graph_counts(pg)))
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_timeout(200)
        check("Ctrl+Shift+Z = redo (удаление повторено)", graph_counts(pg) == (1, 0), str(graph_counts(pg)))
        pg.locator("#btn-undo").click()
        pg.wait_for_timeout(200)
        check("кнопка Undo в тулбаре вернула ноду", graph_counts(pg) == (2, 1), str(graph_counts(pg)))
        check("Redo активна, пока есть что повторить", pg.locator("#btn-redo").is_enabled())

        # Путь Del/Backspace (клик → selected → Svelte Flow → syncFromCanvas →
        # undo) проверяется отдельно в app/ui_flow_selection_test.py.

        # Ctrl+Z в поле ввода — нативный undo текста, граф не трогаем
        pg.fill(".n-prompt .f-text", "текст промпта")
        pg.locator(".n-prompt .f-text").press("Control+z")
        pg.wait_for_timeout(150)
        check("Ctrl+Z в textarea не откатывает граф", graph_counts(pg) == (2, 1), str(graph_counts(pg)))
        pg.locator("body").focus()

        # ---------- 2. защита черновика DNA-редактора ----------
        edit_id = pg.evaluate("window.GraphDev.add('edit', 120, 480).id")
        pg.wait_for_selector(f'.svelte-flow__node[data-id="{edit_id}"]')
        pg.wait_for_timeout(150)
        pg.evaluate("(v) => window.GraphDev.patchData(v.id, {ir: v.ir})", {"id": edit_id, "ir": document("Original")})
        pg.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        pg.wait_for_function("window.DNAEditor.isOpen()")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check("чистая сессия: Esc закрывает без вопросов", not pg.evaluate("window.DNAEditor.isOpen()"))
        check("диалог подтверждения не показан", pg.locator("[data-close-confirm]").count() == 0)

        pg.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        pg.wait_for_function("window.DNAEditor.isOpen()")
        pg.click('[data-act="quality-gate"]')
        pg.wait_for_selector('[data-act="apply-quality-fixes"]')
        pg.click('[data-act="apply-quality-fixes"]')
        pg.wait_for_function("id => window.GraphDev.node(id).data._editorDraft?.ir?.tree?.[0]?.frame?.gap === 16", arg=edit_id)
        pg.keyboard.press("Escape")
        pg.wait_for_selector("[data-close-confirm]", timeout=3000)
        check("грязная сессия: Esc показывает диалог", pg.locator("[data-close-confirm]").count() == 1)
        check("редактор остаётся открытым", pg.evaluate("window.DNAEditor.isOpen()"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check("Esc в диалоге = «Остаться»", pg.locator("[data-close-confirm]").count() == 0 and pg.evaluate("window.DNAEditor.isOpen()"))

        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_selector("[data-close-confirm]", timeout=3000)
        pg.click('[data-act="close-stay"]')
        pg.wait_for_timeout(150)
        check("«Остаться» держит редактор открытым", pg.evaluate("window.DNAEditor.isOpen()"))
        check("черновик после «Остаться» цел", pg.evaluate(
            "id => window.GraphDev.node(id).data._editorDraft?.ir?.tree?.[0]?.frame?.gap === 16", edit_id))

        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_selector("[data-close-confirm]", timeout=3000)
        pg.click('[data-act="close-save"]')
        pg.wait_for_function("!window.DNAEditor.isOpen()")
        check("«Сохранить и закрыть» записал правки в ноду", pg.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].frame.gap === 16", edit_id))
        check("черновик после сохранения снят", pg.evaluate("id => !window.GraphDev.node(id).data._editorDraft", edit_id))

        # IR обратно к gap 13, чтобы quality-fix (gap 16) снова был реальной правкой
        pg.evaluate("(v) => window.GraphDev.patchData(v.id, {ir: v.ir})", {"id": edit_id, "ir": document("Original")})
        pg.wait_for_timeout(150)
        pg.click(f'.svelte-flow__node[data-id="{edit_id}"] .f-open-editor')
        pg.wait_for_function("window.DNAEditor.isOpen()")
        pg.click('[data-act="quality-gate"]')
        pg.wait_for_selector('[data-act="apply-quality-fixes"]')
        pg.click('[data-act="apply-quality-fixes"]')
        pg.wait_for_function("id => window.GraphDev.node(id).data._editorDraft?.ir?.tree?.[0]?.frame?.gap === 16", arg=edit_id)
        pg.click('.dna-editor [data-act="close"]')
        pg.wait_for_selector("[data-close-confirm]", timeout=3000)
        pg.click('[data-act="close-discard"]')
        pg.wait_for_function("!window.DNAEditor.isOpen()")
        check("«Не сохранять» закрыл редактор", not pg.evaluate("window.DNAEditor.isOpen()"))
        check("«Не сохранять» не тронул IR ноды и снял черновик", pg.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].frame.gap === 13 && !window.GraphDev.node(id).data._editorDraft", edit_id))

        # ---------- 3. конфликт автосейва (409) ----------
        pg.wait_for_timeout(900)  # дожать текущие сейвы, чтобы 409 пришёл на наш шаг
        save_mode["requests"].clear()
        save_mode["value"] = "conflict"
        pg.evaluate("window.GraphDev.add('reference', 900, 480)")
        pg.wait_for_selector("[data-project-conflict]", timeout=8000)
        check("409 показывает диалог конфликта", pg.locator("[data-project-conflict]").count() == 1)
        check("конфликтный сейв шёл с CAS-ревизией", save_mode["requests"][0] in ("srv-1", "srv-3"), str(save_mode["requests"]))
        pg.locator("[data-project-conflict] button", has_text="Оставить мои правки").click()
        pg.wait_for_function("!document.querySelector('[data-project-conflict]')", timeout=8000)
        check("«Оставить мои правки» закрыл диалог", pg.locator("[data-project-conflict]").count() == 0)
        check("повторный сейв ушёл с серверной ревизией", save_mode["requests"][-1] == "srv-2", str(save_mode["requests"]))
        check("тост об успешной записи", pg.locator("#toasts .toast", has_text="записана в базу").count() == 1)

        # «Загрузить их версию» — проект целиком заменяется серверным
        pg.wait_for_timeout(900)
        save_mode["value"] = "conflict"
        load_mode["value"] = "project"
        pg.evaluate("window.GraphDev.add('reference', 900, 760)")
        pg.wait_for_selector("[data-project-conflict]", timeout=8000)
        pg.locator("[data-project-conflict] button", has_text="Загрузить их версию").click()
        pg.wait_for_function("!document.querySelector('[data-project-conflict]')", timeout=8000)
        pg.wait_for_timeout(300)
        st = pg.evaluate("window.GraphDev.state()")
        check("«Загрузить их версию» заменил граф серверным",
              len(st["nodes"]) == 1 and st["nodes"][0]["type"] == "prompt", str(st["nodes"]))
        check("текст ноды из базы", pg.evaluate("window.GraphDev.node(1).data.text") == "версия из базы")
        check("Undo после замены проекта сброшен", pg.locator("#btn-undo").is_disabled())

        # ---------- 4. честный прогресс: без измеренного процента — indeterminate ----------
        pg.evaluate("window.__flowStore.getState().setProgress(1, {expectedMs: 90000, label: 'Генерация', stage: 'Модель генерирует IR'})")
        pg.wait_for_selector(".n-progress", timeout=3000)
        bar = pg.locator(".n-progress").first
        check("прогресс без percent — indeterminate", "indeterminate" in (bar.get_attribute("class") or ""))
        check("процент не рисуется", "%" not in bar.locator(".n-progress-caption").inner_text())
        check("стадия видна", "Модель генерирует IR" in bar.locator(".n-progress-label").inner_text())
        check("нет aria-valuenow у indeterminate", bar.get_attribute("aria-valuenow") is None)
        pg.evaluate("window.__flowStore.getState().setProgress(1, {expectedMs: 90000, label: 'Импорт', percent: 42})")
        pg.wait_for_timeout(100)
        check("измеренный процент показывается", "42%" in bar.locator(".n-progress-caption").inner_text())
        check("measured — не indeterminate", "indeterminate" not in (bar.get_attribute("class") or ""))
        pg.evaluate("window.__flowStore.getState().setProgress(1, null)")

        browser.close()

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("ALL PHASE 1 CHECKS PASSED")


if __name__ == "__main__":
    main()
