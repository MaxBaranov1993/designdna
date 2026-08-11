"""Motion IR construction, timeline and replay acceptance checks."""
from __future__ import annotations

import copy

from ir.hash import content_hash
from ir.interaction import build as build_interaction, replay
from ir.motion import build as build_motion, validate
from ui_style_dna_test import make_ir


def check(name: str, condition: bool, detail=""):
    print(("[OK] " if condition else "[FAIL] ") + name)
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def main():
    base = make_ir()
    base["tree"][0]["sourceKey"] = "header"
    base["tree"][0]["children"][1]["sourceKey"] = "header.search"
    interaction = build_interaction(base, {"kind": "design-ir"}, [
        {"id": "scene-0", "viewport": "desktop", "patch": []},
        {"id": "scene-1", "viewport": "desktop", "patch": [
            {"op": "replace", "path": "/tree/0/children/1/text", "value": "Done"},
        ]},
    ], [{
        "id": "event-1", "time": 500, "type": "click", "targetSourceKey": "header.search",
        "payload": {}, "resultingSceneId": "scene-1",
    }])
    motion = build_motion(interaction, {"width": 1080, "height": 1920, "fps": 30}, {
        "scene-0": {"duration": 900, "transition": "cut"},
        "scene-1": {"duration": 1800, "transition": "slide-left", "transitionDuration": 450, "easing": "ease-out"},
    })
    check("Motion IR validates", not validate(motion, interaction), str(validate(motion, interaction)))
    check("vertical composition is preserved", motion["composition"]["width"] == 1080 and motion["composition"]["height"] == 1920)
    check("timeline is contiguous", motion["scenes"][0]["start"] == 0 and motion["scenes"][1]["start"] == 900)
    check("composition duration follows clips", motion["composition"]["duration"] == 2700)
    check("transition settings are deterministic", motion["scenes"][1]["transition"] == {"type": "slide-left", "duration": 450, "easing": "ease-out"})
    check("source hashes bind both IR layers", motion["source"]["interactionHash"] == content_hash(interaction) and motion["source"]["baseDesignIrHash"] == content_hash(base))
    scene = replay(base, interaction, "scene-1")
    check("referenced scene remains editable Design IR", scene["tree"][0]["children"][1]["text"] == "Done")
    broken = copy.deepcopy(motion)
    broken["scenes"][1]["start"] = 1200
    check("validator rejects timeline gaps", any("contiguous" in item for item in validate(broken, interaction)), str(validate(broken, interaction)))
    broken_clip = copy.deepcopy(motion)
    broken_clip["tracks"][0]["clips"][1]["duration"] = 500
    check("validator rejects clip/scene drift", any("timing must match" in item for item in validate(broken_clip, interaction)), str(validate(broken_clip, interaction)))
    print("ALL MOTION IR CHECKS PASSED")


if __name__ == "__main__":
    main()
