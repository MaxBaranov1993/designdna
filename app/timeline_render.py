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
import math
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

from timeline_assets import (
    MaterializedAsset,
    install_render_asset_guard,
    materialize_render_assets,
    promote_oversized_data_urls,
    rewrite_local_asset_urls,
)
from config import settings

MAX_RENDER_FRAMES = 10_800

# Офлайн-документ рендера: зарезервированный несуществующий TLD .invalid —
# даже при сломанном гарде запрос не уйдёт в сеть. Все ассеты исполняются
# гардом из материализованных локальных байтов.
RENDER_DOCUMENT_URL = "https://render.timeline.invalid/document"
RENDER_DOCUMENT_HTML = (
    '<style>html,body,#stage{margin:0;width:100%;height:100%;overflow:hidden}'
    '.timeline-host{position:absolute;left:0;top:0;transform-origin:top left}'
    '.timeline-camera{position:absolute;inset:0;transform-origin:50% 50%}</style>'
    '<div id="stage"><div class="timeline-camera" data-timeline-camera>'
    '<div class="timeline-host" id="host"></div></div></div>'
)

# Детерминированный запасной Inter: мердж токенов по умолчанию всегда просит
# Inter, поэтому офлайн-рендер материализует его из собранных ассетов
# приложения (интер в продукте идёт из @fontsource/inter в статике билда).
_APP_ROOT = settings.app_dir()
_APP_STATIC_ASSETS = _APP_ROOT / "static" / "flow" / "_app" / "immutable" / "assets"
_INTER_FILE_RE = re.compile(r"^inter-(latin|cyrillic|latin-ext|cyrillic-ext)-(400|500|600)-normal\.[A-Za-z0-9_-]+\.woff2$")
_INTER_SUBSET_RANGE = {
    "latin": "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    "cyrillic": "U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "latin-ext": "U+0100-02AF, U+0304, U+0308, U+0329, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
    "cyrillic-ext": "U+0460-052F, U+1C80-1C8A, U+20B4, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
}

# Очередь рендера ограничена: один воркер + небольшая очередь. Всё, что
# сверх, отклоняется на входе (429), а завершённые задачи вытесняются по TTL
# вместе с файлами на диске — память и каталог renders не растут бесконечно.
MAX_ACTIVE_RENDERS = 4
# Верхняя граница параллельных Chromium-воркеров одного рендера.
MAX_RENDER_WORKERS = 4
JOB_TTL_SECONDS = 3600
RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


class RenderCancelled(RuntimeError):
    """Рендер остановлен запросом отмены (браузер и ffmpeg закрыты чисто)."""


def _clock() -> float:
    """Монотонное время задачи; в тестах подменяется для проверки TTL."""
    return time.monotonic()

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

DEFAULTS = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0, "blur": 0.0, "clip": 0.0}


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
        "blur": max(0.0, solve_track(props.get("blur"), t, DEFAULTS["blur"])),
        "clip": min(100.0, max(0.0, solve_track(props.get("clip"), t, DEFAULTS["clip"]))),
        "visible": layer.get("in", 0) <= t <= layer.get("out", 0),
    }


def _filter_css(state: dict) -> str:
    return f"blur({state['blur']:.3f}px)" if state.get("blur", 0) > 0.001 else "none"


def _clip_css(state: dict) -> str:
    return f"inset(0 0 {state['clip']:.3f}% 0)" if state.get("clip", 0) > 0.001 else "none"


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
        if any((props.get(name) or {}).get("keyframes") for name in ("x", "y", "scale", "rotation", "opacity", "blur", "clip")):
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
        has_blur = bool((props.get("blur") or {}).get("keyframes"))
        has_clip = bool((props.get("clip") or {}).get("keyframes"))
        if any((props.get(name) or {}).get("keyframes") for name in ("x", "y", "scale", "rotation", "blur", "clip")):
            step = max(50, min(200, duration // 60)) if duration else 100
            times = list(range(0, duration + 1, step))
            if times[-1] != duration:
                times.append(duration)
            kf_lines = []
            for t in times:
                state = solve_layer(layer, t)
                pct = 0 if duration == 0 else t / duration * 100
                extra = f" filter: {_filter_css(state)};" if has_blur else ""
                extra += f" clip-path: {_clip_css(state)};" if has_clip else ""
                kf_lines.append(f"  {pct:.3f}% {{ transform: {_transform_css(state)};{extra} }}")
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
        lines.append(f"{selector} {{ animation: {', '.join(animations)}; will-change: transform, opacity{', filter' if has_blur else ''}; }}")
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
        has_blur = bool((props.get("blur") or {}).get("keyframes"))
        has_clip = bool((props.get("clip") or {}).get("keyframes"))
        if any((props.get(name) or {}).get("keyframes") for name in ("x", "y", "scale", "rotation", "blur", "clip")):
            step = max(50, min(200, duration // 60)) if duration else 100
            times = list(range(0, duration + 1, step))
            if times[-1] != duration:
                times.append(duration)
            for t in times:
                state = solve_layer(layer, t)
                item = {
                    "offset": 0 if duration == 0 else round(t / duration, 6),
                    "transform": _transform_css(state),
                    "easing": "linear",
                }
                if has_blur:
                    item["filter"] = _filter_css(state)
                if has_clip:
                    item["clipPath"] = _clip_css(state)
                keyframes.append(item)
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


def _builtin_inter_faces() -> tuple[list[dict], dict[str, MaterializedAsset]]:
    """Запасной Inter из собранных ассетов приложения (офлайн-детерминизм).

    Дефолтные токены рендерера всегда просят Inter; без локальных файлов он
    дрейфнул бы на системный фолбэк. Возвращает лица для инжекта в
    ``meta.fontFaces`` и карту ассетов для гарда; пусто, если статика билда
    не найдена (тогда дрейф будет явно отказан проверкой готовности).
    """
    faces: list[dict] = []
    assets: dict[str, MaterializedAsset] = {}
    if not _APP_STATIC_ASSETS.is_dir():
        return faces, assets
    found: dict[tuple[str, str], Path] = {}
    for path in sorted(_APP_STATIC_ASSETS.iterdir()):
        match = _INTER_FILE_RE.match(path.name)
        if match:
            found[(match.group(1), match.group(2))] = path
    if not any(subset == "latin" for subset, _weight in found):
        return faces, assets
    weights = sorted({weight for _subset, weight in found})
    for subset in ("latin", "cyrillic", "latin-ext", "cyrillic-ext"):
        for weight in weights:
            path = found.get((subset, weight))
            if path is None:
                continue
            url = f"/fonts/inter-fallback-{subset}-{weight}.woff2"
            data = path.read_bytes()
            assets[url] = MaterializedAsset(url=url, data=data, mime="font/woff2", source=str(path))
            faces.append({
                "family": "Inter", "weight": weight, "style": "normal",
                "url": url, "unicodeRange": _INTER_SUBSET_RANGE[subset],
            })
            if weight == "600":
                # дефолтные токены просят display-700: детерминированно
                # декларируем 600-файл весом 700
                faces.append({
                    "family": "Inter", "weight": "700", "style": "normal",
                    "url": url, "unicodeRange": _INTER_SUBSET_RANGE[subset],
                })
    return faces, assets


def _design_needs_inter(design_ir: dict) -> bool:
    """Нужен ли рендеру Inter: токены по умолчанию, явные токены или стили."""
    tokens = design_ir.get("tokens") if isinstance(design_ir.get("tokens"), dict) else None
    font = (tokens or {}).get("font") if isinstance((tokens or {}).get("font"), dict) else None
    if not isinstance(font, dict) or not font.get("display") or not font.get("body"):
        return True  # mergeDefaults движка подставит Inter

    def family_of(entry) -> str:
        return str((entry or {}).get("family") or "").strip().lower() if isinstance(entry, dict) else ""

    if family_of(font.get("display")) in ("", "inter") or family_of(font.get("body")) in ("", "inter"):
        return True

    def walk(node) -> bool:
        if not isinstance(node, dict):
            return False
        style = node.get("style")
        if isinstance(style, dict) and "inter" in str(style.get("fontFamily") or "").lower():
            return True
        for child in node.get("children") or []:
            if walk(child):
                return True
        return False

    return any(walk(section) for section in (design_ir.get("tree") or []) if isinstance(section, dict))


def _local_inter_declared(design_ir: dict) -> bool:
    meta = design_ir.get("meta") if isinstance(design_ir.get("meta"), dict) else None
    faces = (meta or {}).get("fontFaces") if isinstance(meta, dict) else None
    if not isinstance(faces, list):
        return False
    return any(
        isinstance(face, dict) and str(face.get("family") or "").strip().lower() == "inter"
        for face in faces)


_READINESS_JS = """async () => {
  // ленивые картинки обязаны загрузиться до нулевого кадра
  document.querySelectorAll('img[loading]').forEach((img) => { img.loading = 'eager'; });
  const errors = [];
  const settle = (async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    await Promise.all([...document.images].map((img) => img.complete
      ? Promise.resolve()
      : new Promise((resolve) => { img.onload = img.onerror = () => resolve(); })));
  })();
  let timedOut = false;
  await Promise.race([settle, new Promise((resolve) => setTimeout(() => { timedOut = true; resolve(); }, 15000))]);
  if (timedOut) errors.push('fonts/images not ready within 15 seconds');
  const loadedFamilies = new Set();
  try {
    for (const face of document.fonts || []) {
      if (face.status === 'error') {
        errors.push('font-face did not load (file missing or corrupted): ' + face.family + ' weight=' + (face.weight || '?'));
      } else if (face.status === 'loaded') {
        loadedFamilies.add(face.family);
      }
    }
  } catch (e) { errors.push('document.fonts unavailable: ' + String(e)); }
  const SYSTEM = new Set(['arial', 'helvetica', 'verdana', 'tahoma', 'trebuchet ms', 'georgia',
    'times new roman', 'courier new', 'segoe ui', 'sf pro display', 'sf pro text', 'serif',
    'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif', 'ui-sans-serif',
    'ui-monospace', 'ui-rounded']);
  const needed = new Set();
  document.querySelectorAll('*').forEach((el) => {
    if (el.children.length || !(el.textContent || '').trim()) return;
    const primary = String(getComputedStyle(el).fontFamily || '').split(',')[0].replace(/['"]/g, '').trim().toLowerCase();
    if (primary && !SYSTEM.has(primary)) needed.add(primary);
  });
  const declared = new Set();
  try {
    for (const face of document.fonts || []) {
      declared.add(String(face.family || '').replace(/['"]/g, '').trim().toLowerCase());
    }
  } catch (e) { /* пустой набор */ }
  // A family installed in the OS (imported sites use Comic Sans MS, Georgia,
  // Bradley Hand, ...) needs no @font-face: it renders identically offline.
  // Detect it by measuring text against two generic fallbacks — an unknown
  // family collapses to the fallback width, an installed one differs.
  const installedLocally = (family) => {
    try {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      if (!ctx) return false;
      const sample = 'mmmmmmmmmmlli1WWWQQ@';
      const widths = ['monospace', 'serif', 'sans-serif'].map((generic) => {
        ctx.font = '32px ' + generic;
        const base = ctx.measureText(sample).width;
        ctx.font = '32px "' + family + '", ' + generic;
        return Math.abs(ctx.measureText(sample).width - base) > 0.5;
      });
      return widths.every(Boolean);
    } catch (e) { return false; }
  };
  for (const family of needed) {
    // check() returns true for undeclared families too (nothing to load), so
    // drift is detected by a missing @font-face, readiness by check().
    if (!declared.has(family)) {
      if (installedLocally(family)) { loadedFamilies.add(family); continue; }
      errors.push('font "' + family + '" is unavailable offline: add a local font (meta.fontFaces, /fonts/<name>) instead of an external catalog');
      continue;
    }
    let ok = false;
    try { ok = !!(document.fonts && document.fonts.check('16px "' + family + '"')); } catch (e) { ok = false; }
    if (!ok) errors.push('font "' + family + '" is declared but did not load (file missing or corrupted)');
  }
  let imagesLoaded = 0;
  for (const img of document.images) {
    const src = img.currentSrc || img.src || '';
    if (!src) continue;
    if (img.complete && img.naturalWidth > 0) { imagesLoaded++; continue; }
    errors.push('изображение не загружено: ' + String(src).slice(0, 200));
  }
  return { errors, fontsLoaded: [...loadedFamilies], imagesLoaded };
}"""


def render_timeline_video(
    timeline: dict,
    design_ir: dict,
    output: Path,
    on_progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    data_dir: Path | None = None,
    workers: int | None = None,
) -> dict:
    """Покадровый офлайн-рендер таймлайна тем же движком, что превью редактора.

    Детерминизм: ноль внешних запросов — ассеты материализуются из локальных
    хранилищ (контент-адресные блобы с полным SHA-256, локальные шрифты с
    проверкой скреперного sha1-префикса имени), исполняются через Playwright
    route.fulfill, готовность шрифтов/картинок проверяется ДО нулевого кадра,
    а ЛЮБОЙ заблокированный запрос, дрейф на фолбэк-шрифт или битый ассет
    валят рендер с человекочитаемой причиной — даже если остальная готовность
    в порядке (fail closed).

    ``should_cancel`` опрашивается между кадрами: отмена поднимает
    ``RenderCancelled``, браузер закрывается, ffmpeg убивается, временный
    файл удаляется — хвостов не остаётся.

    ``workers`` > 1 режет кадры на смежные сегменты, каждый рендерится своим
    Chromium и ffmpeg, затем сегменты склеиваются без перекодирования
    (``_concat_segments``). Кадры идентичны одиночному режиму; отмена или
    ошибка одного воркера останавливает остальные.
    """
    design_ir = promote_oversized_data_urls(design_ir, data_dir=data_dir)
    assets, asset_errors = materialize_render_assets(design_ir, data_dir)
    render_timeline = copy.deepcopy(timeline)
    for source_page in (render_timeline.get("story") or {}).get("pages", []):
        source_page["ir"] = promote_oversized_data_urls(source_page["ir"], data_dir=data_dir)
        page_assets, page_errors = materialize_render_assets(source_page["ir"], data_dir)
        assets.update(page_assets)
        asset_errors.extend(page_errors)
        page_ir = rewrite_local_asset_urls(source_page["ir"])
        if _design_needs_inter(page_ir) and not _local_inter_declared(page_ir):
            faces, fonts = _builtin_inter_faces()
            page_ir.setdefault("meta", {})["fontFaces"] = list(page_ir.get("meta", {}).get("fontFaces") or []) + faces
            assets.update(fonts)
        source_page["ir"] = page_ir
    if asset_errors:
        raise ValueError("render assets failed validation: " + "; ".join(asset_errors[:3]))
    count, fps = validate_timeline_render(timeline, design_ir)
    composition = timeline["composition"]

    render_ir = rewrite_local_asset_urls(design_ir)
    if _design_needs_inter(render_ir) and not _local_inter_declared(render_ir):
        fallback_faces, fallback_assets = _builtin_inter_faces()
        if fallback_faces:
            meta = render_ir.setdefault("meta", {})
            meta["fontFaces"] = list(meta.get("fontFaces") or []) + fallback_faces
            assets.update(fallback_assets)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.stem}.part{output.suffix}")
    if temporary.exists():
        temporary.unlink()

    output_format = output.suffix.lstrip(".").lower() or "mp4"
    worker_count = _worker_count(count, workers)
    segments = _frame_segments(count, worker_count)
    blocked: list[str] = []
    stop = threading.Event()
    progress_lock = threading.Lock()
    done_frames = [0]

    def report(rendered: int) -> None:
        if on_progress is None:
            return
        with progress_lock:
            done_frames[0] += rendered
            on_progress(done_frames[0], count)

    def cancelled() -> bool:
        return stop.is_set() or (should_cancel is not None and should_cancel())

    setup = {"timeline": render_timeline, "designIr": render_ir, "marks": _layer_marks(timeline, design_ir)}
    segment_files = [temporary if worker_count == 1 else temporary.with_name(f"{output.stem}.seg{index}{output.suffix}")
                     for index in range(len(segments))]
    for path in segment_files:
        if path.exists():
            path.unlink()
    succeeded = False
    results: list[dict | None] = [None] * len(segments)
    try:
        if worker_count == 1:
            results[0] = _render_segment(segments[0], segment_files[0], setup, assets, blocked, fps, count,
                                         output_format, composition, cancelled, report)
        else:
            errors: list[BaseException] = []

            def run(index: int) -> None:
                try:
                    results[index] = _render_segment(segments[index], segment_files[index], setup, assets, blocked,
                                                     fps, count, output_format, composition, cancelled, report)
                except BaseException as exc:  # noqa: BLE001 — ошибка воркера останавливает остальных
                    errors.append(exc)
                    stop.set()

            threads = [threading.Thread(target=run, args=(index,), name=f"timeline-render-{index}", daemon=True)
                       for index in range(len(segments))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if errors:
                cancel_errors = [exc for exc in errors if isinstance(exc, RenderCancelled)]
                raise (cancel_errors[0] if cancel_errors and len(cancel_errors) == len(errors) else errors[0])
            _concat_segments(segment_files, temporary, output_format)
        readiness = results[0] or {}
        temporary.replace(output)
        succeeded = True
        return {
            "path": str(output),
            "format": output_format,
            "frames": count,
            "fps": fps,
            "width": int(composition["width"]),
            "height": int(composition["height"]),
            "duration": int(composition["duration"]),
            "bytes": output.stat().st_size,
            "workers": worker_count,
            "assets": {
                "fontsLoaded": sorted(set(readiness.get("fontsLoaded") or [])),
                "imagesLoaded": int(readiness.get("imagesLoaded") or 0),
                "blockedRequests": blocked[:5],
            },
        }
    finally:
        stop.set()
        for path in segment_files:
            if path != temporary and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
        if not succeeded and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _worker_count(count: int, requested: int | None) -> int:
    """Число параллельных Chromium-воркеров: явный параметр, затем
    DESIGNDNA_RENDER_WORKERS, затем автоматика — один воркер для коротких
    роликов (накладные расходы на запуск браузера не окупаются) и до трёх для
    длинных. Каждый воркер держит свой Chromium и свой ffmpeg."""
    if requested is None:
        raw = os.environ.get("DESIGNDNA_RENDER_WORKERS", "").strip()
        if raw.isdigit() and int(raw) > 0:
            requested = int(raw)
    if requested is None:
        requested = 1 if count < 90 else min(3, max(1, (os.cpu_count() or 2) // 2))
    return max(1, min(MAX_RENDER_WORKERS, requested, count))


def _frame_segments(count: int, workers: int) -> list[tuple[int, int]]:
    """Смежные диапазоны кадров [first, last) для воркеров, длины отличаются не более чем на 1."""
    workers = max(1, min(workers, count))
    base, extra = divmod(count, workers)
    segments: list[tuple[int, int]] = []
    first = 0
    for index in range(workers):
        last = first + base + (1 if index < extra else 0)
        segments.append((first, last))
        first = last
    return segments


def _render_segment(segment: tuple[int, int], target: Path, setup: dict, assets: dict, blocked: list[str],
                    fps: int, total: int, output_format: str, composition: dict,
                    cancelled: Callable[[], bool], report: Callable[[int], None]) -> dict:
    """Отрендерить диапазон кадров в отдельный файл своим Chromium и ffmpeg.

    Готовность ассетов проверяется в каждом воркере до его первого кадра;
    заблокированные запросы попадают в общий список ``blocked`` и, как и в
    одиночном режиме, валят рендер (fail closed).
    """
    first, last = segment
    command = _ffmpeg_command(target, fps, last - first, output_format, "high")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    readiness: dict = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={
                    "width": int(composition["width"]),
                    "height": int(composition["height"]),
                }, device_scale_factor=1)
                # Полный офлайн: документ и ассеты — только из материализованных
                # байтов, любой другой запрос абортируется и запоминается.
                install_render_asset_guard(context, assets, blocked,
                                           RENDER_DOCUMENT_URL, RENDER_DOCUMENT_HTML)
                page = context.new_page()
                page.goto(RENDER_DOCUMENT_URL)
                page.add_script_tag(path=str(_APP_ROOT / "static" / "flow" / "engine.js"))
                page.evaluate(_SETUP_JS, setup)
                readiness = page.evaluate(_READINESS_JS)
                problems = [str(item) for item in (readiness.get("errors") or [])]
                if blocked:
                    # Fail closed на ЛЮБОМ заблокированном запросе, даже если
                    # шрифты/картинки иначе готовы: сама попытка выйти в сеть —
                    # нарушение детерминизма, обнаруженное до нулевого кадра.
                    problems.append(
                        "render attempted a network request (" + "; ".join(blocked[:3])
                        + ") — offline rendering accepts only local content-addressed assets")
                if problems:
                    raise ValueError("render assets not ready: " + "; ".join(problems[:5]))
                for index in range(first, last):
                    if cancelled():
                        raise RenderCancelled(f"render cancelled at frame {index + 1}/{total}")
                    page.evaluate("t => window.__timelineSeek(t)", index * 1000 / fps)
                    frame = page.screenshot(type="png", animations="disabled", caret="hide")
                    if not process.stdin:
                        raise RuntimeError("video encoder stdin is unavailable")
                    process.stdin.write(frame)
                    report(1)
            finally:
                # Браузер закрывается на любом выходе, включая отмену.
                browser.close()
        if process.stdin:
            process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
        if return_code:
            raise RuntimeError(stderr.strip() or f"video encoder exited with {return_code}")
        return readiness
    finally:
        # Чистый выход для успеха, ошибки и отмены: сначала закрываем stdin
        # (иначе ffmpeg ждёт кадры), затем дожидаемся процесса, чтобы не
        # оставлять зомби.
        if process.poll() is None:
            if process.stdin:
                try:
                    process.stdin.close()
                except Exception:  # noqa: BLE001 — канал мог умереть вместе с процессом
                    pass
            process.kill()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass


def _concat_segments(segment_files: list[Path], target: Path, output_format: str) -> None:
    """Склеить сегменты без перекодирования (одинаковые параметры кодека)."""
    listing = target.with_name(f"{target.stem}.segments.txt")
    listing.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_files), encoding="utf-8")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-map_metadata", "-1", "-fflags", "+bitexact",
    ]
    if output_format != "webm":
        command += ["-movflags", "+faststart"]
    command.append(str(target))
    try:
        completed = subprocess.run(command, capture_output=True, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip()
                               or f"segment concat exited with {completed.returncode}")
    finally:
        try:
            listing.unlink()
        except OSError:
            pass


_SETUP_JS = """({timeline, designIr, marks}) => {
  const host = document.querySelector('#host');
  if (timeline.story) {
    const player = new window.VideoStoryPlayer(host, timeline, true);
    window.__timelineSeek = (t) => player.seek(t);
    window.__timelineSeek(0);
    return;
  }
  window.IRRenderer.renderIR(host, designIr, { fit: false, viewport: 'desktop', offline: true });
  // офлайн-рендер не ходит в каталог внешних шрифтов: локальные
  // лица уже инжектнуты, ссылка движка гасится до запроса
  const catalogLink = document.getElementById('ir-fonts');
  if (catalogLink) catalogLink.removeAttribute('href');
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
}"""


# --------------------------------------------------------------------------
# Очередь задач рендера (исполняется в отдельном воркере, статусы — в API)
# --------------------------------------------------------------------------

TERMINAL_STATUSES = ("complete", "error", "cancelled")


def _evict_expired_locked() -> None:
    """Вытеснить завершённые задачи старше TTL (вместе с файлами на диске).

    Вызывается под JOBS_LOCK на входе/статусе — очередь и каталог renders
    остаются ограниченными без отдельного фонового сборщика.
    """
    now = _clock()
    expired = [
        render_id for render_id, job in JOBS.items()
        if job.get("status") in TERMINAL_STATUSES
        and now - float(job.get("updatedAt") or job.get("createdAt") or now) > JOB_TTL_SECONDS
    ]
    for render_id in expired:
        job = JOBS.pop(render_id, None)
        if not job:
            continue
        output = job.get("output")
        if output:
            try:
                Path(output).unlink(missing_ok=True)
            except OSError:
                pass


def active_render_count_locked() -> int:
    return sum(1 for job in JOBS.values() if job.get("status") in ("queued", "running"))


def register_job(render_id: str, total_frames: int, output_format: str, output: Path) -> dict | None:
    """Зарегистрировать задачу. ``None`` — очередь полна (зовущий вернёт 429)."""
    with JOBS_LOCK:
        _evict_expired_locked()
        if active_render_count_locked() >= MAX_ACTIVE_RENDERS:
            return None
        now = _clock()
        job = {
            "id": render_id,
            "status": "queued",
            "progress": 0.0,
            "framesDone": 0,
            "framesTotal": total_frames,
            "format": output_format,
            "filename": f"designdna-timeline-{render_id[:8]}.{output_format}",
            "output": output,
            "createdAt": now,
            "updatedAt": now,
            "cancelRequested": False,
        }
        JOBS[render_id] = job
        return job


def request_cancel(render_id: str) -> str | None:
    """Запросить отмену. Возвращает новый статус или причину отказа."""
    with JOBS_LOCK:
        job = JOBS.get(render_id)
        if job is None:
            return None
        status = job.get("status")
        if status in TERMINAL_STATUSES:
            return f"conflict:{status}"
        if status == "queued":
            job.update({"status": "cancelled", "cancelRequested": True, "updatedAt": _clock()})
            return "cancelled"
        job["cancelRequested"] = True
        job["updatedAt"] = _clock()
        return "cancelling"


def evict_expired_jobs() -> None:
    with JOBS_LOCK:
        _evict_expired_locked()


def submit_render(render_id: str, timeline: dict, design_ir: dict, output: Path) -> None:
    def runner() -> None:
        with JOBS_LOCK:
            job = JOBS.get(render_id)
            if job is None or job.get("status") == "cancelled":
                return  # отменено до старта воркера
            job.update({"status": "running", "updatedAt": _clock()})

        def should_cancel() -> bool:
            with JOBS_LOCK:
                current = JOBS.get(render_id)
                return bool(current and current.get("cancelRequested"))

        def progress(done: int, total: int) -> None:
            with JOBS_LOCK:
                current = JOBS.get(render_id)
                if current is not None:
                    current["framesDone"] = done
                    current["framesTotal"] = total
                    current["progress"] = round(done / max(1, total), 3)

        try:
            result = render_timeline_video(
                timeline, design_ir, output, on_progress=progress, should_cancel=should_cancel)
            with JOBS_LOCK:
                job = JOBS.get(render_id)
                if job is not None:
                    job.update({"status": "complete", "progress": 1.0, "result": result,
                                "updatedAt": _clock()})
        except RenderCancelled as exc:
            with JOBS_LOCK:
                job = JOBS.get(render_id)
                if job is not None:
                    job.update({"status": "cancelled", "error": str(exc), "updatedAt": _clock()})
        except Exception as exc:  # noqa: BLE001 — статус задачи важнее типа ошибки
            with JOBS_LOCK:
                job = JOBS.get(render_id)
                if job is not None:
                    job.update({"status": "error", "error": str(exc), "updatedAt": _clock()})

    RENDER_EXECUTOR.submit(runner)
