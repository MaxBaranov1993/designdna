"""Autosave cost with a heavy Source Import project.

Регрессия 998bb8c/03061c9: раньше каждое dragstop/keystroke сериализовало
мегабайтный проект 3-4 раза и синхронно писало localStorage в кадре. Теперь:
 - сериализация одна и в idle-слоте (longtask после dragstop < 150 мс);
 - POST /api/project/save получает compact (без base64-скриншотов).
Нужен запущенный сервер: .venv/Scripts/python app/server.py
Запуск: .venv/Scripts/python app/ui_flow_autosave_performance_test.py
"""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ~110 KB на превью, 3 вьюпорта, 6 блоков -> ~2 МБ base64 в node.data
PREVIEW = "data:image/jpeg;base64," + "A" * 110_000


def make_block(index: int) -> dict:
    children = [
        {
            "id": f"hero-{index}-{i}",
            "type": "text",
            "text": f"Row {i} of imported block {index}",
            "frame": {"x": 0, "y": i * 28, "width": 320, "height": 24, "layout": "auto", "direction": "row"},
            "style": {"fontSize": 14 + (i % 3), "color": "#222222"},
        }
        for i in range(40)
    ]
    ir = {
        "version": "1.1",
        "tokens": {"color": {"bg": {"value": "#ffffff"}}, "font": {"body": {"value": "Inter"}}},
        "tree": [
            {
                "id": f"sec-{index}",
                "type": "section",
                "sourceKey": f"b{index}:root",
                "frame": {"width": 1200, "height": 40 * 28, "layout": "auto", "direction": "column"},
                "children": children,
            }
        ],
    }
    return {
        "name": f"block{index}",
        "label": f"Block {index}",
        "lit": True,
        "layers": 41,
        "ir": ir,
        "preview": PREVIEW,
        "previews": {"desktop": PREVIEW, "tablet": PREVIEW, "mobile": PREVIEW},
    }


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        save_bodies: list[str] = []
        page.route(
            "**/api/project/load",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"project":null,"updated_at":null}'
            ),
        )

        def capture_save(route):
            body = route.request.post_data or ""
            save_bodies.append(body)
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

        page.route("**/api/project/save", capture_save)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        page.evaluate("window.GraphDev.clear()")

        # питоновская сборка данных дешевле, чем JS-eval строк
        import json as _json

        blocks_json = _json.dumps([make_block(i) for i in range(6)])
        source_id = page.evaluate("window.GraphDev.add('sourceimport', 120, 80).id")
        page.evaluate("(args) => window.GraphDev.patchData(args[0], {blocks: JSON.parse(args[1])})", [source_id, blocks_json])
        for i in range(8):
            page.evaluate(f"window.GraphDev.add('prompt', {120 + (i % 4) * 380}, {560 + (i // 4) * 300})")
        page.wait_for_selector(".bp-block[data-block='block5']")

        # ждём idle-сейв начального состояния и проверяем компактность POST
        page.wait_for_timeout(2200)
        assert save_bodies, "autosave POST never fired"
        worst_post = max(len(body) for body in save_bodies)
        assert worst_post < 400_000, f"POST too big: {worst_post} bytes"
        assert not any("data:image/jpeg;base64," in body for body in save_bodies), "base64 previews leaked into POST"

        page.evaluate(
            """() => {
              window.__longtasks = [];
              new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) window.__longtasks.push(entry.duration);
              }).observe({ entryTypes: ['longtask'] });
            }"""
        )

        # --- сценарий 1: dragstop тяжёлой ноды ---
        header = page.locator(f'.svelte-flow__node[data-id="{source_id}"] .node-head')
        box = header.bounding_box()
        assert box
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 200, y + 120, steps=50)
        page.mouse.up()
        page.wait_for_timeout(2200)  # дебаунс 300 мс + idle до 1.2 с + POST

        moved = page.evaluate("id => window.GraphDev.node(id)", source_id)
        assert moved["x"] != 120 or moved["y"] != 80, "drag position was not committed"
        drag_tasks = page.evaluate("window.__longtasks")
        drag_worst = max(drag_tasks) if drag_tasks else 0.0
        assert drag_worst < 150, f"longtask after dragstop: {drag_worst:.0f} ms"

        # --- сценарий 2: печать в поле url (дебаунс-коммит) ---
        page.evaluate("window.__longtasks = []")
        url_box = page.locator(f'.svelte-flow__node[data-id="{source_id}"] .f-url').bounding_box()
        assert url_box
        page.mouse.click(url_box["x"] + 40, url_box["y"] + 8)
        page.keyboard.type("https://example.com/heavy/page", delay=8)
        page.wait_for_timeout(1600)  # keystrokes + 100 мс debounce + idle
        type_tasks = page.evaluate("window.__longtasks")
        type_worst = max(type_tasks) if type_tasks else 0.0
        assert type_worst < 150, f"longtask while typing: {type_worst:.0f} ms"

        stored = page.evaluate(
            "() => ({ pages: (localStorage.getItem('designai-flow-pages-v1') || '').length,"
            " legacy: (localStorage.getItem('designai-flow-v1') || '').length })"
        )
        assert stored["legacy"] == 0, stored
        assert stored["pages"] < 400_000, stored
        assert not errors, errors
        browser.close()

    print(
        "AUTOSAVE PERFORMANCE PASSED: "
        f"6 blocks × 3 previews (~2 MB base64 in node.data), "
        f"worst POST {worst_post // 1024} KB, "
        f"longtask after dragstop {drag_worst:.0f} ms, while typing {type_worst:.0f} ms"
    )


if __name__ == "__main__":
    main()
