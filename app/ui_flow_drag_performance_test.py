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
        page.route(
            "**/api/project/load",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"project":null,"updated_at":null}',
            ),
        )
        page.route(
            "**/api/project/save",
            lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true}'),
        )
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
              for (let i = 0; i < 48; i++) {
                window.GraphDev.add('prompt', 5000 + (i % 12) * 360, 5000 + Math.floor(i / 12) * 260);
              }
              return first;
            }"""
        )
        page.wait_for_timeout(800)
        rendered_nodes = page.locator(".svelte-flow__node").count()
        assert rendered_nodes < 40, rendered_nodes
        header = page.locator(f'.svelte-flow__node[data-id="{target_id}"] .node-head')
        box = header.bounding_box()
        assert box
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        before = page.evaluate("id => window.GraphDev.node(id)", target_id)
        dom_before = page.locator(f'.svelte-flow__node[data-id="{target_id}"]').bounding_box()

        page.mouse.move(x, y)
        page.evaluate(
            """() => {
              window.__dragFrameGaps = [];
              window.__dragFrameActive = true;
              let previous = performance.now();
              const sample = (now) => {
                if (!window.__dragFrameActive) return;
                window.__dragFrameGaps.push(now - previous);
                previous = now;
                requestAnimationFrame(sample);
              };
              requestAnimationFrame(sample);
            }"""
        )
        page.mouse.down()
        started = time.perf_counter()
        page.mouse.move(x + 180, y + 100, steps=60)
        move_seconds = time.perf_counter() - started

        mid = page.evaluate("id => window.GraphDev.node(id)", target_id)
        dom_mid = page.locator(f'.svelte-flow__node[data-id="{target_id}"]').bounding_box()
        assert mid["x"] == before["x"] and mid["y"] == before["y"], (before, mid)
        assert abs(dom_mid["x"] - dom_before["x"]) > 20, (dom_before, dom_mid)
        page.mouse.up()
        frame_gaps = page.evaluate(
            """() => {
              window.__dragFrameActive = false;
              return window.__dragFrameGaps.slice(2);
            }"""
        )
        assert len(frame_gaps) >= 20, len(frame_gaps)
        ordered_gaps = sorted(frame_gaps)
        p95_gap_ms = ordered_gaps[min(len(ordered_gaps) - 1, int(len(ordered_gaps) * 0.95))]
        long_frame_ratio = sum(gap > 34 for gap in frame_gaps) / len(frame_gaps)
        assert p95_gap_ms < 34, p95_gap_ms
        assert long_frame_ratio < 0.1, long_frame_ratio
        page.wait_for_timeout(250)
        after = page.evaluate("id => window.GraphDev.node(id)", target_id)
        assert after["x"] != before["x"] or after["y"] != before["y"], (before, after)
        assert not errors, errors
        browser.close()

    print(
        "FLOW DRAG PERFORMANCE PASSED: "
        f"72 nodes ({rendered_nodes} mounted), 60 protocol moves in {move_seconds:.3f}s, "
        f"rAF p95={p95_gap_ms:.1f}ms, long frames={long_frame_ratio:.1%}"
    )


if __name__ == "__main__":
    main()
