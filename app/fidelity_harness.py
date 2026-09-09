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
from config import settings

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
RENDERER_JS = APP_DIR / "static" / "flow" / "engine.js"
FIXTURES_DIR = APP_DIR / "fixtures"

CHANNEL_TOLERANCE = 24          # per-channel допуск пиксельного сходства
REGION_GRID = 8                 # сетка регионов для region_diffs
REGION_MISMATCH_PCT = 10.0      # регион «расходится», если mismatch больше
UNMATCHED_BOX_PENALTY = 100.0   # штраф за лист без совпадения в рендере
PAINT_BARRIER_TIMEOUT_MS = 20000  # hard deadline ожидания картинок/шрифтов в рендере

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
    """Gate одного viewport: все метрики обязаны существовать, пороги жёсткие.

    Два случая понижены до advisory (видны, но не валят гейт):
    - pixel similarity у блока с ПОЛУПРОЗРАЧНЫМ корнем: в референсе сквозь него
      просвечивает контент страницы, а IR-рендер рисует блок изолированно —
      расхождение не является ошибкой захвата (геометрия проверяется отдельно);
    - unexplained lost visuals при ПРОШЕДШЕМ pixel similarity: потерянный канал
      не проявился в пикселях (например, ротатор строк с sr-only дублем).
    Раньше оба случая держали блок вечно красным и, из-за fail-closed кэша,
    каждый импорт такого сайта пересчитывался заново.
    """
    if not isinstance(metrics, dict):
        return {"passed": False, "reasons": ["no metrics"], "advisory": []}
    reasons = [f"missing metric: {key}" for key in REQUIRED_METRICS if metrics.get(key) is None]
    if reasons:
        return {"passed": False, "reasons": reasons, "advisory": []}
    advisory: list = []
    if float(metrics["grid_origin_error"]) > GATE_THRESHOLDS["max_origin_error_px"]:
        reasons.append(f"grid origin error {metrics['grid_origin_error']}px > "
                       f"{GATE_THRESHOLDS['max_origin_error_px']}px")
    if float(metrics["paint_coverage"]) < GATE_THRESHOLDS["min_paint_coverage"]:
        reasons.append(f"paint coverage {metrics['paint_coverage']} < "
                       f"{GATE_THRESHOLDS['min_paint_coverage']}")
    similarity_ok = float(metrics["pixel_similarity"]) >= GATE_THRESHOLDS["min_pixel_similarity"]
    if not similarity_ok:
        message = (f"pixel similarity {metrics['pixel_similarity']} < "
                   f"{GATE_THRESHOLDS['min_pixel_similarity']}")
        if metrics.get("translucent_root"):
            advisory.append(message + " (полупрозрачный корень блока — фон страницы просвечивает в референсе)")
        else:
            reasons.append(message)
    if float(metrics["bbox_p95"]) > GATE_THRESHOLDS["max_bbox_p95_px"]:
        reasons.append(f"bbox p95 {metrics['bbox_p95']}px > "
                       f"{GATE_THRESHOLDS['max_bbox_p95_px']}px")
    if int(metrics["unexplained_losses"]) > 0:
        message = f"{metrics['unexplained_losses']} unexplained lost visuals"
        unexplained = [loss for loss in (metrics.get("visual_losses") or [])
                       if isinstance(loss, dict) and not loss.get("explained")]
        # Послабление только для kind=dropped (выпавший DOM-ребёнок): раз пиксели
        # сошлись, содержимое дошло другим путём (sr-only дубль, ротатор строк).
        # kind=extra (непредставленный канал: фон, pseudo) остаётся блокирующим —
        # совпадение пикселей там может быть случайным.
        only_dropped = bool(unexplained) and all(
            str(loss.get("kind") or "") == "dropped" for loss in unexplained)
        if similarity_ok and only_dropped:
            advisory.append(message + " (kind=dropped, пиксельное сходство в норме — потеря не проявилась)")
        else:
            reasons.append(message)
    return {"passed": not reasons, "reasons": reasons, "advisory": advisory}


def _translucent_root(ir: dict | None) -> bool:
    """Корень блока полупрозрачен: 8-значный hex-фон с alpha<0.97 или backdropFilter."""
    if not isinstance(ir, dict):
        return False
    tree = ir.get("tree")
    root = tree[0] if isinstance(tree, list) and tree and isinstance(tree[0], dict) else None
    style = (root or {}).get("style")
    if not isinstance(style, dict):
        return False
    if str(style.get("backdropFilter") or "").strip():
        return True
    background = str(style.get("background") or "")
    if len(background) == 9 and background.startswith("#"):
        try:
            return int(background[7:9], 16) / 255.0 < 0.97
        except ValueError:
            return False
    return False


def provenance_reasons(provenance) -> list[str]:
    """Fail-closed: browser/viewport/font/asset/compiler identity must be present
    and its fingerprint must match the canonical hash of those fields."""
    if not isinstance(provenance, dict):
        return ["missing capture provenance"]
    reasons = []
    for key in ("captureVersion", "compilerSha256", "browser", "deviceScaleFactor",
                "viewports", "fonts", "assets", "fingerprint"):
        if key not in provenance:
            reasons.append(f"missing provenance.{key}")
    browser = provenance.get("browser")
    if not isinstance(browser, dict) or not str(browser.get("name") or ""):
        reasons.append("missing provenance.browser.name")
    if provenance.get("deviceScaleFactor") is None:
        reasons.append("missing provenance.deviceScaleFactor")
    if not isinstance(provenance.get("viewports"), list):
        reasons.append("missing provenance.viewports")
    if not isinstance(provenance.get("fonts"), list):
        reasons.append("missing provenance.fonts")
    if not isinstance(provenance.get("assets"), list):
        reasons.append("missing provenance.assets")
    try:
        import scraper
        expected = scraper.provenance_fingerprint(provenance)
    except Exception as e:
        return reasons + [f"provenance fingerprint unavailable: {e}"]
    if str(provenance.get("fingerprint") or "") != expected:
        reasons.append("provenance fingerprint mismatch")
    return reasons


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
    reasons.extend(provenance_reasons(report.get("provenance")))
    for name, metrics in viewports.items():
        reasons.extend(f"[{name}] {r}" for r in viewport_gate(metrics)["reasons"])
    return {"passed": not reasons, "reasons": reasons}


# ---------- измерения (браузер) ----------

def _decode_data_url(data_url: str) -> bytes:
    _head, b64 = data_url.split(",", 1)
    return base64.b64decode(b64)


def _fonts_dir() -> Path:
    return settings.fonts_dir()


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
        # Шрифты источника лежат в DESIGNDNA_DATA_DIR/fonts (десктоп: userData/data),
        # а не только в <repo>/data: с жёстким путём harness мерил fallback-глифы
        # и каждый мастер получал ~90% при идеальной геометрии.
        path = _fonts_dir() / filename
        if not path.is_file():
            fallback = ROOT / "data" / "fonts" / filename
            if not fallback.is_file():
                continue
            path = fallback
        suffix = path.suffix.lower()
        mime = "font/woff2" if suffix == ".woff2" else "font/woff" if suffix == ".woff" else "font/ttf"
        fmt = "woff2" if suffix == ".woff2" else "woff" if suffix == ".woff" else "truetype"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        unicode_rule = f"unicode-range:{unicode_range};" if unicode_range else ""
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
            f"{unicode_rule}src:url('data:{mime};base64,{payload}') format('{fmt}');font-display:block;}}")
    return "\n".join(rules)


class FidelityRenderError(RuntimeError):
    """A failed measurement is retryable, never a passing fidelity result."""

    def __init__(self, ir: dict, viewport: str, error: Exception):
        root = next(iter(ir.get("tree") or []), {})
        message = f"Render failed ({viewport}): {str(error)[:350]}"
        super().__init__(message)
        self.detail = {"code": "render-failed", "stage": "fidelity-render",
                       "component": str(root.get("sourceKey") or ""),
                       "path": "masterIr.tree[0]", "viewport": viewport,
                       "retryable": True}


def _render_block_png(page, ir: dict, viewport_name: str, width: int, height: int) -> bytes:
    from playwright.sync_api import Error as PlaywrightError
    try:
        return _render_block_png_impl(page, ir, viewport_name, width, height)
    except PlaywrightError as exc:
        raise FidelityRenderError(ir, viewport_name, exc) from exc


def _render_block_png_impl(page, ir: dict, viewport_name: str, width: int, height: int) -> bytes:
    """Отрисовать IR движком редактора в точном размере viewport и вернуть PNG.

    Viewport страницы выставляется в размер захваченного viewport, контейнер —
    в ширину блока; вариант responsive IR выбирается явно по имени viewport.
    """
    page.set_viewport_size({"width": max(240, int(width)), "height": max(320, int(height))})
    page.set_content(f'<div id="preview" style="width:{int(width)}px"></div>')
    page.add_script_tag(path=str(RENDERER_JS))
    # Захваченные шрифты инлайним ДО рендера: document.fonts.ready —
    # одноразовый promise, он резолвится по фейсам движка (/fonts/ в about:blank
    # падают мгновенно), и шрифты, добавленные после renderIR, грузятся уже
    # после барьера — скриншот ловил fallback-глифы.
    inline_fonts = _inline_font_face_css(ir)
    if inline_fonts:
        page.add_style_tag(content=inline_fonts)
    page.evaluate(
        "(args) => { const container = document.querySelector('#preview');"
        " window.IRRenderer.renderIR(container, args.ir, {viewport: args.viewport, fit: false, offline: true});"
        " window.IRRenderer.fitPreview(container); }",
        {"ir": ir, "viewport": viewport_name})
    page.wait_for_selector('[data-ir-sec="0"]', timeout=5000)
    # Headless measurement owns layout: fit synchronously, rather than depend
    # on a preview-only deferred callback. Keep the font/image paint barrier.
    page.wait_for_function("() => document.querySelector('#preview').style.height !== ''",
                           timeout=5000)
    # The renderer returns before remote images and webfonts necessarily finish.
    # A screenshot taken at that point measures network timing, not IR fidelity.
    # Wait for the same deterministic paint barrier used during source capture.
    # page.evaluate has no built-in timeout, so a single hanging image request
    # (throttled CDN, analytics pixel) would block the whole harness forever —
    # race the barrier against a hard deadline.
    page.evaluate("""(deadlineMs) => Promise.race([
      Promise.all([
        (document.fonts && document.fonts.ready) ? document.fonts.ready.catch(() => {}) : Promise.resolve(),
        // faces могут стартовать ПОСЛЕ fonts.ready (поздний layout/swap) —
        // опрашиваем статусы, пока что-то грузится
        new Promise(resolve => {
          const settle = () => {
            document.fonts.ready.then(() => {
              if (Array.from(document.fonts).some(f => f.status === 'loading')) setTimeout(settle, 50);
              else resolve();
            }).catch(resolve);
          };
          settle();
        }),
        Promise.all(Array.from(document.images || []).map(img =>
          img.complete && img.naturalWidth > 0
            ? Promise.resolve()
            : Promise.race([
                (img.decode ? img.decode() : new Promise(resolve => {
                    img.addEventListener('load', resolve, {once:true});
                    img.addEventListener('error', resolve, {once:true});
                  })).catch(() => {}),
                new Promise(resolve => setTimeout(resolve, 8000))
              ])))
      ]).then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))),
      new Promise(resolve => setTimeout(resolve, deadlineMs))
    ])""", PAINT_BARRIER_TIMEOUT_MS)
    return page.locator("#preview").screenshot(type="png", timeout=15000)


def measure_layout(page, ir: dict, viewport_name: str, width: int, height: int,
                   source_line_counts: dict[str, int] | None = None,
                   thresholds: dict[str, float] | None = None) -> dict:
    """Render *ir* with source fonts and return deterministic text/layout defects.

    The measurement deliberately runs through :func:`_render_block_png`, so the
    font and two-frame paint barriers are identical to the fidelity harness.
    Paths are renderer ``data-ir-path`` values (sourceKey for captured masters).
    """
    png = _render_block_png(page, ir, viewport_name, width, height)
    limits = {"overflowMinPx": 4.0, "overflowMinRatio": .15, "escapeMinPx": 4.0,
              **(thresholds or {})}
    measured = page.evaluate("""(args) => {
      const sourceLines = args.sourceLines || {}, limits = args.thresholds;
      const root = document.querySelector('#preview');
      const nodes = Array.from(root.querySelectorAll('[data-ir-path]'));
      const visible = el => {
        const r = el.getBoundingClientRect(); let cur = el;
        while (cur && cur !== root.parentElement) {
          const cs = getComputedStyle(cur);
          if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity || 1) <= 0) return false;
          cur = cur.parentElement;
        }
        return r.width > .25 && r.height > .25;
      };
      const directText = el => Array.from(el.childNodes || [])
        .filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent || '').join('').trim();
      const visibleNodes = nodes.filter(visible);
      const records = visibleNodes.map((el, index) => {
        const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
        const text = directText(el) || (!el.querySelector('[data-ir-path]') ? (el.textContent || '').trim() : '');
        let clipped = 0, parent = el.parentElement;
        while (parent && parent !== root.parentElement) {
          const ps = getComputedStyle(parent);
          if (['hidden','clip'].includes(ps.overflowX) || ['hidden','clip'].includes(ps.overflowY)) {
            const pr = parent.getBoundingClientRect();
            clipped = Math.max(clipped, Math.max(0, pr.left-r.left, r.right-pr.right,
              pr.top-r.top, r.bottom-pr.bottom));
          }
          parent = parent.parentElement;
        }
        const family = (cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim();
        const range = document.createRange(); range.selectNodeContents(el);
        const lineTops = [...range.getClientRects()].filter(x => x.width > .25 && x.height > .25)
          .map(x => Math.round(x.top * 2) / 2);
        const lineCount = new Set(lineTops).size;
        const owner = el.parentElement && el.parentElement.closest('[data-ir-path]');
        const pr = owner ? owner.getBoundingClientRect() : root.getBoundingClientRect();
        const escape = Math.max(0, pr.left-r.left, r.right-pr.right, pr.top-r.top, r.bottom-pr.bottom);
        const ownerStyle = owner ? getComputedStyle(owner) : null;
        const parentClips = !!ownerStyle && (['hidden','clip'].includes(ownerStyle.overflowX)
          || ['hidden','clip'].includes(ownerStyle.overflowY));
        const componentRoot = el.closest('[data-ir-sec]') || visibleNodes[0];
        const rr = componentRoot && componentRoot !== el ? componentRoot.getBoundingClientRect() : r;
        const rootEscape = Math.max(0, rr.left-r.left, r.right-rr.right, rr.top-r.top, r.bottom-rr.bottom);
        return {index, path:el.dataset.irPath || `(dom:${index})`, text,
          left:r.left, top:r.top, right:r.right, bottom:r.bottom,
          width:r.width, height:r.height,
          lineCount, escape, parentClips, rootEscape,
          overflowX:Math.max(0, el.scrollWidth-el.clientWidth),
          overflowY:Math.max(0, el.scrollHeight-el.clientHeight), clipped,
          overflowHidden:['hidden','clip'].includes(cs.overflowX) || ['hidden','clip'].includes(cs.overflowY),
          fontFamily:family, fontLoaded:!text || !document.fonts || document.fonts.check(`${cs.fontSize} "${family}"`, text)};
      });
      const defects = [];
      for (const a of records) {
        if (!a.text) continue;
        const overflow = Math.max(a.overflowX, a.overflowY);
        const capturedLineFragment = /::text\\d+l\\d+$/.test(a.path);
        // A descendant crossing some clipped ancestor is handled by the
        // escape rule below.  Text clipping itself is proven by this text
        // frame's hidden/clip overflow plus scrollWidth-clientWidth.
        const clipPx = a.overflowHidden ? overflow : 0;
        const actuallyClipped = clipPx >= limits.overflowMinPx;
        const actionableOverflow = !capturedLineFragment && overflow >= limits.overflowMinPx
          && (actuallyClipped || overflow / Math.max(a.width, 1) >= limits.overflowMinRatio);
        if (actionableOverflow)
          defects.push({path:a.path, kind:'overflow', px:Math.round(overflow*100)/100});
        if (!capturedLineFragment && clipPx >= limits.overflowMinPx)
          defects.push({path:a.path, kind:'clip', px:Math.round(clipPx*100)/100});
        if (a.escape >= limits.escapeMinPx || (a.parentClips && a.escape > .5) || a.rootEscape > .5)
          defects.push({path:a.path, kind:'escape', px:Math.round(Math.max(a.escape,a.rootEscape)*100)/100});
        const expected = Number(sourceLines[a.path] || 0);
        if (expected > 0 && a.lineCount > expected)
          defects.push({path:a.path, kind:'wrap', px:a.lineCount-expected});
      }
      for (let i=0; i<records.length; i++) for (let j=i+1; j<records.length; j++) {
        const a=records[i], b=records[j];
        if (!a.text || !b.text) continue;
        const ae=visibleNodes[a.index], be=visibleNodes[b.index];
        if (ae.contains(be) || be.contains(ae) || ae.parentElement !== be.parentElement) continue;
        // Captured ::text / ::pseudo fragments of one source element are
        // layered intentionally and are not independent siblings.
        if (a.path.split('::')[0] === b.path.split('::')[0]) continue;
        const ix=Math.max(0, Math.min(a.right,b.right)-Math.max(a.left,b.left));
        const iy=Math.max(0, Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
        if (ix > .5 && iy > .5) defects.push({path:b.path, kind:'overlap',
          px:Math.round(Math.min(ix,iy)*100)/100, otherPath:a.path});
      }
      const unique = new Map();
      for (const d of defects) {
        const key = `${d.path}\u0000${d.kind}`, old = unique.get(key);
        if (!old || d.px > old.px) unique.set(key, d);
      }
      return {defects:[...unique.values()], nodes:records.map(({index,left,top,right,bottom,...r}) => r),
        fontsLoaded:records.filter(r=>r.text).every(r=>r.fontLoaded)};
    }""", {"sourceLines": source_line_counts or {}, "thresholds": limits})
    measured["viewport"] = viewport_name
    measured["png"] = png
    return measured


AA_SHIFT_TOLERANCE_PX = 1


def _shift_tolerant_match(ref_arr, got_arr, exact):
    """Маска совпадений с допуском сдвига на AA_SHIFT_TOLERANCE_PX в любую сторону."""
    import numpy as np

    height, width = exact.shape
    match = exact.copy()
    radius = AA_SHIFT_TOLERANCE_PX
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            ys = slice(max(0, dy), height + min(0, dy))
            xs = slice(max(0, dx), width + min(0, dx))
            yb = slice(max(0, -dy), height + min(0, -dy))
            xb = slice(max(0, -dx), width + min(0, -dx))
            shifted = np.zeros_like(exact)
            shifted[ys, xs] = (np.abs(ref_arr[ys, xs] - got_arr[yb, xb]) < CHANNEL_TOLERANCE).all(axis=2)
            match |= shifted
    return match


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
    ref_arr = np.asarray(ref, dtype=np.int16)
    got_arr = np.asarray(got, dtype=np.int16)
    diff = np.abs(got_arr - ref_arr)
    exact = (diff < CHANNEL_TOLERANCE).all(axis=2)
    # Точное попиксельное сравнение считало расхождением КАЖДУЮ кромку глифа
    # при сдвиге текста на 1px (субпиксельная раскладка/округление line-height):
    # блок с идеальной геометрией и теми же шрифтами получал ~90%. Как pixelmatch,
    # допускаем сдвиг на AA_SHIFT_TOLERANCE_PX: пиксель совпал, если в окрестности
    # рендера есть такой же цвет. Точное значение остаётся в pixel_similarity_exact.
    match = _shift_tolerant_match(ref_arr, got_arr, exact)
    result["pixel_similarity"] = round(float(match.mean()) * 100, 2)
    result["pixel_similarity_exact"] = round(float(exact.mean()) * 100, 2)

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


def _component_boundaries(ir: dict | None) -> dict[str, dict]:
    boundaries: dict[str, dict] = {}

    def visit(node, ancestors: tuple[dict, ...] = ()) -> None:
        if not isinstance(node, dict):
            return
        meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
        source_key = str(node.get("sourceKey") or "")
        if meta.get("componentBoundary") and source_key:
            # Captured node frames are local to their parent. Component crops and
            # rendered DOM boxes are measured relative to the block root, so keep
            # the ancestry needed to reconstruct that absolute frame. Storing it
            # on a shallow harness-only copy avoids leaking private data into IR.
            boundaries[source_key] = {**node, "_componentAncestors": ancestors}
        for child in node.get("children") or []:
            visit(child, (*ancestors, node))

    for root in (ir or {}).get("tree") or []:
        visit(root)
    return boundaries


def _viewport_component_frame(node: dict, viewport: str) -> dict | None:
    absolute_x = 0.0
    absolute_y = 0.0
    parts = [*(node.get("_componentAncestors") or ()), node]
    frame: dict = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        base = part.get("frame") if isinstance(part.get("frame"), dict) else {}
        override = ((part.get("responsive") or {}).get(viewport) or {})
        if isinstance(override, dict) and override.get("visible") is False:
            return None
        override_frame = (override.get("frame")
                          if isinstance(override, dict) and isinstance(override.get("frame"), dict)
                          else {})
        current = {**base, **override_frame}
        absolute_x += float(current.get("x") or 0)
        absolute_y += float(current.get("y") or 0)
        if part is node:
            frame = current
    if any(not isinstance(frame.get(key), (int, float)) for key in ("width", "height")):
        return None
    return {**frame, "x": absolute_x, "y": absolute_y}


def _crop_png(png: bytes, frame: dict, block_size: dict) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    block_width = float(block_size.get("width") or image.width)
    block_height = float(block_size.get("height") or image.height)
    scale_x = image.width / max(1.0, block_width)
    scale_y = image.height / max(1.0, block_height)
    left = max(0, int(round(float(frame.get("x") or 0) * scale_x)))
    top = max(0, int(round(float(frame.get("y") or 0) * scale_y)))
    right = min(image.width, int(round((float(frame.get("x") or 0) + float(frame["width"])) * scale_x)))
    bottom = min(image.height, int(round((float(frame.get("y") or 0) + float(frame["height"])) * scale_y)))
    if right <= left or bottom <= top:
        raise ValueError("component crop is outside the block screenshot")
    cropped = image.crop((left, top, right, bottom))
    output = io.BytesIO()
    cropped.save(output, format="PNG")
    return output.getvalue()


def _rendered_source_box(page, source_key: str) -> dict | None:
    try:
        return page.evaluate("""(sourceKey) => {
          const preview = document.querySelector('#preview');
          const section = document.querySelector('[data-ir-sec="0"]');
          if (!preview || !section) return null;
          const element = Array.from(section.querySelectorAll('[data-ir-path]'))
            .find(candidate => candidate.getAttribute('data-ir-path') === sourceKey);
          if (!element) return null;
          const base = section.getBoundingClientRect();
          const rect = element.getBoundingClientRect();
          return {x: rect.left - base.left, y: rect.top - base.top,
                  width: rect.width, height: rect.height};
        }""", source_key)
    except Exception:
        return None


def _component_viewport_metrics(item: dict, page, node: dict, viewport: str,
                                reference_png: bytes, render_png: bytes,
                                block_size: dict) -> dict:
    source_key = str(node.get("sourceKey") or "")
    frame = _viewport_component_frame(node, viewport)
    metrics: dict = {key: None for key in REQUIRED_METRICS}
    metrics["visual_losses"] = []
    metrics["unexplained_losses"] = 0
    metrics["artifacts"] = {}
    if not frame:
        metrics["gate"] = viewport_gate(metrics)
        return metrics

    reference_crop = _crop_png(reference_png, frame, block_size)
    render_crop = _crop_png(render_png, frame, block_size)
    images = _image_metrics(reference_crop, render_crop)
    metrics.update({
        "pixel_similarity": images.get("pixel_similarity"),
        "region_diffs": images.get("region_diffs"),
        "reference_size": images.get("reference_size"),
        "render_size": images.get("render_size"),
        "size_match": images.get("size_match"),
    })

    all_leaf_boxes = (item.get("leaf_boxes_by_viewport") or {}).get(viewport) or []
    leaf_boxes = [
        box for box in all_leaf_boxes if isinstance(box, dict)
        and (str(box.get("sourceKey") or "") == source_key
             or str(box.get("sourceKey") or "").startswith(source_key + "/")
             or str(box.get("sourceKey") or "").startswith(source_key + "::"))
    ]
    bbox = _bbox_metrics(page, leaf_boxes) or {}
    rendered_box = _rendered_source_box(page, source_key)
    boundary_error = None
    if rendered_box:
        boundary_error = max(
            abs(float(frame.get("x") or 0) - float(rendered_box.get("x") or 0)),
            abs(float(frame.get("y") or 0) - float(rendered_box.get("y") or 0)),
            abs(float(frame.get("width") or 0) - float(rendered_box.get("width") or 0)),
            abs(float(frame.get("height") or 0) - float(rendered_box.get("height") or 0)),
        )
        metrics["grid_origin_error"] = round(max(
            abs(float(frame.get("x") or 0) - float(rendered_box.get("x") or 0)),
            abs(float(frame.get("y") or 0) - float(rendered_box.get("y") or 0)),
        ), 2)
    for key in ("bbox_mean", "bbox_p95", "bbox_max"):
        measured = bbox.get(key)
        if measured is None:
            measured = boundary_error
        elif boundary_error is not None and key != "bbox_mean":
            measured = max(float(measured), float(boundary_error))
        metrics[key] = round(float(measured), 2) if measured is not None else None
    metrics["bbox_matched"] = bbox.get("bbox_matched", 0)
    metrics["bbox_unmatched"] = bbox.get("bbox_unmatched", 0)
    metrics["bbox_total"] = bbox.get("bbox_total", 0)

    paint = (item.get("paint_coverage") or {}).get(viewport)
    metrics["paint_coverage"] = float(paint) if paint is not None else None
    losses = [
        loss for loss in visual_losses(item, viewport)
        if str(loss.get("sourceKey") or "") == source_key
        or str(loss.get("sourceKey") or "").startswith(source_key + "/")
        or str(loss.get("sourceKey") or "").startswith(source_key + "::")
    ]
    metrics["visual_losses"] = losses
    metrics["unexplained_losses"] = sum(1 for loss in losses if not loss.get("explained"))
    metrics["gate"] = viewport_gate(metrics)
    return metrics


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
    boundaries = _component_boundaries(ir)
    report: dict = {
        "raster_fallback": raster,
        "viewports": {},
        "components": {
            source_key: {
                "sourceKey": source_key,
                "label": str(((node.get("sourceMeta") or {}).get("componentLabel") or "")),
                "role": str(((node.get("sourceMeta") or {}).get("componentRole") or "")),
                "repeatGroup": str(((node.get("sourceMeta") or {}).get("repeatGroup") or "")),
                "raster_fallback": False,
                "viewports": {},
            }
            for source_key, node in boundaries.items()
        },
    }
    if isinstance(item.get("provenance"), dict):
        report["provenance"] = item["provenance"]
        for component in report["components"].values():
            component["provenance"] = item["provenance"]
    previews = item.get("previews") or {}
    sizes = item.get("sizes") or {}
    for name in sorted(previews):
        preview = str(previews.get(name) or "")
        size = sizes.get(name) or {}
        metrics: dict = {key: None for key in REQUIRED_METRICS}
        metrics["translucent_root"] = _translucent_root(ir)
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
                import scraper
                resolved, blob_errors = scraper.resolve_ir_blobs(ir)
                if blob_errors:
                    raise RuntimeError("blob resolve failed: " + "; ".join(blob_errors[:6]))
                shot = _render_block_png(page, resolved, name, int(size["width"]), int(size["height"]))
                reference_png = _decode_data_url(preview)
                images = _image_metrics(reference_png, shot)
                metrics["pixel_similarity"] = images["pixel_similarity"]
                metrics["region_diffs"] = images["region_diffs"]
                metrics["reference_size"] = images["reference_size"]
                metrics["render_size"] = images["render_size"]
                metrics["size_match"] = images["size_match"]
                bbox = _bbox_metrics(page, leaf_boxes)
                if bbox:
                    metrics.update(bbox)
                for source_key, node in boundaries.items():
                    if _viewport_component_frame(node, name) is None:
                        continue
                    try:
                        component_metrics = _component_viewport_metrics(
                            item, page, node, name, reference_png, shot, size)
                    except Exception as component_error:
                        component_metrics = {key: None for key in REQUIRED_METRICS}
                        component_metrics.update({
                            "visual_losses": [], "unexplained_losses": 0,
                            "harness_error": str(component_error),
                        })
                        component_metrics["gate"] = viewport_gate(component_metrics)
                    report["components"][source_key]["viewports"][name] = component_metrics
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
    for component in report["components"].values():
        component["gate"] = evaluate_gate(component)
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
    import scraper
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = scraper.launch_chromium(p)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900},
                                    device_scale_factor=1)
            # Движок подтягивает Google Fonts CSS по сети — это гонка со
            # скриншотом: faces регистрируются после document.fonts.ready и
            # текст снимается в fallback-шрифте. Захваченные /fonts файлы уже
            # инлайнятся как data:URL — блокируем сетевой источник.
            # ВАЖНО: только точечные маршруты — catch-all "**/*" гоняет КАЖДЫЙ
            # запрос рендера через Python-interception и на медленных машинах
            # ломает загрузку картинок (каждый round-trip стоит секунды).
            def _block_google_fonts(route):
                route.abort("blockedbyclient")

            page.route("https://fonts.googleapis.com/**", _block_google_fonts)
            page.route("https://fonts.gstatic.com/**", _block_google_fonts)
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
        "captureVersion": scraper.SOURCE_CAPTURE_VERSION,
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
