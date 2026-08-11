"""Chromium acceptance checks for deterministic hybrid interaction capture."""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import interaction_capture
from ir.interaction import replay, validate
from ui_style_dna_test import make_ir

ROOT = Path(__file__).resolve().parent.parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return


def check(name: str, condition: bool, detail=""):
    print(("[OK] " if condition else "[FAIL] ") + name)
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def main():
    base_ir = make_ir()
    base_ir["tree"][0]["sourceKey"] = "signup"
    base_ir["tree"][0]["children"][1] = {
        "type": "input",
        "sourceKey": "signup.email",
        "placeholder": "Email",
        "frame": {"x": 20, "y": 20, "width": 220, "height": 40},
        "style": {"background": "#ffffff", "color": "#171717"},
        "children": [{
            "type": "text", "sourceKey": "signup.email::value", "text": "",
            "frame": {"x": 8, "y": 8, "width": 180, "height": 20},
        }],
    }
    fixture_dir = ROOT / "app" / "fixtures"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(fixture_dir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/interaction_capture_form.html"
    original_validate = interaction_capture.validate_public_url
    interaction_capture.validate_public_url = lambda candidate: candidate
    try:
        result = interaction_capture.capture_live_flow(base_ir, url, [
            {"type": "type", "selector": "#email", "targetSourceKey": "signup.email", "value": "owner@example.com"},
            {"type": "click", "selector": "#submit", "targetSourceKey": "signup.submit"},
            {"type": "scroll", "targetSourceKey": "document-root", "y": 300},
        ])
    finally:
        interaction_capture.validate_public_url = original_validate
        server.shutdown()
        server.server_close()

    serialized = json.dumps(result, ensure_ascii=False)
    check("hybrid Interaction IR validates", not validate(result), str(validate(result)))
    check("raw email is absent from artifact", "owner@example.com" not in serialized, serialized)
    check("typed value is redacted in event and scene", serialized.count("[EMAIL]") >= 2, serialized)
    check("selectors are execution-only", "#email" not in serialized and "#submit" not in serialized, serialized)
    check("three browser actions produce three scenes", len(result["events"]) == 3 and len(result["scenes"]) == 4, serialized)
    check("capture source is hybrid", result["source"]["kind"] == "hybrid", str(result["source"]))
    scene = replay(base_ir, result, "scene-1")
    value_text = scene["tree"][0]["children"][1]["children"][0]["text"]
    check("replay materializes sanitized input state", value_text == "[EMAIL]", str(scene))
    print("ALL HYBRID INTERACTION CAPTURE CHECKS PASSED")


if __name__ == "__main__":
    main()
