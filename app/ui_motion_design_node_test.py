"""Browser contract for Motion Design planners and the paid Seedance gate.

GPT/Claude and OpenRouter are mocked; this test cannot consume credits.
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import Route, sync_playwright


BASE = os.environ.get("DESIGNAI_UI_BASE", "http://127.0.0.1:8420")
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    submitted: list[dict] = []

    def route_api(route: Route) -> None:
        url = route.request.url
        if url.endswith("/api/project/load"):
            route.fulfill(status=200, content_type="application/json", body='{"project":null}')
        elif url.endswith("/api/project/save"):
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        elif url.endswith("/api/video/seedance/config"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "configured": True, "model": "bytedance/seedance-2.5",
            }))
        elif url.endswith("/api/video/seedance/submit"):
            submitted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "id": "job_ui_safe", "status": "pending", "model": "bytedance/seedance-2.5",
            }))
        elif url.endswith("/api/fake-motion.mp4"):
            route.fulfill(status=200, content_type="video/mp4", body=b"fake-video")
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        planner_bridge = """
          window.__motionPlannerCalls = [];
          window.designDNA = {
            providers: {
              chatRequest: async (request) => {
                window.__motionPlannerCalls.push(request);
                return {
                  content: request.provider === 'claude'
                    ? 'Claude planned camera continuity with preserved interface text.'
                    : 'GPT planned a measured cinematic extension with no layout drift.',
                  provider: request.provider,
                  requestId: 'planner-test',
                  transport: { provider: request.provider, model: request.model, requestId: 'planner-test' }
                };
              }
            }
          };
        """
        page.route("**/api/**", route_api)
        for _ in range(30):
            try:
                page.goto(BASE + "/flow", timeout=2_000)
                break
            except Exception:
                time.sleep(1)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev")
        page.evaluate("window.GraphDev.clear()")
        # Install only the provider mock after browser boot; it is not a full Electron preload.
        page.evaluate(planner_bridge)

        node_id = page.evaluate("window.GraphDev.add('motiondesign', 300, 120).id")
        video = {
            "version": "video-artifact/1.0",
            "origin": "motion-editor",
            "jobId": "local-render",
            "downloadUrl": "/api/fake-motion.mp4",
            "filename": "motion.mp4",
            "mime": "video/mp4",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "duration": 8_000,
            "parameters": {"composition": {"width": 1920, "height": 1080, "fps": 30}},
        }
        page.evaluate("(v) => window.GraphDev.patchData(v.id, {prompt:'Extend the product reveal', planner:'openai', inputMode:'reference', sourceVideo:v.video})", {"id": node_id, "video": video})
        page.evaluate("id => window.GraphDev.run(id)", node_id)
        page.wait_for_function("id => window.GraphDev.node(id).data.plannedPrompt.includes('GPT planned')", arg=node_id)

        calls = page.evaluate("window.__motionPlannerCalls")
        check("GPT planner routed through the desktop provider envelope", calls[0]["provider"] == "openai")
        check("planner receives metadata but never video bytes", "data:video" not in json.dumps(calls[0]))

        page.evaluate("id => window.GraphDev.patchData(id, {planner:'claude', plannedPrompt:''})", node_id)
        page.evaluate("id => window.GraphDev.run(id)", node_id)
        page.wait_for_function("id => window.GraphDev.node(id).data.plannedPrompt.includes('Claude planned')", arg=node_id)
        calls = page.evaluate("window.__motionPlannerCalls")
        check("Claude Code planner uses the Claude transport", calls[-1]["provider"] == "claude")

        node = page.locator(f'.svelte-flow__node[data-id="{node_id}"]')
        inputs = node.locator('.dna-port.in')
        input_tops = [inputs.nth(i).get_attribute("style") for i in range(inputs.count())]
        check("four inputs are ordered on the left", input_tops == [
            "top: 44px;", "top: 66px;", "top: 88px;", "top: 110px;",
        ], str(input_tops))
        check("video output is on the right", node.locator('.dna-port.out[data-kind="video"]').count() == 1)

        generate = node.get_by_role("button", name="Сгенерировать")
        check("paid Seedance button starts disabled", generate.is_disabled())
        check("no submit happened while confirmation was absent", len(submitted) == 0)
        node.locator('.md-paid input[type="checkbox"]').check()
        generate.click()
        page.wait_for_function("() => window.GraphDev.node(" + str(node_id) + ").data.job?.id === 'job_ui_safe'")
        check("one confirmed Seedance request was submitted", len(submitted) == 1)
        payload = submitted[0]
        check("submit is pinned to explicit confirmation", payload.get("confirmed_paid") is True)
        ref_url = (((payload.get("input_references") or [{}])[0].get("video_url") or {}).get("url") or "")
        check("completed local render becomes a video_url data reference", ref_url.startswith("data:video/mp4;base64,"))

        browser.close()


if __name__ == "__main__":
    main()
    if FAILS:
        print(f"\n{len(FAILS)} FAIL: {', '.join(FAILS)}")
        sys.exit(1)
    print("\nALL MOTION DESIGN UI CHECKS PASSED")
