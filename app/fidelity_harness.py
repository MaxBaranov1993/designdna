"""Fidelity harness: честное сравнение отрендеренного IR со скриншотом источника.

Каждый захваченный IR рендерится тем же движком (app/static/flow/engine.js),
что и редактор, в точном размере соответствующего viewport — без ресайза
изображений. Reference (element-screenshot блока при capture) и render
сравниваются только когда их размеры равны; расхождение размеров — честный
провал метрик, а не LANCZOS-подгонка.

Метрики на блок × viewport:
  pixel_similarity  — доля пикселей с per-channel |diff| < 24, 0-100
  region_diffs      — сетка 8×8, регионы с mismatch > 10%
  bbox_mean/p95/max — ошибка bbox листьев IR против замеренного DOM
  grid_origin_error — смещение корня секции в рендере от начала контейнера
  paint_coverage    — доля покрашенной площади источника, покрытая IR-слоями
  visual_losses     — потерянные визуальные каналы (explained/unexplained)

Gate (все обязательные метрики должны существовать): origin <= 2px,
paint >= 95, similarity >= 85, нет необъяснённых потерянных визуалов.
Явный selectable raster fallback разрешён явно.

CLI:
  .venv/Scripts/python app/fidelity_harness.py https://example.com/page --out results/run-1
  .venv/Scripts/python app/fidelity_harness.py --fixture chess_arena.html --out results/fixture
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import sys
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
RENDERER_JS = APP_DIR / "static" / "flow" / "engine.js"
FIXTURES_DIR = APP_DIR / "fixtures"

CHANNEL_TOLERANCE = 24          # per-channel допуск пиксельного сходства
REGION_GRID = 8                 # сетка регионов для region_diffs
REGION_MISMATCH_PCT = 10.0      # регион «расходится», если mismatch больше
UNMATCHED_BOX_PENALTY = 100.0   # штраф за лист без совпадения в рендере

GATE_THRESHOLDS = {
    "max_origin_error_px": 2.0,
    "min_paint_coverage": 95.0,
    "min_pixel_similarity": 85.0,
    # bbox p95: structural drift leaf→render; фантомные leafBox у implicit-текстов
    # убраны в компиляторе, так что это честный порог (текст-heavy шапки ~3-4px)
    "max_bbox_p95_px": 12.0,
}
REQUIRED_METRICS = (
    "pixel_similarity", "bbox_mean", "bbox_p95", "bbox_max",
    "grid_origin_error", "paint_coverage", "unexplained_losses",
)
# Потерянный визуальный канал объяснён только реальным locked raster слоем
# (editable:false image с фактическим src) с тем же sourceKey — reason-only
# whitelist (background-image/pseudo) не принимается.

DEFAULT_VIEWPORTS = [
    {"name": "desktop", "width": 1440, "height": 900},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 390, "height": 844},
]


# ---------- чистая логика гейта (без браузера) ----------

def is_raster_fallback(ir: dict) -> bool:
    """Блок целиком — явный locked raster fallback (image-слои со скриншотом
    источника). Строгая форма: каждая секция tree непуста, и КАЖДЫЙ child —
    type == "image" с фактическим непустым src, editable is False и
    sourceMeta.reason == "raster-fallback", без собственных children. Любая
    лишняя секция, лишний/не-image child, пустой src или неверный type
    отклоняют IR: смешанный блок метрик не избегает."""
    if not isinstance(ir, dict):
        return False
    tree = ir.get("tree") or []
    if not tree:
        return False
    for section in tree:
        if not isinstance(section, dict):
            return False
        children = section.get("children") or []
        if not children:
            return False
        for child in children:
            if not isinstance(child, dict):
                return False
            if child.get("type") != "image":
                return False
            if not str(child.get("src") or ""):
                return False
            if child.get("editable") is not False:
                return False
            if (child.get("sourceMeta") or {}).get("reason") != "raster-fallback":
                return False
            if child.get("children"):
                return False
    return True


def _locked_raster_keys(ir: dict) -> set[str]:
    """sourceKeys явных selectable locked raster слоёв: editable:false image
    с фактическим raster-содержимым (src). Только такой слой объясняет потерю
    визуального канала с тем же sourceKey."""
    keys: set[str] = set()

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if (node.get("editable") is False and node.get("type") == "image"
                and str(node.get("src") or "")):
            key = str(node.get("sourceKey") or "")
            if key:
                keys.add(key)
        for child in node.get("children") or []:
            walk(child)

    for section in (ir or {}).get("tree") or []:
        walk(section)
    return keys


def visual_losses(item: dict, viewport: str) -> list[dict]:
    """Потерянные визуальные каналы viewport: extras/dropped с visual:true.

    explained=True — канал представлен в IR явным selectable editable:false
    raster-слоем с тем же sourceKey (canvas/iframe/... snapshot). Всё остальное —
    необъяснённая потеря, валящая gate.
    """
    raster_keys = _locked_raster_keys(item.get("ir") if isinstance(item.get("ir"), dict) else {})
    losses: list[dict] = []
    extras = (item.get("extras_by_viewport") or {}).get(viewport) or []
    for entry in extras:
        if not isinstance(entry, dict) or not entry.get("visual"):
            continue
        reason = str(entry.get("reason") or "")
        source_key = str(entry.get("sourceKey") or "")
        losses.append({"kind": "extra", "sourceKey": source_key,
                       "reason": reason, "explained": source_key in raster_keys})
    dropped = (item.get("dropped_by_viewport") or {}).get(viewport) or []
    for entry in dropped:
        if not isinstance(entry, dict) or not entry.get("visual"):
            continue
        reason = str(entry.get("reason") or "")
        source_key = str(entry.get("sourceKey") or "")
        losses.append({"kind": "dropped", "sourceKey": source_key,
                       "reason": reason, "explained": source_key in raster_keys})
    return losses


def viewport_gate(metrics: dict | None) -> dict:
    """Gate одного viewport: все метрики обязаны существовать, пороги жёсткие."""
    if not isinstance(metrics, dict):
        return {"passed": False, "reasons": ["no metrics"]}
    reasons = [f"missing metric: {key}" for key in REQUIRED_METRICS if metrics.get(key) is None]
    if reasons:
        return {"passed": False, "reasons": reasons}
    if float(metrics["grid_origin_error"]) > GATE_THRESHOLDS["max_origin_error_px"]:
        reasons.append(f"grid origin error {metrics['grid_origin_error']}px > "
                       f"{GATE_THRESHOLDS['max_origin_error_px']}px")
    if float(metrics["paint_coverage"]) < GATE_THRESHOLDS["min_paint_coverage"]:
        reasons.append(f"paint coverage {metrics['paint_coverage']} < "
                       f"{GATE_THRESHOLDS['min_paint_coverage']}")
    if float(metrics["pixel_similarity"]) < GATE_THRESHOLDS["min_pixel_similarity"]:
        reasons.append(f"pixel similarity {metrics['pixel_similarity']} < "
                       f"{GATE_THRESHOLDS['min_pixel_similarity']}")
    if float(metrics["bbox_p95"]) > GATE_THRESHOLDS["max_bbox_p95_px"]:
        reasons.append(f"bbox p95 {metrics['bbox_p95']}px > "
                       f"{GATE_THRESHOLDS['max_bbox_p95_px']}px")
    if int(metrics["unexplained_losses"]) > 0:
        reasons.append(f"{metrics['unexplained_losses']} unexplained lost visuals")
    return {"passed": not reasons, "reasons": reasons}


def evaluate_gate(report: dict | None) -> dict:
    """Gate блока (viewports) или агрегата (blocks). Fail-closed по умолчанию."""
    if not isinstance(report, dict):
        return {"passed": False, "reasons": ["no fidelity report"]}
    if report.get("raster_fallback"):
        return {"passed": True, "reasons": ["explicit raster fallback"]}
    if isinstance(report.get("blocks"), list):
        if not report["blocks"]:
            # пустой агрегат (все блоки упали с ошибкой capture) — fail-closed
            return {"passed": False, "reasons": ["no blocks in fidelity report"]}
        reasons = []
        for block in report["blocks"]:
            gate = evaluate_gate(block)
            reasons.extend(f"[{block.get('name') or block.get('selector') or '?'}] {r}"
                           for r in gate["reasons"])
        return {"passed": not reasons, "reasons": reasons}
    viewports = report.get("viewports") or {}
    if not viewports:
        return {"passed": False, "reasons": ["no viewport metrics"]}
    reasons = []
    for name, metrics in viewports.items():
        reasons.extend(f"[{name}] {r}" for r in viewport_gate(metrics)["reasons"])
    return {"passed": not reasons, "reasons": reasons}


# ---------- измерения (браузер) ----------

def _decode_data_url(data_url: str) -> bytes:
    _head, b64 = data_url.split(",", 1)
    return base64.b64decode(b64)


def _inline_font_face_css(ir: dict) -> str:
    """Resolve captured /fonts assets for the about:blank harness page.

    The product renderer normally runs under the app origin, where /fonts is
    routable. The harness uses set_content(), so relative font URLs otherwise
    fail silently and measure fallback glyphs instead of the captured font.
    """
    rules: list[str] = []
    for face in (ir.get("meta") or {}).get("fontFaces") or []:
        family = str(face.get("family") or "")
        weight = str(face.get("weight") or "")
        style = str(face.get("style") or "")
        url = str(face.get("url") or "")
        unicode_range = str(face.get("unicodeRange") or "")
        if not re.fullmatch(r"[A-Za-z0-9 ._-]{1,80}", family):
            continue
        if not re.fullmatch(r"(?:[1-9]00(?: [1-9]00)?|normal|bold)", weight):
            continue
        if style not in ("normal", "italic", "oblique") or not url.startswith("/fonts/"):
            continue
        if unicode_range and not re.fullmatch(r"[Uu+0-9A-Fa-f? ,\-]{1,2048}", unicode_range):
            continue
        filename = url.rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", filename):
            continue
        path = ROOT / "data" / "fonts" / filename
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        mime = "font/woff2" if suffix == ".woff2" else "font/woff" if suffix == ".woff" else "font/ttf"
        fmt = "woff2" if suffix == ".woff2" else "woff" if suffix == ".woff" else "truetype"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        unicode_rule = f"unicode-range:{unicode_range};" if unicode_range else ""
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
            f"{unicode_rule}src:url('data:{mime};base64,{payload}') format('{fmt}');font-display:block;}}")
    return "\n".join(rules)


def _render_block_png(page, ir: dict, viewport_name: str, width: int, height: int) -> bytes:
    """Отрисовать IR движком редактора в точном размере viewport и вернуть PNG.

    Viewport страницы выставляется в размер захваченного viewport, контейнер —
    в ширину блока; вариант responsive IR выбирается явно по имени viewport.
    """
    page.set_viewport_size({"width": max(240, int(width)), "height": max(320, int(height))})
    page.set_content(f'<div id="preview" style="width:{int(width)}px"></div>')
    page.add_script_tag(path=str(RENDERER_JS))
    page.evaluate(
        "(args) => window.IRRenderer.renderIR(document.querySelector('#preview'), args.ir,"
        " {viewport: args.viewport})",
        {"ir": ir, "viewport": viewport_name})
    inline_fonts = _inline_font_face_css(ir)
    if inline_fonts:
        page.add_style_tag(content=inline_fonts)
    page.wait_for_selector('[data-ir-sec="0"]', timeout=5000)
    # fitPreview выставляет высоту контейнера в requestAnimationFrame
    page.wait_for_function("() => document.querySelector('#preview').style.height !== ''",
                           timeout=5000)
    # The renderer returns before remote images and webfonts necessarily finish.
    # A screenshot taken at that point measures network timing, not IR fidelity.
    # Wait for the same deterministic paint barrier used during source capture.
    page.evaluate("""() => Promise.all([
      (document.fonts && document.fonts.ready) ? document.fonts.ready.catch(() => {}) : Promise.resolve(),
      Promise.all(Array.from(document.images || []).map(img =>
        img.complete && img.naturalWidth > 0
          ? Promise.resolve()
          : (img.decode ? img.decode() : new Promise(resolve => {
              img.addEventListener('load', resolve, {once:true});
              img.addEventListener('error', resolve, {once:true});
            })).catch(() => {})))
    ]).then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))""")
    return page.locator("#preview").screenshot(type="png")


def _image_metrics(reference_png: bytes, render_png: bytes) -> dict:
    """Сравнение равных по размеру образов: similarity, region diffs, diff PNG."""
    import numpy as np
    from PIL import Image

    ref = Image.open(io.BytesIO(reference_png)).convert("RGB")
    got = Image.open(io.BytesIO(render_png)).convert("RGB")
    result: dict = {"reference_size": [ref.width, ref.height],
                    "render_size": [got.width, got.height],
                    "size_match": ref.size == got.size,
                    "pixel_similarity": None, "region_diffs": None, "diff_png": None}
    ref_buf = io.BytesIO()
    ref.save(ref_buf, format="PNG")  # reference приезжает JPEG; артефакт — PNG
    result["reference_png"] = ref_buf.getvalue()
    if ref.size != got.size:
        return result  # без ресайза: неравные размеры — честный провал метрики
    diff = np.abs(np.asarray(got, dtype=np.int16) - np.asarray(ref, dtype=np.int16))
    match = (diff < CHANNEL_TOLERANCE).all(axis=2)
    result["pixel_similarity"] = round(float(match.mean()) * 100, 2)

    height, width = match.shape
    regions = []
    # Целочисленное разбиение покрывает каждый пиксель, включая remainder
    # строки/колонки, когда размер не делится на REGION_GRID.
    for row in range(REGION_GRID):
        y0, y1 = height * row // REGION_GRID, height * (row + 1) // REGION_GRID
        for col in range(REGION_GRID):
            x0, x1 = width * col // REGION_GRID, width * (col + 1) // REGION_GRID
            cell = match[y0:y1, x0:x1]
            if cell.size == 0:
                continue
            mismatch = round(float((~cell).mean()) * 100, 2)
            if mismatch > REGION_MISMATCH_PCT:
                regions.append({"region": [row, col], "mismatch_pct": mismatch})
    result["region_diffs"] = regions

    amplified = np.clip(diff * 4, 0, 255).astype(np.uint8)
    amplified[~match] = [255, 0, 0]  # расходящиеся пиксели — красным
    buf = io.BytesIO()
    Image.fromarray(amplified).save(buf, format="PNG")
    result["diff_png"] = buf.getvalue()
    return result


def _bbox_metrics(page, leaf_boxes: list[dict]) -> dict | None:
    """Ошибки bbox листьев IR против замеренного DOM + grid-origin смещение."""
    try:
        measured = page.evaluate("""() => {
          const preview = document.querySelector('#preview');
          const sec = document.querySelector('[data-ir-sec="0"]');
          if (!preview || !sec) return null;
          const base = preview.getBoundingClientRect();
          const root = sec.getBoundingClientRect();
          const boxes = {};
          sec.querySelectorAll('[data-ir-path]').forEach(el => {
            const r = el.getBoundingClientRect();
            boxes[el.getAttribute('data-ir-path')] = {
              x: Math.round(r.left - root.left), y: Math.round(r.top - root.top),
              width: Math.round(r.width), height: Math.round(r.height)};
          });
          return {origin: {x: root.left - base.left, y: root.top - base.top}, boxes};
        }""")
    except Exception:
        return None
    if not measured:
        return None
    origin = measured.get("origin") or {}
    grid_origin_error = round(max(abs(float(origin.get("x", 0))), abs(float(origin.get("y", 0)))), 2)
    rendered = measured.get("boxes") or {}
    diffs: list[float] = []
    matched = 0
    for box in leaf_boxes or []:
        ref = rendered.get(str(box.get("sourceKey") or ""))
        if ref:
            matched += 1
            diffs.append(max(
                abs(float(box.get("x", 0)) - ref["x"]),
                abs(float(box.get("y", 0)) - ref["y"]),
                abs(float(box.get("width", 0)) - ref["width"]),
                abs(float(box.get("height", 0)) - ref["height"]),
            ))
        else:
            diffs.append(max(float(box.get("width", UNMATCHED_BOX_PENALTY)),
                             float(box.get("height", UNMATCHED_BOX_PENALTY)),
                             UNMATCHED_BOX_PENALTY))
    total = len(leaf_boxes or [])
    if not diffs:
        return {"grid_origin_error": grid_origin_error,
                "bbox_mean": None, "bbox_p95": None, "bbox_max": None,
                "bbox_matched": 0, "bbox_unmatched": 0, "bbox_total": 0}
    diffs.sort()
    p95_idx = max(0, int(math.ceil(0.95 * len(diffs))) - 1)
    return {"grid_origin_error": grid_origin_error,
            "bbox_mean": round(sum(diffs) / len(diffs), 2),
            "bbox_p95": round(float(diffs[p95_idx]), 2),
            "bbox_max": round(float(diffs[-1]), 2),
            "bbox_matched": matched, "bbox_unmatched": total - matched,
            "bbox_total": total}


def evaluate_capture_item(item: dict, page, artifacts_dir: Path | None = None,
                          artifact_prefix: str = "block") -> dict:
    """Метрики и артефакты для одной записи capture_block_irs по всем viewport."""
    ir = item.get("ir") if isinstance(item.get("ir"), dict) else None
    raster = is_raster_fallback(ir)
    report: dict = {"raster_fallback": raster, "viewports": {}}
    previews = item.get("previews") or {}
    sizes = item.get("sizes") or {}
    for name in sorted(previews):
        preview = str(previews.get(name) or "")
        size = sizes.get(name) or {}
        metrics: dict = {key: None for key in REQUIRED_METRICS}
        metrics["visual_losses"] = visual_losses(item, name)
        metrics["unexplained_losses"] = sum(1 for loss in metrics["visual_losses"]
                                            if not loss["explained"])
        paint = (item.get("paint_coverage") or {}).get(name)
        metrics["paint_coverage"] = float(paint) if paint is not None else None
        metrics["artifacts"] = {}
        leaf_boxes = (item.get("leaf_boxes_by_viewport") or {}).get(name) or []
        if (ir is not None and not raster and preview.startswith("data:image")
                and size.get("width") and size.get("height")):
            try:
                shot = _render_block_png(page, ir, name, int(size["width"]), int(size["height"]))
                images = _image_metrics(_decode_data_url(preview), shot)
                metrics["pixel_similarity"] = images["pixel_similarity"]
                metrics["region_diffs"] = images["region_diffs"]
                metrics["reference_size"] = images["reference_size"]
                metrics["render_size"] = images["render_size"]
                metrics["size_match"] = images["size_match"]
                bbox = _bbox_metrics(page, leaf_boxes)
                if bbox:
                    metrics.update(bbox)
                if artifacts_dir is not None:
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    stem = f"{artifact_prefix}-{name}"
                    ref_path = artifacts_dir / f"{stem}-reference.png"
                    render_path = artifacts_dir / f"{stem}-render.png"
                    ref_path.write_bytes(images.get("reference_png") or _decode_data_url(preview))
                    render_path.write_bytes(shot)
                    metrics["artifacts"] = {"reference": str(ref_path), "render": str(render_path)}
                    if images["diff_png"]:
                        diff_path = artifacts_dir / f"{stem}-diff.png"
                        diff_path.write_bytes(images["diff_png"])
                        metrics["artifacts"]["diff"] = str(diff_path)
            except Exception as e:  # метрики остаются None → gate честно падает
                metrics["harness_error"] = str(e)
        metrics["gate"] = viewport_gate(metrics)
        report["viewports"][name] = metrics
    report["gate"] = evaluate_gate(report)
    return report


def evaluate_captures(captured: dict, artifacts_dir: Path | None = None) -> dict:
    """Прогон harness по результату capture_block_irs: selector → report.

    Один Chromium на все блоки. Ошибочные блоки пропускаются; ошибка отдельного
    блока даёт fail-closed report без метрик, а не исключение.
    """
    import re

    jobs = {selector: item for selector, item in captured.items()
            if isinstance(item, dict) and not item.get("error") and isinstance(item.get("ir"), dict)}
    reports: dict = {}
    if not jobs:
        return reports
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            for selector, item in jobs.items():
                prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", selector.strip("#.")) or "block"
                try:
                    reports[selector] = evaluate_capture_item(item, page, artifacts_dir, prefix)
                except Exception as e:
                    reports[selector] = {"raster_fallback": False, "viewports": {},
                                         "gate": {"passed": False,
                                                  "reasons": [f"harness error: {e}"]}}
        finally:
            browser.close()
    return reports


# ---------- top-level: capture + оценка + report ----------

def run(url: str, blocks: list[dict] | None = None, viewports: list[dict] | None = None,
        artifacts_dir: Path | None = None, timeout_ms: int = 20000) -> dict:
    """Capture URL → fidelity report по каждому блоку и viewport.

    Harness ничего не пишет в кэш: импорт и кэш-гейтинг живут в blockparse.
    """
    import scraper

    if blocks is None:
        import blockparse
        html = blockparse.rendered_html(url)
        blocks = blockparse.detect_blocks(html)
    captured = scraper.capture_block_irs(url, blocks, viewports=viewports, timeout_ms=timeout_ms)
    reports = evaluate_captures(captured, artifacts_dir)
    names = {b["selector"]: b.get("name") or b["selector"] for b in blocks}
    report = {
        "url": url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": GATE_THRESHOLDS,
        "required_metrics": list(REQUIRED_METRICS),
        "blocks": [
            {"name": names.get(selector, selector), "selector": selector, **reports[selector]}
            for selector in reports
        ],
        "errors": {selector: item["error"] for selector, item in captured.items()
                   if isinstance(item, dict) and item.get("error")
                   and not blockparse._is_hidden_block_error(item.get("error"))},
    }
    report["gate"] = evaluate_gate({"blocks": report["blocks"]})
    if report["errors"]:
        # блок с ошибкой захвата не должен проходить гейт молча — раньше
        # ошибки печатались, но не влияли на verdict
        report["gate"] = {
            "passed": False,
            "reasons": report["gate"]["reasons"] + [
                f"[{selector}] capture error: {str(err)[:140]}"
                for selector, err in report["errors"].items()
            ],
        }
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "fidelity-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _parse_viewport(spec: str) -> dict:
    name, _, dims = spec.partition(":")
    width, _, height = dims.partition("x")
    return {"name": name, "width": int(width), "height": int(height)}


def _fixture_url(fixture: str):
    """Локальный 127.0.0.1 сервер фикстур с test-only транспортом (SSRF-гард
    продакшена не ослабляется: monkeypatch живёт только в этом процессе)."""
    import httpx
    import scraper
    from urlguard import PublicHttpResponse

    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 partial(SimpleHTTPRequestHandler, directory=str(FIXTURES_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def _local_fetcher(url: str, *, timeout: float, headers=None,
                       max_bytes: int, max_redirects: int = 5) -> PublicHttpResponse:
        with httpx.Client(timeout=timeout, headers=headers, trust_env=False) as client:
            response = client.get(url, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > max_bytes:
                raise ValueError(f"fixture response exceeds {max_bytes} bytes")
            return PublicHttpResponse(url=str(response.url), status_code=response.status_code,
                                      headers=dict(response.headers), content=response.content)

    scraper.validate_public_url = lambda _url: None
    scraper.fetch_public_bytes = _local_fetcher
    return f"http://127.0.0.1:{server.server_port}/{fixture}", server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fidelity harness: IR render vs source pixels")
    parser.add_argument("url", nargs="?", help="URL страницы для capture")
    parser.add_argument("--fixture", help="HTML-фикстура из app/fixtures (локальный сервер)")
    parser.add_argument("--block", action="append", default=[],
                        help="name=selector; по умолчанию — автодетект блоков")
    parser.add_argument("--viewport", action="append", default=[],
                        help="name:WxH; по умолчанию desktop/tablet/mobile")
    parser.add_argument("--out", type=Path, default=None,
                        help="каталог артефактов (reference/render/diff + fidelity-report.json)")
    args = parser.parse_args(argv)

    server = None
    url = args.url
    if args.fixture:
        url, server = _fixture_url(args.fixture)
    if not url:
        parser.error("нужен url или --fixture")

    blocks = None
    if args.block:
        blocks = [{"name": spec.partition("=")[0], "selector": spec.partition("=")[2]}
                  for spec in args.block]
    viewports = [_parse_viewport(spec) for spec in args.viewport] or None
    out = args.out
    if out is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = ROOT / "results" / f"fidelity-{stamp}"
    try:
        report = run(url, blocks=blocks, viewports=viewports, artifacts_dir=out)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    for block in report["blocks"]:
        for name, metrics in sorted((block.get("viewports") or {}).items()):
            gate = metrics.get("gate") or {}
            status = "OK  " if gate.get("passed") else "FAIL"
            print(f"[{status}] {block['name']}/{name}: "
                  f"similarity={metrics.get('pixel_similarity')} "
                  f"paint={metrics.get('paint_coverage')} "
                  f"origin={metrics.get('grid_origin_error')} "
                  f"bbox_max={metrics.get('bbox_max')} "
                  f"unexplained_losses={metrics.get('unexplained_losses')}")
            for reason in gate.get("reasons") or []:
                print(f"       - {reason}")
    for selector, error in (report.get("errors") or {}).items():
        print(f"[FAIL] {selector}: capture error: {error}")
    gate = report["gate"]
    print(f"gate: {'PASSED' if gate['passed'] else 'FAILED'}; artifacts: {out}")
    for reason in gate["reasons"]:
        print(f"  - {reason}")
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
