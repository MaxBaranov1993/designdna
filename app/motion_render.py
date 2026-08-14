"""Deterministic Motion IR frame composition and local video encoding."""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
from playwright.sync_api import sync_playwright


APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
RENDERER_JS = APP_ROOT / "static" / "flow" / "engine.js"
MAX_RENDER_FRAMES = 10_800


def frame_count(duration_ms: int, fps: int) -> int:
    return max(1, math.ceil(max(0, duration_ms) * max(1, fps) / 1000))


def eased_progress(progress: float, easing: str) -> float:
    p = min(1.0, max(0.0, progress))
    if easing == "ease-in":
        return p * p
    if easing == "ease-out":
        return 1 - (1 - p) * (1 - p)
    if easing in {"ease", "ease-in-out"}:
        return p * p * (3 - 2 * p)
    return p


def frame_state(motion: dict, frame_index: int) -> dict:
    """Return the exact scene/transition state for one output frame."""
    composition = motion["composition"]
    scenes = motion["scenes"]
    time_ms = frame_index * 1000 / composition["fps"]
    scene_index = next(
        (index for index, scene in enumerate(scenes)
         if time_ms < scene["start"] + scene["duration"]),
        len(scenes) - 1,
    )
    scene = scenes[scene_index]
    transition = scene["transition"]
    transition_duration = transition["duration"] if scene_index > 0 else 0
    local_time = max(0.0, time_ms - scene["start"])
    progress = 1.0
    if transition_duration > 0 and local_time < transition_duration:
        progress = eased_progress(local_time / transition_duration, transition["easing"])
    return {
        "frame": frame_index,
        "time": time_ms,
        "sceneIndex": scene_index,
        "previousIndex": scene_index - 1 if progress < 1 else -1,
        "transition": transition["type"] if progress < 1 else "cut",
        "progress": progress,
    }


def _ffmpeg_command(output: Path, motion: dict, count: int) -> list[str]:
    composition = motion["composition"]
    settings = motion["renderSettings"]
    fps = int(composition["fps"])
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "png", "-framerate", str(fps), "-i", "pipe:0",
        "-an", "-frames:v", str(count), "-map_metadata", "-1", "-fflags", "+bitexact",
        "-threads", "1",
    ]
    if settings["format"] == "webm":
        quality = {"draft": "38", "high": "28", "lossless": "0"}[settings["quality"]]
        command += ["-c:v", "libvpx-vp9", "-crf", quality, "-b:v", "0", "-row-mt", "0"]
        if settings["quality"] == "lossless":
            command += ["-lossless", "1"]
    else:
        quality = {"draft": "28", "high": "18", "lossless": "0"}[settings["quality"]]
        pixel_format = "yuv444p" if settings["quality"] == "lossless" else "yuv420p"
        command += [
            "-c:v", "libx264", "-preset", "medium", "-crf", quality,
            "-pix_fmt", pixel_format, "-movflags", "+faststart",
        ]
    command.append(str(output))
    return command


def validate_render_input(motion: dict, scene_irs: list[dict]) -> tuple[int, str]:
    composition = motion.get("composition") or {}
    settings = motion.get("renderSettings") or {}
    scenes = motion.get("scenes") or []
    count = frame_count(int(composition.get("duration") or 0), int(composition.get("fps") or 0))
    if count > MAX_RENDER_FRAMES:
        raise ValueError(f"render exceeds the {MAX_RENDER_FRAMES} frame limit")
    if int(composition.get("width") or 0) % 2 or int(composition.get("height") or 0) % 2:
        raise ValueError("video composition width and height must be even")
    expected = [scene.get("id") for scene in scenes]
    actual = [item.get("sceneId") for item in scene_irs]
    if expected != actual:
        raise ValueError("materialized scenes do not match Motion IR order")
    output_format = str(settings.get("format") or "mp4")
    return count, output_format


def render_video(
    motion: dict,
    scene_irs: list[dict],
    output: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Render scene DOM at exact frame times and encode it into one video."""
    count, output_format = validate_render_input(motion, scene_irs)
    if output.suffix.lower() != f".{output_format}":
        raise ValueError("output extension does not match Motion IR format")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.stem}.part{output.suffix}")
    if temporary.exists():
        temporary.unlink()

    command = _ffmpeg_command(temporary, motion, count)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                composition = motion["composition"]
                page = browser.new_page(viewport={
                    "width": int(composition["width"]),
                    "height": int(composition["height"]),
                }, device_scale_factor=1)
                page.set_content(
                    '<style>html,body,#stage{margin:0;width:100%;height:100%;overflow:hidden}'
                    'body{background:var(--motion-bg)}.motion-layer{position:absolute;inset:0;'
                    'overflow:hidden;transform-origin:center center;will-change:transform,opacity}'
                    '.motion-ir{position:absolute;left:0;top:0;transform-origin:top left}</style>'
                    '<div id="stage"></div>'
                )
                page.add_script_tag(path=str(RENDERER_JS))
                page.evaluate(
                    """({motion, sceneIrs}) => {
                      document.body.style.setProperty('--motion-bg', motion.composition.background);
                      const stage = document.querySelector('#stage');
                      sceneIrs.forEach((item, index) => {
                        const layer = document.createElement('div');
                        layer.className = 'motion-layer';
                        layer.dataset.index = String(index);
                        layer.style.display = 'none';
                        const target = document.createElement('div');
                        target.className = 'motion-ir';
                        layer.appendChild(target);
                        stage.appendChild(layer);
                        window.IRRenderer.renderIR(target, item.ir, {
                          fit: false,
                          viewport: motion.scenes[index].viewport,
                        });
                        const inner = target.querySelector('[data-design-width]');
                        const artWidth = Number(inner?.dataset.designWidth) || 1440;
                        const scale = motion.composition.width / artWidth;
                        target.style.transform = `scale(${scale})`;
                        target.style.width = `${artWidth}px`;
                      });
                      window.__motionSetFrame = ({sceneIndex, previousIndex, transition, progress}) => {
                        const layers = [...document.querySelectorAll('.motion-layer')];
                        layers.forEach(layer => {
                          layer.style.display = 'none'; layer.style.opacity = '1';
                          layer.style.transform = 'none';
                        });
                        const current = layers[sceneIndex];
                        const previous = previousIndex >= 0 ? layers[previousIndex] : null;
                        current.style.display = 'block';
                        if (!previous || transition === 'cut') return;
                        previous.style.display = 'block';
                        if (transition === 'fade') {
                          current.style.opacity = String(progress);
                          previous.style.opacity = String(1 - progress);
                        } else if (transition === 'slide-left') {
                          current.style.transform = `translateX(${(1 - progress) * 100}%)`;
                          previous.style.transform = `translateX(${-progress * 100}%)`;
                        } else if (transition === 'slide-up') {
                          current.style.transform = `translateY(${(1 - progress) * 100}%)`;
                          previous.style.transform = `translateY(${-progress * 100}%)`;
                        } else if (transition === 'zoom') {
                          current.style.opacity = String(progress);
                          current.style.transform = `scale(${0.92 + 0.08 * progress})`;
                          previous.style.opacity = String(1 - progress);
                          previous.style.transform = `scale(${1 + 0.04 * progress})`;
                        }
                      };
                    }""",
                    {"motion": motion, "sceneIrs": scene_irs},
                )
                page.evaluate(
                    """async () => {
                      const assetsReady = (async () => {
                        if (document.fonts?.ready) await document.fonts.ready;
                        await Promise.all([...document.images].map(image => image.complete
                          ? Promise.resolve()
                          : new Promise(resolve => { image.onload = image.onerror = resolve; })));
                      })();
                      await Promise.race([assetsReady, new Promise(resolve => setTimeout(resolve, 5000))]);
                    }"""
                )
                for index in range(count):
                    page.evaluate("state => window.__motionSetFrame(state)", frame_state(motion, index))
                    frame = page.screenshot(type="png", animations="disabled", caret="hide")
                    if not process.stdin:
                        raise RuntimeError("video encoder stdin is unavailable")
                    process.stdin.write(frame)
                    if on_progress:
                        on_progress(index + 1, count)
            finally:
                browser.close()
        if process.stdin:
            process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
        if return_code:
            raise RuntimeError(stderr.strip() or f"video encoder exited with {return_code}")
        temporary.replace(output)
        return {
            "path": str(output),
            "format": output_format,
            "frames": count,
            "fps": int(motion["composition"]["fps"]),
            "width": int(motion["composition"]["width"]),
            "height": int(motion["composition"]["height"]),
            "duration": int(motion["composition"]["duration"]),
            "bytes": output.stat().st_size,
        }
    except Exception:
        if process.poll() is None:
            process.kill()
        if temporary.exists():
            temporary.unlink()
        raise
