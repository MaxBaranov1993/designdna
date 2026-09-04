"""Playwright contract for Generator art directions and judge feedback.

All generation, Quality Pass, project and taste endpoints are mocked; the test
never calls an LLM and may run against an isolated local server.
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import Route, sync_playwright


BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:8420")
FAILS: list[str] = []

DIRECTIONS = [
    {
        "id": "editorial",
        "label": "Editorial Focus",
        "motivation": "Сильная иерархия быстро объясняет продукт.",
        "tradeoff": "Меньше места для вторичных карточек.",
    },
    {
        "id": "soft-pastel",
        "label": "Soft Pastel",
        "motivation": "Мягкая палитра снижает тревожность аудитории.",
        "tradeoff": "Потребуется строгий контроль контраста.",
    },
    {
        "id": "industrial",
        "label": "Industrial Grid",
        "motivation": "Технический ритм подчёркивает надёжность.",
        "tradeoff": "Характер может казаться холодным.",
    },
]


def ir(direction: str, heading: str) -> dict:
    return {
        "frame": {"width": 960},
        "tokens": {"color": {"primary": "#5b5bd6", "background": "#ffffff"}},
        "meta": {"designDirection": direction},
        "tree": [{
            "id": f"cta-{direction}",
            "type": "cta",
            "variant": "centered",
            "props": {
                "heading": heading,
                "subheading": "Mocked direction without an LLM",
                "ctaPrimary": {"text": "Start", "variant": "primary"},
            },
        }],
    }


VARIANTS = [
    ir("Editorial Focus", "Editorial page"),
    ir("Soft Pastel", "Pastel page"),
    ir("Industrial Grid", "Industrial page"),
]


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    generate_payloads: list[dict] = []
    taste_payloads: list[dict] = []
    quality_index = 0

    def route_api(route: Route) -> None:
        nonlocal quality_index
        url = route.request.url
        if url.endswith("/api/project/load"):
            route.fulfill(status=200, content_type="application/json", body='{"project":null}')
        elif url.endswith("/api/project/save"):
            route.fulfill(status=200, content_type="application/json", body='{"ok":true,"revision":"mock"}')
        elif url.endswith("/api/project/taste/outcome"):
            taste_payloads.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        elif url.endswith("/api/generate"):
            generate_payloads.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "variants": VARIANTS,
                "directions": DIRECTIONS,
                "variantDirections": [item["label"] for item in DIRECTIONS],
                "errors": [],
            }, ensure_ascii=False))
        elif url.endswith("/api/quality-pass"):
            index = quality_index % len(VARIANTS)
            quality_index += 1
            failed = index == 0
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "ir": VARIANTS[index],
                "passed": not failed,
                "min_score": 80,
                "scorecard": {
                    "score": 68 if failed else 91,
                    "verdict": "needs_repair" if failed else "pass",
                    "summary": "Hierarchy is too flat" if failed else "Ready",
                    "issues": ([{
                        "severity": "major",
                        "problem": "Hero and supporting copy have equal visual weight.",
                        "instruction": "Increase the hero contrast and spacing.",
                    }] if failed else []),
                },
                "repair": {"attempted": failed, "applied": False, "error": None},
            }))
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        page.route("**/api/**", route_api)
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2_000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError(f"server not ready at {BASE}")

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev")
        page.evaluate("window.GraphDev.clear()")
        node_id = page.evaluate("window.GraphDev.add('generator', 300, 100).id")
        check("generator keeps exactly three inputs",
              page.locator(f'.svelte-flow__node[data-id="{node_id}"] .port-row.in').count() == 3)
        page.evaluate("id => window.GraphDev.patchData(id, {ownPrompt:'Design a calm finance landing page'})", node_id)
        page.evaluate("id => window.GraphDev.run(id)", node_id)

        node = page.locator(f'.svelte-flow__node[data-id="{node_id}"]')
        node.locator(".direction-chip").first.wait_for(timeout=10_000)
        check("three art-direction chips are rendered", node.locator(".direction-chip").count() == 3)
        check("motivation and tradeoff are visible",
              "Сильная иерархия" in node.locator(".direction-chip").first.inner_text()
              and "Компромисс:" in node.locator(".direction-chip").first.inner_text())
        check("all-directions choice is selected by default",
              "active" in (node.locator(".direction-all").get_attribute("class") or ""))

        badges = node.locator(".thumb .tbadge").all_inner_texts()
        check("variants are labelled by direction", badges == [item["label"] for item in DIRECTIONS], str(badges))
        check("generic variant labels are absent", all("Вариант" not in label for label in badges))

        revision = node.locator(".revision-status")
        revision.wait_for(timeout=5_000)
        revision_text = revision.inner_text()
        check("failed judge result uses needs-revision status", "Нужна доработка · 68/100" in revision_text)
        check("judge reason is visible", "equal visual weight" in revision_text)
        check("node status includes the judge reason",
              "Нужна доработка" in node.locator(".n-status").inner_text()
              and "equal visual weight" in node.locator(".n-status").inner_text())

        node.locator('.direction-chip[data-direction-id="soft-pastel"]').click()
        page.wait_for_function(
            "id => window.GraphDev.node(id).data.selectedDirection === 'soft-pastel'",
            arg=node_id,
        )
        page.wait_for_function("() => window.__unused === undefined")
        check("one direction can be selected",
              node.locator('.direction-chip[data-direction-id="soft-pastel"]').get_attribute("aria-pressed") == "true")
        check("selected direction is recorded in Taste Memory",
              bool(taste_payloads)
              and taste_payloads[-1].get("kind") == "accepted"
              and taste_payloads[-1].get("payload", {}).get("style", {}).get("tags") == ["art-direction:soft-pastel"],
              str(taste_payloads))

        page.evaluate("id => window.GraphDev.run(id)", node_id)
        page.wait_for_function(
            "id => !document.querySelector(`.svelte-flow__node[data-id='${id}'] .f-run`).disabled",
            arg=str(node_id),
        )
        check("subsequent generation carries the selected direction",
              len(generate_payloads) >= 2
              and generate_payloads[-1].get("selectedDirection") == "soft-pastel"
              and generate_payloads[-1].get("allDirections") is False,
              str(generate_payloads[-1] if generate_payloads else {}))

        node.locator(".direction-all").click()
        page.wait_for_function("id => window.GraphDev.node(id).data.selectedDirection === 'all'", arg=node_id)
        check("all three can be selected", "active" in (node.locator(".direction-all").get_attribute("class") or ""))

        browser.close()

    if FAILS:
        print(f"\n{len(FAILS)} FAIL: {', '.join(FAILS)}")
        sys.exit(1)
    print("\nALL GENERATOR DIRECTION UI CHECKS PASSED")


if __name__ == "__main__":
    main()
