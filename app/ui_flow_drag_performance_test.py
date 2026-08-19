"""Flow canvas drag stays local and responsive until the final dragstop commit."""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8420"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")

        target_id = page.evaluate(
            """() => {
              let first = null;
              for (let i = 0; i < 24; i++) {
                const node = window.GraphDev.add('prompt', 80 + (i % 6) * 360, 80 + Math.floor(i / 6) * 260);
                if (i === 0) first = node.id;
              }
              window.GraphDev.fit();
              return first;
            }"""
        )
        page.wait_for_timeout(800)
        header = page.locator(f'.svelte-flow__node[data-id="{target_id}"] .node-head')
        box = header.bounding_box()
        assert box
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        before = page.evaluate("id => window.GraphDev.node(id)", target_id)
        dom_before = page.locator(f'.svelte-flow__node[data-id="{target_id}"]').bounding_box()

        page.mouse.move(x, y)
        page.mouse.down()
        started = time.perf_counter()
        page.mouse.move(x + 180, y + 100, steps=60)
        move_seconds = time.perf_counter() - started

        mid = page.evaluate("id => window.GraphDev.node(id)", target_id)
        dom_mid = page.locator(f'.svelte-flow__node[data-id="{target_id}"]').bounding_box()
        assert mid["x"] == before["x"] and mid["y"] == before["y"], (before, mid)
        assert abs(dom_mid["x"] - dom_before["x"]) > 20, (dom_before, dom_mid)
        assert move_seconds < 2.5, move_seconds

        page.mouse.up()
        page.wait_for_timeout(250)
        after = page.evaluate("id => window.GraphDev.node(id)", target_id)
        assert after["x"] != before["x"] or after["y"] != before["y"], (before, after)
        assert not errors, errors
        browser.close()

    print(f"FLOW DRAG PERFORMANCE PASSED: 24 nodes, 60 moves in {move_seconds:.3f}s")


if __name__ == "__main__":
    main()
