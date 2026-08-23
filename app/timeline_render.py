"""Детерминированный рендер Timeline IR: видео (headless Chromium + ffmpeg)
и экспорт веб-анимации (CSS @keyframes / Web Animations API).

Рендер использует тот же движок, что редактор: ``engine.js`` рендерит дизайн
один раз, дальше на каждый кадр работает только ``Timeline.solveLayer``
(композитные свойства), поэтому ролик совпадает с превью.

Экспорт использует Python-зеркало солвера (паритет с engine/timeline.ts
проверяется тестами): для трансформаций кейфреймы вычисляются семплированием
решённых значений (кусочно-линейная аппроксимация кривых), прозрачность
переносится с исходными изингами 1:1.
"""
from __future__ import annotations

import copy
import json
import math
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

MAX_RENDER_FRAMES = 10_800
RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

# --------------------------------------------------------------------------
# Python-зеркало солвера (паритет с frontend/src/engine/timeline.ts)
# --------------------------------------------------------------------------

EASING_BEZIERS = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
}

DEFAULTS = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}


def _cubic_bezier_y(x1: float, y1: float, x2: float, y2: float, progress: float) -> float:
    if progress <= 0:
        return 0.0
    if progress >= 1:
        return 1.0
    cx = 3 * x1
    bx = 3 * (x2 - x1) - cx
    ax = 1 - cx - bx
    cy = 3 * y1
    by = 3 * (y2 - y1) - cy
    ay = 1 - cy - by

    def sample_x(u: float) -> float:
        return ((ax * u + bx) * u + cx) * u

    def sample_y(u: float) -> float:
        return ((ay * u + by) * u + cy) * u

    def sample_dx(u: float) -> float:
        return (3 * ax * u + 2 * bx) * u + cx

    u = progress
    for _ in range(8):
        x = sample_x(u) - progress
        if abs(x) < 1e-6:
            return sample_y(u)
        d = sample_dx(u)
        if abs(d) < 1e-6:
            break
        u -= x / d
        u = min(1.0, max(0.0, u))
    lo, hi = 0.0, 1.0
    u = progress
    while hi - lo > 1e-6:
        if sample_x(u) < progress:
            lo = u
        else:
            hi = u
        u = (lo + hi) / 2
    return sample_y(u)


def easing_progress(easing: str | None, bezier: list | None, progress: float) -> float:
    if progress <= 0:
        return 0.0
    if progress >= 1:
        return 1.0
    name = easing or "linear"
    if name == "linear":
        return progress
    if name == "cubic-bezier":
        points = tuple(bezier[:4]) if isinstance(bezier, list) and len(bezier) == 4 else EASING_BEZIERS["ease-in-out"]
    else:
        points = EASING_BEZIERS.get(name, EASING_BEZIERS["ease-in-out"])
    return _cubic_bezier_y(points[0], points[1], points[2], points[3], progress)


def solve_track(track: dict | None, t: float, fallback: float) -> float:
    kfs = track.get("keyframes") if isinstance(track, dict) else None
    if not kfs:
        return fallback
    if t <= kfs[0]["t"]:
        return float(kfs[0]["value"])
    last = kfs[-1]
    if t >= last["t"]:
        return float(last["value"])
    for a, b in zip(kfs, kfs[1:]):
        if a["t"] <= t <= b["t"]:
            if b["t"] == a["t"]:
                return float(b["value"])
            progress = (t - a["t"]) / (b["t"] - a["t"])
            eased = easing_progress(a.get("easing"), a.get("bezier"), progress)
            return float(a["value"]) + (float(b["value"]) - float(a["value"])) * eased
    return float(last["value"])


def solve_layer(layer: dict, t: float) -> dict:
    props = (layer.get("transform") or {}).get("properties") or {}
    return {
        "x": solve_track(props.get("x"), t, DEFAULTS["x"]),
        "y": solve_track(props.get("y"), t, DEFAULTS["y"]),
        "scale": max(0.0, solve_track(props.get("scale"), t, DEFAULTS["scale"])),
        "rotation": solve_track(props.get("rotation"), t, DEFAULTS["rotation"]),
        "opacity": min(1.0, max(0.0, solve_track(props.get("opacity"), t, DEFAULTS["opacity"]))),
        "visible": layer.get("in", 0) <= t <= layer.get("out", 0),
    }


def _transform_css(state: dict) -> str:
    return (
        f"translate3d({state['x']:.3f}px, {state['y']:.3f}px, 0) "
        f"rotate({state['rotation']:.4f}deg) scale({state['scale']:.6f})"
    )


# --------------------------------------------------------------------------
# Экспорт веб-анимации: CSS @keyframes и WAAPI
# --------------------------------------------------------------------------

def _animated_layers(timeline: dict) -> list[dict]:
    out = []
    for layer in timeline.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        props = (layer.get("transform") or {}).get("properties") or {}
        if any((props.get(name) or {}).get("keyframes") for name in ("x", "y", "scale", "rotation", "opacity")):
            out.append(layer)
    return out


def export_css(timeline: dict) -> str:
    """CSS @keyframes на слой. Трансформации — семплы решённых значений
    (шаг 100 мс): кусочно-линейная кривая совпадает с движком в точках семплов;
    прозрачность переносится с исходными изингами."""
    duration = int(timeline["composition"]["duration"])
    lines = ["/* DesignDNA Timeline export — CSS keyframes */"]
    for layer in _animated_layers(timeline):
        layer_id = str(layer["id"])
        props = (layer.get("transform") or {}).get("properties") or {}
        animations = []
        if any((props.get(name) or {}).get("keyframes") for name in ("x", "y", "scale", "rotation")):
            step = max(50, min(200, duration // 60)) if duration else 100
            times = list(range(0, duration + 1, step))
            if times[-1] != duration:
                times.append(duration)
            kf_lines = []
            for t in times:
                state = solve_layer(layer, t)
                pct = 0 if duration == 0 else t / duration * 100
                kf_lines.append(f"  {pct:.3f}% {{ transform: {_transform_css(state)}; }}")
            name = f"tl-{layer_id}-transform"
            lines.append(f"@keyframes {name} {{\n" + "\n".join(kf_lines) + "\n}")
            animations.append(f"{name} {duration}ms linear both")
        opacity_track = props.get("opacity") or {}
        if opacity_track.get("keyframes"):
            kf_lines = []
            for kf in opacity_track["keyframes"]:
                pct = 0 if duration == 0 else int(kf["t"]) / duration * 100
                easing = kf.get("easing") or "linear"
                kf_lines.append(
                    f"  {pct:.3f}% {{ opacity: {float(kf['value']):.4f}; "
                    f"animation-timing-function: {easing if easing != 'cubic-bezier' else 'ease-in-out'}; }}")
            name = f"tl-{layer_id}-opacity"
            lines.append(f"@keyframes {name} {{\n" + "\n".join(kf_lines) + "\n}")
            animations.append(f"{name} {duration}ms linear both")
        selector = f'[data-timeline-layer="{layer_id}"]'
        lines.append(f"{selector} {{ animation: {', '.join(animations)}; will-change: transform, opacity; }}")
        lines.append(f"{selector} {{ animation-fill-mode: both; }}")
    return "\n".join(lines) + "\n"


def export_waapi(timeline: dict) -> dict:
    """Рецепт для Web Animations API: element.animate(keyframes, {duration})."""
    duration = int(timeline["composition"]["duration"])
    layers_out = []
    for layer in _animated_layers(timeline):
        layer_id = str(layer["id"])
        props = (layer.get("transform") or {}).get("properties") or {}
        keyframes = []
        if any((props.get(name) or {}).get("keyframes") for name in ("x", "y", "scale", "rotation")):
            step = max(50, min(200, duration // 60)) if duration else 100
            times = list(range(0, duration + 1, step))
            if times[-1] != duration:
                times.append(duration)
            for t in times:
                state = solve_layer(layer, t)
                keyframes.append({
                    "offset": 0 if duration == 0 else round(t / duration, 6),
                    "transform": _transform_css(state),
                    "easing": "linear",
                })
        opacity_track = props.get("opacity") or {}
        if opacity_track.get("keyframes"):
            for kf in opacity_track["keyframes"]:
                keyframes.append({
                    "offset": 0 if duration == 0 else round(int(kf["t"]) / duration, 6),
                    "opacity": round(float(kf["value"]), 4),
                    "easing": kf.get("easing") or "linear",
                })
        keyframes.sort(key=lambda item: item["offset"])
        layers_out.append({
            "id": layer_id,
            "in": int(layer.get("in") or 0),
            "out": int(layer.get("out") or 0),
            "keyframes": keyframes,
        })
    return {
        "duration": duration,
        "fps": int(timeline["composition"]["fps"]),
        "width": int(timeline["composition"]["width"]),
        "height": int(timeline["composition"]["height"]),
        "layers": layers_out,
    }


# --------------------------------------------------------------------------
# Видео-рендер: headless Chromium + покадровый скриншот + ffmpeg
# --------------------------------------------------------------------------

def frame_count(duration_ms: int, fps: int) -> int:
    return max(1, math.ceil(max(0, duration_ms) * max(1, fps) / 1000))


def _ffmpeg_command(output: Path, fps: int, count: int, output_format: str, quality: str) -> list[str]:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "png", "-framerate", str(fps), "-i", "pipe:0",
        "-an", "-frames:v", str(count), "-map_metadata", "-1", "-fflags", "+bitexact",
        "-threads", "1",
    ]
    if output_format == "webm":
        crf = {"draft": "38", "high": "28", "lossless": "0"}[quality]
        command += ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-row-mt", "0"]
        if quality == "lossless":
            command += ["-lossless", "1"]
    else:
        crf = {"draft": "28", "high": "18", "lossless": "0"}[quality]
        pixel_format = "yuv444p" if quality == "lossless" else "yuv420p"
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", crf,
                    "-pix_fmt", pixel_format, "-movflags", "+faststart"]
    command.append(str(output))
    return command


def validate_timeline_render(timeline: dict, design_ir: dict) -> tuple[int, int]:
    composition = timeline.get("composition") or {}
    count = frame_count(int(composition.get("duration") or 0), int(composition.get("fps") or 30))
    if count > MAX_RENDER_FRAMES:
        raise ValueError(f"render exceeds the {MAX_RENDER_FRAMES} frame limit")
    if int(composition.get("width") or 0) % 2 or int(composition.get("height") or 0) % 2:
        raise ValueError("video composition width and height must be even")
    if not isinstance(design_ir, dict) or not design_ir.get("tree"):
        raise ValueError("Design IR with a tree is required for render")
    return count, int(composition.get("fps") or 30)


def _layer_marks(timeline: dict, design_ir: dict) -> list[dict]:
    """Соответствие слой → индекс секции в дереве (для data-ir-sec)."""
    keys_to_index: dict[str, int] = {}
    for index, section in enumerate(design_ir.get("tree") or []):
        if not isinstance(section, dict):
            continue
        if section.get("sourceKey"):
            keys_to_index[str(section["sourceKey"])] = index
        if section.get("id"):
            keys_to_index[str(section["id"])] = index
    marks = []
    for layer in timeline.get("layers") or []:
        if not isinstance(layer, dict) or layer.get("type") != "component":
            continue
        index = keys_to_index.get(str(layer.get("ref") or ""))
        if index is not None:
            marks.append({"layerId": str(layer["id"]), "secIndex": index})
    return marks


def render_timeline_video(
    timeline: dict,
    design_ir: dict,
    output: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Покадровый рендер таймлайна тем же движком, что превью редактора."""
    count, fps = validate_timeline_render(timeline, design_ir)
    composition = timeline["composition"]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.stem}.part{output.suffix}")
    if temporary.exists():
        temporary.unlink()

    command = _ffmpeg_command(temporary, fps, count, output.suffix.lstrip(".").lower() or "mp4", "high")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={
                    "width": int(composition["width"]),
                    "height": int(composition["height"]),
                }, device_scale_factor=1)
                page.set_content(
                    '<style>html,body,#stage{margin:0;width:100%;height:100%;overflow:hidden}'
                    '.timeline-host{position:absolute;left:0;top:0;transform-origin:top left}</style>'
                    '<div id="stage"><div class="timeline-host" id="host"></div></div>'
                )
                page.add_script_tag(path=str(Path(__file__).resolve().parent / "static" / "flow" / "engine.js"))
                page.evaluate(
                    """({timeline, designIr, marks}) => {
                      const host = document.querySelector('#host');
                      window.IRRenderer.renderIR(host, designIr, { fit: false, viewport: 'desktop' });
                      const inner = host.querySelector('[data-design-width]');
                      const artWidth = Number(inner?.dataset.designWidth) || 1440;
                      const scale = timeline.composition.width / artWidth;
                      host.style.width = artWidth + 'px';
                      host.style.transform = `scale(${scale})`;
                      marks.forEach((mark) => {
                        const el = host.querySelector(`[data-ir-sec="${mark.secIndex}"]`);
                        if (el) {
                          el.setAttribute('data-timeline-layer', mark.layerId);
                          el.style.willChange = 'transform, opacity';
                        }
                      });
                      const engine = new window.TimelineEngine(timeline);
                      window.__timelineSeek = (t) => {
                        window.Timeline.applySolvedToDom(host, engine.seek(t));
                      };
                      window.__timelineSeek(0);
                    }""",
                    {"timeline": timeline, "designIr": design_ir, "marks": _layer_marks(timeline, design_ir)},
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
                    page.evaluate("t => window.__timelineSeek(t)", index * 1000 / fps)
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
            "format": output.suffix.lstrip("."),
            "frames": count,
            "fps": fps,
            "width": int(composition["width"]),
            "height": int(composition["height"]),
            "duration": int(composition["duration"]),
            "bytes": output.stat().st_size,
        }
    except Exception:
        if process.poll() is None:
            process.kill()
        if temporary.exists():
            temporary.unlink()
        raise


# --------------------------------------------------------------------------
# Очередь задач рендера (исполняется в отдельном воркере, статусы — в API)
# --------------------------------------------------------------------------

def submit_render(render_id: str, timeline: dict, design_ir: dict, output: Path) -> None:
    def runner() -> None:
        with JOBS_LOCK:
            job = JOBS.get(render_id)
            if job is not None:
                job["status"] = "running"
        try:
            def progress(done: int, total: int) -> None:
                with JOBS_LOCK:
                    current = JOBS.get(render_id)
                    if current is not None:
                        current["framesDone"] = done
                        current["framesTotal"] = total
                        current["progress"] = round(done / max(1, total), 3)
            result = render_timeline_video(timeline, design_ir, output, on_progress=progress)
            with JOBS_LOCK:
                job = JOBS.get(render_id)
                if job is not None:
                    job.update({"status": "complete", "progress": 1.0, "result": result})
        except Exception as exc:  # noqa: BLE001 — статус задачи важнее типа ошибки
            with JOBS_LOCK:
                job = JOBS.get(render_id)
                if job is not None:
                    job.update({"status": "error", "error": str(exc)})

    RENDER_EXECUTOR.submit(runner)


def register_job(render_id: str, total_frames: int, output_format: str, output: Path) -> dict:
    job = {
        "id": render_id,
        "status": "queued",
        "progress": 0.0,
        "framesDone": 0,
        "framesTotal": total_frames,
        "format": output_format,
        "filename": f"designdna-timeline-{render_id[:8]}.{output_format}",
        "output": output,
    }
    with JOBS_LOCK:
        JOBS[render_id] = job
    return job
