"""BlockParse: детекция блоков страницы и параллельный clone каждого в Design IR.

Внутренний движок Source Import (см. docs/ARCHITECTURE.md и docs/NODES.md):
fetch — scraper.fetch_html, детекция границ — scraper.detect_blocks,
клонирование — промпт-механика /api/clone (LLM в режиме edit, точное
воспроизведение), кэш — cache_store (повторный разбор сайта бесплатен),
параллельность — ThreadPool (паттерн /api/generate).
Ошибки отдельного блока не роняют остальные.
"""
from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

import llm_client as llm
import cache_store
import fidelity_harness
import ir
from ir import ensure_current as ensure_current_ir
from scraper import (blob_ref, capture_block_irs, detect_blocks, fetch_html,
                     put_png_blob, rendered_html)
from ir.style_dna import enrich_ir, extract_from_signals
from ir.parser_contract import build_parser_envelope

MAX_WORKERS = 4            # как EXECUTOR в server.py
FRAGMENT_LIMIT = 12000     # HTML блока в промпте, символов
STYLES_LIMIT = 6000        # CSS страницы в промпте, символов
DEFAULT_PROVIDER = "auto"  # роль clone/repair выбирает модель из ROUTING

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)

_SEMANTIC_ROLES = {
    "header", "footer", "carousel", "categories", "product-grid", "services-grid",
    "journal", "how-it-works", "faq", "cta", "trust", "pricing", "testimonials",
    "gallery", "navigation", "status", "toolbar", "profile", "panel", "section",
}

SOURCE_COMPILER_VERSION = "dom-v34"

# Hidden blocks (display:none / zero box / no visual content) are not import
# errors; they are omitted from Source Import outputs. Both English compiler
# diagnostics and the legacy Russian guard are recognized.
_HIDDEN_BLOCK_ERRORS = ("not visible", "не виден", "no editable visible layers")


def _is_hidden_block_error(error: Any) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in _HIDDEN_BLOCK_ERRORS)


def _validate(doc: dict) -> list[str]:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return ir.format_errors(ir.validate_ir(doc))


def _normalize_captured_page_tokens(value: dict | None, source: str) -> dict | None:
    """Accept the current scraper token contract without re-parsing it.

    `capture_block_irs` already converts DOM signals into schema-compatible
    tokens. Passing that result through `extract_from_signals` again looked for
    obsolete bodyBg/buttonBg keys and replaced the real brand palette with the
    black/white defaults.
    """
    if not isinstance(value, dict):
        return None
    public_keys = {"mode", "color", "font", "radius", "spacing", "shadow"}
    if public_keys.issubset(value):
        return copy.deepcopy(value)
    return extract_from_signals(value, source=source)


def _clean_text_nodes(node: dict) -> None:
    """Text and heading nodes must never carry visual box styles.

    Those properties belong to the parent card/button/input. This keeps the
    imported DOM pixel-accurate while preventing text blocks from looking like
    coloured rectangles in the editor.
    """
    if not isinstance(node, dict):
        return
    if node.get("type") in ("text", "heading"):
        style = node.get("style")
        if isinstance(style, dict):
            for k in ("background", "borderColor", "borderWidth", "borderRadius", "boxShadow"):
                style.pop(k, None)
            node["style"] = style
    for child in node.get("children") or []:
        _clean_text_nodes(child)


def _block_cache_key(url: str, name: str, selector: str) -> str:
    # Bump when the deterministic DOM compiler or responsive merge contract changes.
    raw = f"{SOURCE_COMPILER_VERSION}|{url.strip().lower().rstrip('/')}|{name}|{selector}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _refine_ambiguous_blocks(html: str, blocks: list[dict], provider: str) -> list[dict]:
    """Use a small semantic LLM pass only when DOM/tag/class heuristics are unsure.

    Selectors and geometry remain deterministic. The model can label a candidate,
    but cannot invent, resize, merge or reorder source blocks. The call wears a
    hard 20s budget: semantic labels are optional sugar over deterministic DOM
    detection, and a stalling provider must not stretch an import into minutes
    (the desktop queues every API call behind this single worker).
    """
    ambiguous = [(i, b) for i, b in enumerate(blocks) if b.get("kind") == "section"]
    if not ambiguous:
        return blocks
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for index, block in ambiguous:
        try:
            el = soup.select_one(block["selector"])
        except Exception:
            el = None
        candidates.append({
            "index": index,
            "tag": block.get("tag"),
            "heading": block.get("heading", ""),
            "text": (el.get_text(" ", strip=True)[:500] if el else ""),
        })
    prompt = (
        "Classify ambiguous web page sections. Return JSON only: "
        '{"blocks":[{"index":0,"role":"section","label":"Human label"}]}. '
        "Allowed roles: " + ", ".join(sorted(_SEMANTIC_ROLES)) + ". "
        "Do not add/remove/reorder candidates. A repeated group of products/listings is product-grid; "
        "services is services-grid; editorial posts are journal.\n\n" +
        json.dumps(candidates, ensure_ascii=False)
    )
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": "You label existing DOM sections. You never design or alter layout."},
            {"role": "user", "content": prompt},
        ], 0.1, timeout=20, role="source_semantics")
        answer = json.loads(llm.extract_json(raw))
    except Exception:
        return blocks
    refined = [dict(b) for b in blocks]
    for item in answer.get("blocks", []) if isinstance(answer, dict) else []:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        role = str(item.get("role", ""))
        if index < 0 or index >= len(refined) or role not in _SEMANTIC_ROLES:
            continue
        if refined[index].get("kind") != "section":
            continue
        refined[index]["kind"] = role
        label = str(item.get("label") or "").strip()
        if label:
            refined[index]["label"] = label[:100]
    return refined


def _compact_preview(uri: str | None, max_width: int = 720, quality: int = 82) -> str | None:
    """Reference-превью для клиента: PNG-скриншот → JPEG ≤720px.

    Полное разрешение остаётся у fidelity-harness (свои копии); клиенту превью
    нужны только как <img> в списке блоков. 14 блоков × 3 viewport'а PNG
    весили ~5 МБ на импорт и раздували node data и автосейвы проекта.
    """
    if not isinstance(uri, str) or not uri.startswith("data:image"):
        return uri or None
    try:
        import base64
        import io

        from PIL import Image

        header, _, b64 = uri.partition(",")
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode != "P":
                background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            else:
                background.paste(img.convert("RGB"))
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if img.width > max_width:
            img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        compact = "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
        return compact if len(compact) < len(uri) else uri
    except Exception:
        return uri


def _full_resolution_preview(uri: str | None) -> str | None:
    """Persist a lossless Source screenshot as a content-addressed PNG ref."""
    if not isinstance(uri, str) or not uri.startswith("data:image"):
        return uri or None
    try:
        import base64
        import io

        from PIL import Image

        _header, _, encoded = uri.partition(",")
        raw = base64.b64decode(encoded)
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            with Image.open(io.BytesIO(raw)) as image:
                converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                converted.save(output, format="PNG")
                raw = output.getvalue()
        return blob_ref(put_png_blob(raw))
    except Exception:
        return _compact_preview(uri)


def _public_fidelity_report(report: dict | None) -> dict:
    """Return serialisable fidelity evidence without local artifact paths."""
    if not isinstance(report, dict):
        return {}
    # The harness report also contains diagnostic heatmaps and repeats the full
    # capture provenance on every component. Those fields are useful in a local
    # artifact bundle, but they made a real 14-block project exceed the 8 MiB
    # live-session limit. The UI Kit builder consumes only scalar metrics, gate
    # results and semantic identity, so publish exactly that durable contract.
    metric_keys = {
        "pixel_similarity", "bbox_mean", "bbox_p95", "bbox_max",
        "grid_origin_error", "paint_coverage", "visual_losses",
        "unexplained_losses", "reference_size", "render_size", "size_match",
        "gate", "harness_error",
    }

    def public_metrics(value) -> dict:
        return {key: copy.deepcopy(item) for key, item in (value or {}).items()
                if key in metric_keys}

    public = {
        key: copy.deepcopy(value)
        for key, value in report.items()
        if key not in {"viewports", "components"}
    }
    public["viewports"] = {
        str(name): public_metrics(metrics)
        for name, metrics in (report.get("viewports") or {}).items()
        if isinstance(metrics, dict)
    }
    public["components"] = {}
    for source_key, component in (report.get("components") or {}).items():
        if not isinstance(component, dict):
            continue
        compact_component = {
            key: copy.deepcopy(component.get(key))
            for key in ("sourceKey", "label", "role", "repeatGroup", "raster_fallback", "gate")
            if key in component
        }
        compact_component["viewports"] = {
            str(name): public_metrics(metrics)
            for name, metrics in (component.get("viewports") or {}).items()
            if isinstance(metrics, dict)
        }
        public["components"][str(source_key)] = compact_component
    return public


def parse_blocks(url: str, blocks: list | None = None,
                 provider: str = DEFAULT_PROVIDER,
                 viewports: list[dict] | None = None,
                 auth_cookies: list[dict] | None = None,
                 full_resolution_evidence: bool = False) -> dict:
    """BlockParse: список блоков-IR + design-токены по URL.

    blocks — опциональный список {name, selector}: клонировать только их
    (экономия LLM-вызовов, §7.4); по умолчанию — все найденные detect_blocks.
    Ошибка отдельного блока возвращается в его записи, остальные продолжаются.
    """
    url = url.strip()
    authenticated = auth_cookies is not None
    cache_enabled = not authenticated

    wanted = None
    if blocks is not None:
        wanted = []
        for b in blocks:
            if not isinstance(b, dict) or not str(b.get("selector", "")).strip():
                raise ValueError("Каждый блок должен быть объектом с полем selector.")
            wanted.append({"name": str(b.get("name") or f"block-{len(wanted) + 1}"),
                           "selector": str(b["selector"]).strip()})
        if not wanted:
            raise ValueError("Пустой список блоков.")

    # кэш полного разбора — только когда берём все блоки (выборочный список не кэшируем)
    # Не читаем результаты v1: там лежат LLM-аппроксимации, а не DOM-слои.
    viewport_key = json.dumps({
        "viewports": viewports or "default",
        "fullResolutionEvidence": bool(full_resolution_evidence),
    }, sort_keys=True, separators=(",", ":"))
    full_key = cache_store.key_url(SOURCE_COMPILER_VERSION + "|" + viewport_key + "|" + url)
    if wanted is None and cache_enabled:
        hit = cache_store.get("blockparse_url", full_key)
        # Ошибочный частичный ответ никогда не должен выглядеть как успешный
        # «кэш»: иначе временный 429/timeout навсегда блокирует повторный запуск.
        if hit and not any(isinstance(block, dict) and block.get("error")
                           for block in hit.get("blocks", [])):
            return {**hit, "cached": True}

    if wanted is None:
        # Детекция и refine — по живому DOM после JS (Chromium), чтобы селекторы
        # гарантированно resolve'ились в capture; SSR/hydration-расхождение с raw
        # HTML делало их хрупкими. При сбое рендера — тихий fallback на httpx
        # (у payload нет warnings-канала).
        try:
            html = rendered_html(url, cookies=auth_cookies)  # внутри SSRF-гард
        except ValueError:
            raise
        except Exception:
            if authenticated:
                raise
            try:
                html = fetch_html(url)  # внутри SSRF-гард
            except ValueError:
                raise
            except Exception as e:
                raise RuntimeError(f"не удалось загрузить {url}: {e}")
        wanted = detect_blocks(html)
        wanted = _refine_ambiguous_blocks(html, wanted, provider)
        if not wanted:
            raise RuntimeError("на странице не найдено ни одного блока "
                               "(нет семантических тегов и заголовков)")

    # Токены страницы приезжают из capture (замер живого DOM); CSS-фолбэк по
    # inline <style> больше не нужен — без capture осмысленных токенов нет.
    tokens = None

    # Один Chromium на всю страницу: снимаем реальный DOM после JS, computed
    # styles и bbox каждого блока. Это даёт редактируемый фрейм, а не догадку
    # LLM о том, к какому из 19 шаблонов отнести произвольный компонент.
    try:
        captured, rendered_tokens = capture_block_irs(
            url, wanted, return_tokens=True, viewports=viewports, cookies=auth_cookies)
        tokens = _normalize_captured_page_tokens(rendered_tokens, source=url)
    except Exception as e:
        traceback.print_exc()
        captured = {b["selector"]: {"error": f"не удалось снять DOM-слепок: {e}"}
                    for b in wanted}
        tokens = None

    results = []
    pending_block_writes = []  # (key, payload, selector) — запись после fidelity-гейта
    final_items: dict = {}     # selector → capture item с финальным (enriched) IR
    for b in wanted:  # порядок детекции остаётся порядком выходных портов
        head = {"name": b["name"], "selector": b["selector"],
                "label": b.get("label") or b["name"], "kind": b.get("kind", "section")}
        item = captured.get(b["selector"], {"error": "DOM-слепок не получен"})
        if item.get("error"):
            # Responsive duplicates that are hidden at the canonical desktop viewport
            # are not meaningful Source Import outputs. The compiler emits English
            # diagnostics; the legacy Russian guard is kept for backward compatibility.
            if _is_hidden_block_error(item["error"]):
                continue
            results.append({**head, "error": item["error"]})
            continue
        ir = item.get("ir")
        errors = _validate(ir) if isinstance(ir, dict) else ["DOM-слепок не является IR"]
        if errors:
            results.append({**head, "error": "внутренняя ошибка DOM-импорта: " + "; ".join(errors[:3])})
            continue
        _clean_text_nodes(ir)
        ir = enrich_ir(ir, source=url)
        ir = ensure_current_ir(ir, source=f"source-import:{url}")
        parser_contract = build_parser_envelope(
            ir,
            url=url,
            selector=b["selector"],
            label=head["label"],
            parser_version=SOURCE_COMPILER_VERSION,
            capture={
                **item,
                "size": {"width": item.get("width"), "height": item.get("height")},
                "layers": item.get("layer_count", 0),
                "layersByViewport": item.get("layers_by_viewport", {}),
            },
        )
        if cache_enabled:
            pending_block_writes.append((
                _block_cache_key(url, b["name"], b["selector"]),
                {"ir": ir, "parserContract": parser_contract,
                 "rasterFallback": fidelity_harness.is_raster_fallback(ir)},
                b["selector"],
            ))
        final_items[b["selector"]] = {**item, "ir": ir}
        preview_mapper = _full_resolution_preview if full_resolution_evidence else _compact_preview
        results.append({**head, "ir": ir, "cached": False, "source": "dom",
                        "parserContract": parser_contract,
                        "layers": item.get("layer_count", 0), "size": {
                            "width": item.get("width"), "height": item.get("height")},
                        "preview": preview_mapper(item.get("preview")),
                        "previews": {name: preview_mapper(pv)
                                     for name, pv in (item.get("previews") or {}).items()},
                        "sizes": item.get("sizes", {}),
                        "layersByViewport": item.get("layers_by_viewport", {}),
                        "editableLayersByViewport": item.get("editable_layers_by_viewport", {}),
                        "componentBoundariesByViewport": item.get("component_boundaries_by_viewport", {}),
                        "coverage": item.get("coverage", {}),
                        "paintCoverage": item.get("paint_coverage", {}),
                        "fidelity": item.get("fidelity"),
                        "p95LayoutError": item.get("p95_layout_error"),
                        "droppedByViewport": item.get("dropped_by_viewport", {}),
                        "extrasByViewport": item.get("extras_by_viewport", {}),
                        "warnings": item.get("warnings", []), "repeat": item.get("repeat")})

    payload_tokens = tokens
    if payload_tokens is None:
        for block in results:
            if isinstance(block, dict) and block.get("ir"):
                payload_tokens = block["ir"].get("tokens")
                if payload_tokens:
                    break
    payload = {"url": url, "blocks": results, "tokens": payload_tokens,
               "authenticated": authenticated}
    # Fail-closed прогрев кэша: harness рендерит финальные IR в точном размере
    # каждого viewport и сравнивает со скриншотами источника. Нет обязательных
    # метрик или gate не пройден → записи нет, но IR всё равно возвращается.
    fidelity_reports: dict = {}
    if final_items:
        try:
            fidelity_reports = fidelity_harness.evaluate_captures(final_items)
        except Exception:
            traceback.print_exc()
            fidelity_reports = {}
    for block in results:
        if not isinstance(block, dict):
            continue
        report = fidelity_reports.get(block.get("selector"))
        if isinstance(report, dict):
            block["fidelityReport"] = _public_fidelity_report(report)
    for cache_key, cache_payload, selector in pending_block_writes:
        cache_store.put_gated("clone_block", cache_key, cache_payload,
                              fidelity_reports.get(selector))
    # Сохраняем только полностью успешный разбор. Отдельные удачные блоки уже
    # имеют свой clone_block-кэш; неудачные должны иметь шанс на повтор.
    if cache_enabled and blocks is None and not any(block.get("error") for block in results if isinstance(block, dict)):
        aggregate = {"blocks": [
            {"name": block.get("name"), "selector": block.get("selector"),
             **(fidelity_reports.get(block.get("selector")) or {})}
            for block in results
            if isinstance(block, dict) and block.get("ir")
        ]}
        cache_store.put_gated("blockparse_url", full_key, payload, aggregate)
    return {**payload, "cached": False}
