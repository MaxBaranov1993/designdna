"""Focused Interaction IR sanitization, validation and replay checks."""
from __future__ import annotations

import copy
import json
import sys

import ir
from style_projection_test import fixture

FAILS: list[str] = []


def check(name: str, condition: bool, extra=""):
    print(("[OK] " if condition else "[FAIL] ") + name + (f" - {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main():
    base = fixture()
    snapshot = copy.deepcopy(base)
    button = snapshot["tree"][0]["children"][0]
    button["text"] = "Registered user@example.com"
    button["value"] = "+7 999 123-45-67"
    button["styleBindings"] = {"background": {"token": "semantic.primary", "fallback": "#7018e6"}}

    document = ir.build_interaction(
        base,
        {"kind": "hybrid", "url": "https://user:pass@example.com/register?token=secret#step", "title": "Registration"},
        [
            {"id": "start", "patch": [], "viewport": "desktop"},
            {"id": "success", "snapshot": snapshot, "viewport": "desktop"},
        ],
        [
            {"id": "type-email", "time": 300, "type": "type", "targetSourceKey": "source/header/button", "payload": {"value": "user@example.com", "password": "secret"}, "resultingSceneId": "success"},
            {"id": "submit", "time": 900, "type": "submit", "targetSourceKey": "source/header/button", "payload": {"authorization": "Bearer abc.def.ghi"}, "resultingSceneId": "success"},
        ],
        {"email": "user@example.com", "sessionToken": "abc"},
    )

    encoded = json.dumps(document, ensure_ascii=False)
    check("Interaction IR validates", not ir.validate_interaction(document), str(ir.validate_interaction(document)))
    check("source URL drops credentials/query/fragment", document["source"]["url"] == "https://example.com/register", document["source"]["url"])
    check("email, phone and secret values are absent", "user@example.com" not in encoded and "999 123" not in encoded and "token=secret" not in encoded and '"password": "secret"' not in encoded and "Bearer" not in encoded)
    check("privacy report records redactions", document["privacyReport"]["sanitizedCount"] >= 6, str(document["privacyReport"]))

    replayed = ir.replay_interaction(base, document, "success")
    replayed_button = replayed["tree"][0]["children"][0]
    check("scene replay applies sanitized snapshot patch", replayed_button["text"] == "Registered [EMAIL]" and replayed_button["value"] == "[PHONE]", str(replayed_button))
    check("Design IR semantic token references survive sanitization", replayed_button["styleBindings"]["background"]["token"] == "semantic.primary")
    check("base IR remains unchanged", base["tree"][0]["children"][0]["text"] == "Continue")

    rejected = False
    try:
        ir.apply_interaction_patch(base, [{"op": "replace", "path": "/version", "value": "9"}])
    except (ValueError, AttributeError):
        rejected = True
    check("patch cannot mutate protected document roots", rejected)

    bad = copy.deepcopy(document)
    bad["events"][0]["resultingSceneId"] = "missing"
    check("semantic validator catches missing scene", any("does not exist" in error for error in ir.validate_interaction(bad)))

    if FAILS:
        print("FAILS:", FAILS)
        sys.exit(1)
    print("ALL INTERACTION IR CHECKS PASSED")


if __name__ == "__main__":
    main()
