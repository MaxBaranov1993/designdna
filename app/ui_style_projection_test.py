"""Browser checks for Normalize preview and Tailwind projection in DNA Editor."""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

from ui_style_dna_test import make_ir

BASE = "http://127.0.0.1:8420"
FAILS: list[str] = []


def check(name: str, condition: bool, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main():
    fixture = make_ir()
    fixture["tree"][0]["children"][1]["style"]["fontSize"] = 15
    fixture["tree"][0]["children"][1]["style"]["borderRadius"] = 7

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        config = page.request.get(BASE + "/api/config").json()
        check("Tailwind feature flag enabled", config.get("flags", {}).get("tailwindProjection") is True, str(config))

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        page.evaluate("window.GraphDev.add('edit', 60, 40)")
        node_id = int(page.evaluate("window.GraphDev.state().nodes.find(n => n.type === 'edit').id"))
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": node_id, "ir": fixture})
        page.click(".n-edit .f-open-editor")
        page.click('[data-act="style-dna"]')
        page.wait_for_selector('[data-dna-action="preview-normalize"]')

        page.click('[data-dna-action="preview-normalize"]')
        page.wait_for_selector('[data-dna-action="apply-normalize"]')
        preview_text = page.locator("#feDnaWorkflowResult").inner_text()
        check("Normalize preview lists property changes", "fontSize" in preview_text and "borderRadius" in preview_text, preview_text)

        page.click('[data-dna-action="apply-normalize"]')
        normalized = page.evaluate(
            "id => window.GraphDev.node(id).data.ir.tree[0].children[1].style",
            node_id,
        )
        check("Normalize applies only after confirmation", normalized.get("fontSize") == 14 and normalized.get("borderRadius") == 6, str(normalized))

        page.click('[data-dna-action="tailwind-exact"]')
        page.wait_for_function("document.querySelector('#feDnaWorkflowResult')?.innerText.includes('bg-[#ff691d]')")
        exact_text = page.locator("#feDnaWorkflowResult").inner_text()
        check("Exact projection shows arbitrary utility", "bg-[#ff691d]" in exact_text, exact_text)

        page.click('[data-dna-action="tailwind-normalized"]')
        page.wait_for_function("document.querySelector('#feDnaWorkflowResult')?.innerText.includes('bg-primary')")
        normalized_text = page.locator("#feDnaWorkflowResult").inner_text()
        check("Normalized projection shows semantic utility", "bg-primary" in normalized_text, normalized_text)
        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL STYLE PROJECTION UI CHECKS PASSED")


if __name__ == "__main__":
    main()
