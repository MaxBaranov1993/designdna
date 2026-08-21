"""End-to-end graph and fullscreen Motion Editor acceptance checks."""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

from ir.migrate import ensure_current
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
    fixture["tree"][0]["children"][1]["sourceKey"] = "header.search"
    fixture = ensure_current(fixture)
    scenes = [
        {"id": "scene-0", "viewport": "desktop", "patch": []},
        {"id": "scene-1", "viewport": "desktop", "patch": [
            {"op": "replace", "path": "/tree/0/children/1/text", "value": "Registered"},
        ]},
    ]
    events = [{
        "id": "event-1", "time": 300, "type": "click", "targetSourceKey": "header.search",
        "payload": {}, "resultingSceneId": "scene-1",
    }]

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
        check("Motion Editor feature flag enabled", config.get("flags", {}).get("motionEditor") is True, str(config))
        check("Video Render feature flag enabled", config.get("flags", {}).get("videoRender") is True, str(config))

        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.add === 'function'")
        # изоляция от состояния в SQLite: boot мог подтянуть прошлый проект из БД
        page.evaluate("window.GraphDev.clear()")
        edit_id = int(page.evaluate("window.GraphDev.add('edit', 30, 40).id"))
        recorder_id = int(page.evaluate("window.GraphDev.add('recorder', 520, 40).id"))
        motion_id = int(page.evaluate("window.GraphDev.add('motion', 1010, 40).id"))
        page.evaluate("(args) => window.GraphDev.setIR(args.id, args.ir)", {"id": edit_id, "ir": fixture})
        check("Design IR connects to Recorder", page.evaluate("a => window.GraphDev.connect(a.edit, 'ir', a.rec, 'ir')", {"edit": edit_id, "rec": recorder_id}))
        check("Design IR connects to Motion", page.evaluate("a => window.GraphDev.connect(a.edit, 'ir', a.motion, 'ir')", {"edit": edit_id, "motion": motion_id}))
        check("Interaction IR connects to Motion", page.evaluate("a => window.GraphDev.connect(a.rec, 'interaction', a.motion, 'interaction')", {"rec": recorder_id, "motion": motion_id}))
        page.evaluate("a => window.GraphDev.patchData(a.id, {draftScenes:a.scenes,draftEvents:a.events})", {"id": recorder_id, "scenes": scenes, "events": events})
        page.evaluate("id => window.GraphDev.run(id)", recorder_id)
        page.wait_for_function("id => Boolean(window.GraphDev.node(id).data.interaction)", arg=recorder_id, timeout=8000)
        page.evaluate("a => window.GraphDev.patchData(a.id, {composition:{width:320,height:240,fps:12},renderSettings:{format:'mp4',quality:'high'},sceneSettings:{'scene-0':{duration:600},'scene-1':{duration:900}}})", {"id": motion_id})
        page.evaluate("id => window.GraphDev.run(id)", motion_id)
        page.wait_for_function("id => Boolean(window.GraphDev.node(id).data.motion)", arg=motion_id, timeout=8000)
        data = page.evaluate("id => window.GraphDev.node(id).data", motion_id)
        check("Motion IR has two materialized scenes", len(data["motion"]["scenes"]) == 2 and len(data["sceneIrs"]) == 2, str(data))
        check("Timeline honors scene durations", data["motion"]["composition"]["duration"] == 1500, str(data["motion"]))
        validation = page.request.post(BASE + "/api/motion/validate", data={"motion": data["motion"], "interaction": data["interaction"]}).json()
        check("Motion IR validates through API", validation.get("valid") is True, str(validation))
        stale_motion = {**data["motion"], "source": {**data["motion"]["source"], "interactionHash": "0" * 64}}
        stale = page.request.post(BASE + "/api/motion/render", data={"base_ir": data["ir"], "interaction": data["interaction"], "motion": stale_motion})
        check("Render rejects stale provenance", stale.status == 409, stale.text())
        check("Motion output uses typed port", page.locator('.n-motion .port-row.out[data-port="motion"][data-kind="motion"]').count() == 1)

        page.get_by_role("button", name="Open editor").click()
        page.wait_for_selector(".motion-workspace")
        check("Fullscreen Motion Editor opens", page.locator(".motion-workspace").count() == 1)
        check("Timeline renders two clips", page.locator(".motion-clips button").count() == 2)
        page.locator(".motion-clips button").nth(1).click()
        page.locator('.motion-inspector label:has-text("Duration") input').first.fill("1400")
        page.locator('.motion-inspector label:has-text("Transition") select').select_option("slide-left")
        page.get_by_role("button", name="Apply timeline").click()
        page.wait_for_function("id => window.GraphDev.node(id).data.motion.composition.duration === 2000", arg=motion_id, timeout=8000)
        check("Inspector rebuilds canonical timeline", page.evaluate("id => window.GraphDev.node(id).data.motion.scenes[1].transition.type === 'slide-left'", motion_id))
        playhead_before = float(page.locator('.motion-timebar input').input_value())
        page.get_by_role("button", name="Play").click()
        page.wait_for_timeout(180)
        playhead_after = float(page.locator('.motion-timebar input').input_value())
        check("Transport advances playhead", playhead_after > playhead_before, f"{playhead_before} -> {playhead_after}")
        page.get_by_role("button", name="Export MP4").click()
        page.wait_for_function("id => window.GraphDev.node(id).data.renderJob?.status === 'complete'", arg=motion_id, timeout=60000)
        render_job = page.evaluate("id => window.GraphDev.node(id).data.renderJob", motion_id)
        check("Render job reports completed progress", render_job["progress"] == 100 and render_job["result"]["frames"] == 24, str(render_job))
        check("Completed render exposes download control", page.locator("a.motion-download").count() == 1)
        video = page.request.get(BASE + render_job["downloadUrl"])
        check("Rendered MP4 downloads from guarded artifact route", video.status == 200 and video.headers.get("content-type", "").startswith("video/mp4") and len(video.body()) > 500)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator(".motion-inspector-toggle").click()
        check("Mobile canvas can use the full workspace", not page.locator(".motion-inspector").is_visible() and page.locator(".motion-stage").bounding_box()["width"] == 390)
        page.locator(".motion-inspector-toggle").click()
        check("Mobile inspector opens as a drawer", page.locator(".motion-inspector.open").is_visible())
        page.keyboard.press("Escape")
        check("Escape closes Motion Editor", page.locator(".motion-workspace").count() == 0)
        page.wait_for_timeout(700)
        page.reload()
        page.wait_for_function("window.GraphDev && typeof window.GraphDev.node === 'function'")
        check("Render job is excluded from project persistence", page.evaluate("id => window.GraphDev.node(id).data.renderJob === null", motion_id))
        browser.close()

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL MOTION EDITOR UI CHECKS PASSED")


if __name__ == "__main__":
    main()
