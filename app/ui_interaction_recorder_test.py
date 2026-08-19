"""End-to-end browser checks for the graph Interaction Recorder."""
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
    fixture["tree"][0]["sourceKey"] = "header"
    fixture["tree"][0]["children"][0]["sourceKey"] = "header.container"
    fixture["tree"][0]["children"][1]["sourceKey"] = "header.search"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1800, "height": 1100})
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        else:
            print("server not ready")
            sys.exit(2)

        ownership = page.request.post(BASE + "/api/interaction/capture", data={
            "base_ir": fixture,
            "url": "https://example.com/signup",
            "mine": False,
            "actions": [],
        })
        check("Live capture requires ownership confirmation", ownership.status == 403, ownership.text())

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector(".svelte-flow__pane")
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        edit_id = int(page.evaluate("window.GraphDev.add('edit', 40, 40).id"))
        recorder_id = int(page.evaluate("window.GraphDev.add('recorder', 560, 40).id"))
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": edit_id, "ir": fixture})
        connected = page.evaluate(
            "args => window.GraphDev.connect(args.edit, 'ir', args.recorder, 'ir')",
            {"edit": edit_id, "recorder": recorder_id},
        )
        check("Design IR connects to Recorder", connected)
        page.wait_for_selector('.n-recorder [data-ir-path="children.1"]')

        page.click(".n-recorder .recorder-preview-bar button")
        page.click('.n-recorder [data-ir-path="children.1"]')
        draft = page.evaluate("id => window.GraphDev.node(id).data", recorder_id)
        check("Preview click records stable sourceKey", draft["draftEvents"][0]["targetSourceKey"] == "header.search", str(draft))

        page.fill('.n-recorder input[placeholder^="Type value"]', "designer@example.com")
        page.click(".n-recorder .recorder-input-row button")
        draft = page.evaluate("id => window.GraphDev.node(id).data", recorder_id)
        serialized = str(draft)
        check("PII is redacted before graph persistence", "designer@example.com" not in serialized and "[EMAIL]" in serialized, serialized)
        check("Type event creates replay scene", len(draft["draftScenes"]) == 2 and len(draft["draftEvents"]) == 2, serialized)

        page.click(".n-recorder .ctl-row .primary")
        page.wait_for_function(
            "id => Boolean(window.GraphDev.node(id).data.interaction)",
            arg=recorder_id,
            timeout=8000,
        )
        interaction = page.evaluate("id => window.GraphDev.node(id).data.interaction", recorder_id)
        validation = page.request.post(BASE + "/api/interaction/validate", data={"interaction": interaction}).json()
        check("Built Interaction IR validates", validation.get("valid") is True, str(validation))
        check("Interaction output port is active", page.locator('.n-recorder .port-row.out[data-port="interaction"]').count() == 1)

        captured_request = {}

        def capture_route(route):
            captured_request.update(route.request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"interaction":{"version":"1.0","events":[],"scenes":[],"privacyReport":{"sanitizedCount":1}}}',
            )

        page.route("**/api/interaction/capture", capture_route)
        page.locator(".n-recorder .recorder-mode button").nth(1).click()
        page.fill('.n-recorder input[placeholder^="https://"]', "https://example.com/signup")
        page.check(".n-recorder .recorder-live-meta input[type=checkbox]")
        page.select_option(".n-recorder .recorder-live-builder select", "type")
        page.fill('.n-recorder input[placeholder="sourceKey"]', "signup.email")
        page.fill('.n-recorder input[placeholder="CSS selector"]', "#email")
        page.fill('.n-recorder input[placeholder="Transient value"]', "private@example.com")
        page.click(".n-recorder .recorder-live-builder button")
        persisted_before = str(page.evaluate("id => window.GraphDev.node(id).data", recorder_id))
        check("Transient live value is absent from graph state", "private@example.com" not in persisted_before, persisted_before)
        check("Live action appears in local ordered list", page.locator(".n-recorder .recorder-live-steps div").count() == 1)
        page.click(".n-recorder .ctl-row .primary")
        page.wait_for_function("id => Boolean(window.GraphDev.node(id).data.interaction)", arg=recorder_id)
        check("Live capture sends transient value only to runner", captured_request.get("actions", [{}])[0].get("value") == "private@example.com", str(captured_request))
        persisted_after = str(page.evaluate("id => window.GraphDev.node(id).data", recorder_id))
        check("Transient value remains absent after capture", "private@example.com" not in persisted_after, persisted_after)
        check("Successful capture clears transient steps", page.locator(".n-recorder .recorder-live-steps div").count() == 0)
        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL INTERACTION RECORDER UI CHECKS PASSED")


if __name__ == "__main__":
    main()
