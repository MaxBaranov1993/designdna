"""Deterministic video render acceptance checks."""
from __future__ import annotations

import tempfile
import hashlib
from pathlib import Path

import imageio_ffmpeg

from ir import build_interaction, build_motion, ensure_current, replay_interaction
from motion_render import eased_progress, frame_count, frame_state, render_video
from ui_style_dna_test import make_ir


def check(name: str, condition: bool, extra="") -> None:
    if not condition:
        raise AssertionError(f"{name}: {extra}")
    print(f"[OK] {name}")


def main() -> None:
    base_ir = make_ir()
    base_ir["tree"][0]["sourceKey"] = "header"
    base_ir["tree"][0]["children"][1]["sourceKey"] = "header.search"
    base_ir = ensure_current(base_ir)
    interaction = build_interaction(base_ir, {"kind": "design-ir"}, [
        {"id": "scene-0", "viewport": "desktop", "patch": []},
        {"id": "scene-1", "viewport": "desktop", "patch": [{
            "op": "replace", "path": "/tree/0/children/1/text", "value": "Registered",
        }]},
    ], [])
    motion = build_motion(interaction, {"width": 320, "height": 240, "fps": 12}, {
        "scene-0": {"duration": 250},
        "scene-1": {"duration": 250, "transition": "fade", "transitionDuration": 250, "easing": "linear"},
    })
    scene_irs = [{
        "sceneId": scene["id"],
        "ir": ensure_current(replay_interaction(base_ir, interaction, scene["interactionSceneId"])),
    } for scene in motion["scenes"]]

    check("frame count rounds up from canonical duration", frame_count(501, 12) == 7)
    check("easing is clamped", eased_progress(2, "linear") == 1)
    boundary = frame_state(motion, 3)
    check("scene boundary keeps previous layer for transition", boundary["sceneIndex"] == 1 and boundary["previousIndex"] == 0, str(boundary))
    check("transition starts at exact zero progress", boundary["progress"] == 0, str(boundary))

    progress: list[tuple[int, int]] = []
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "motion.mp4"
        result = render_video(motion, scene_irs, output, lambda done, total: progress.append((done, total)))
        check("MP4 artifact is non-empty", output.stat().st_size > 500, str(result))
        reader = imageio_ffmpeg.read_frames(str(output), pix_fmt="rgb24")
        metadata = next(reader)
        decoded = sum(1 for _ in reader)
        check("encoded geometry matches composition", metadata["size"] == (320, 240), str(metadata))
        check("encoded FPS matches composition", abs(float(metadata["fps"]) - 12) < 0.01, str(metadata))
        check("encoded frame count is deterministic", decoded == 6 and result["frames"] == 6, f"{decoded}, {result}")
        check("progress reaches the final frame", progress[-1] == (6, 6), str(progress))

        repeated = Path(directory) / "motion-repeat.mp4"
        render_video(motion, scene_irs, repeated)
        check(
            "same Motion IR produces identical MP4 bytes",
            hashlib.sha256(output.read_bytes()).digest() == hashlib.sha256(repeated.read_bytes()).digest(),
        )

        webm_motion = build_motion(interaction, {"width": 320, "height": 240, "fps": 12}, {
            "scene-0": {"duration": 250}, "scene-1": {"duration": 250},
        }, {"format": "webm", "quality": "draft"})
        webm = Path(directory) / "motion.webm"
        webm_result = render_video(webm_motion, scene_irs, webm)
        check("WebM / VP9 export is encoded", webm.stat().st_size > 500 and webm_result["format"] == "webm")

    print("ALL MOTION RENDER CHECKS PASSED")


if __name__ == "__main__":
    main()
