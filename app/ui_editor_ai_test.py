"""UI smoke-тест AI-first Edit Node: Preview → Apply → Undo.

Маршрут assist замокан, поэтому тест не тратит внешний LLM-бюджет.
Запуск: .venv/Scripts/python app/ui_editor_ai_test.py
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8420"
ROOT = pathlib.Path(__file__).resolve().parent.parent
IR_PATH = ROOT / "app" / "fixtures" / "frame-example.json"
FAILS: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    tag = "OK " if condition else "FAIL"
    print(f"[{tag}] {name}" + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main() -> None:
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(ir)
    button = candidate["tree"][0]["children"][0]["children"][4]["children"][1]
    before = button.get("text", "")
    button["text"] = "AI Apply"
    assist_payload = {
        "summary": "Текст кнопки подготовлен к применению",
        "ops": [{
            "op": "replace",
            "path": "/tree/0/children/0/children/4/children/1/text",
            "before": before,
            "after": "AI Apply",
            "reason": "Проверка атомарного Preview → Apply",
        }],
        "previewIr": candidate,
        "changedViewports": ["desktop"],
        "warnings": [],
        "validation": {"schema": True, "overflow": [], "constraints": []},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.route("**/api/project/load", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"project":null,"updated_at":null}'
        ))
        page.route("**/api/project/save", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}'
        ))
        page.route("**/api/editor/assist", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(assist_payload, ensure_ascii=False)
        ))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("server not ready")

        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": node_id, "ir": ir})
        page.wait_for_timeout(500)
        page.click(".n-edit .f-open-editor")
        page.wait_for_timeout(600)

        page.click('.dna-editor [data-tool="ai"]')
        page.click('#feAiPanel [data-ai-action="adapt"]')
        page.wait_for_selector('#feAiPanel [data-ai-preview="ready"]', timeout=5000)
        check("AI preview показан", page.locator('#feAiPanel [data-ai-preview="ready"]').count() == 1)
        check("AI diff содержит операцию", "1 изменений" in page.locator("#feAiPanel").inner_text())
        check("preview реально отрендерен на холсте", "AI Apply" in page.locator(".fe-canvas-inner").inner_text())
        check("preview помечен как неприменённый", page.locator(".dna-editor.ai-previewing").count() == 1)
        still_original = page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[0].children[4].children[1].text",
            node_id,
        )
        check("preview не мутирует канонический IR", still_original == before, str(still_original))

        page.click('#feAiPanel [data-ai-cancel]')
        page.wait_for_timeout(250)
        check("Cancel возвращает исходный холст", "AI Apply" not in page.locator(".fe-canvas-inner").inner_text())
        check("Cancel снимает preview-state", page.locator(".dna-editor.ai-previewing").count() == 0)

        page.click('#feAiPanel [data-ai-action="adapt"]')
        page.wait_for_selector('#feAiPanel [data-ai-preview="ready"]', timeout=5000)

        page.click('#feAiPanel [data-ai-apply]')
        page.wait_for_timeout(450)
        applied = page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[0].children[4].children[1].text",
            node_id,
        )
        check("Apply меняет IR атомарно", applied == "AI Apply", str(applied))
        check("Apply оставляет dirty-state", page.locator('[data-editor-status]').inner_text() == "Есть изменения")
        check("после Apply preview очищен", page.locator('#feAiPanel [data-ai-preview="ready"]').count() == 0)

        page.locator("body").press("Control+z")
        page.wait_for_timeout(350)
        undone = page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[0].children[4].children[1].text",
            node_id,
        )
        check("Undo откатывает всю AI-операцию", undone == before, str(undone))
        page.click('[data-act="close"]')
        if page.query_selector('[data-act="discard-close"]'):
            page.click('[data-act="discard-close"]')
        browser.close()

    if FAILS:
        print("FAILURES:", len(FAILS))
        for failure in FAILS:
            print(" -", failure)
        raise SystemExit(1)
    print("ALL AI EDITOR CHECKS PASSED")


if __name__ == "__main__":
    main()
