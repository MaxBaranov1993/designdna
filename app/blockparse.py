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
import time
import traceback
from pathlib import Path
from typing import Any, Callable

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

SOURCE_COMPILER_VERSION = "dom-v41"
SOURCE_ARTIFACT_VERSION = "source-artifact/1.0"

# Hidden blocks (display:none / zero box / no visual content) are not import
# errors; they are omitted from Source Import outputs. Both English compiler
# diagnostics and the legacy Russian guard are recognized.
_HIDDEN_BLOCK_ERRORS = ("not visible", "не виден", "no editable visible layers")


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _finish_source_import(payload: dict, *, timings_ms: dict[str, int],
                          started_at: float, cached: bool,
                          authenticated: bool) -> dict:
    """Attach measured pipeline diagnostics without polluting cache payloads."""
    timings_ms["total"] = _elapsed_ms(started_at)
    diagnostics = {
        "pipelineVersion": SOURCE_COMPILER_VERSION,
        "timingsMs": timings_ms,
    }
    blocks = payload.get("blocks") if isinstance(payload, dict) else []
    blocks = blocks if isinstance(blocks, list) else []
    print(json.dumps({
        "event": "source_import.completed",
        "pipelineVersion": SOURCE_COMPILER_VERSION,
        "cached": cached,
        "authenticated": authenticated,
        "blockCount": len(blocks),
        "errorCount": sum(1 for block in blocks if isinstance(block, dict) and block.get("error")),
        "timingsMs": timings_ms,
    }, ensure_ascii=False, separators=(",", ":")), flush=True)
    return {**payload, "cached": cached, "diagnostics": diagnostics}


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


def _token_leaf_count(value) -> int:
    if isinstance(value, dict):
        return sum(_token_leaf_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_token_leaf_count(item) for item in value)
    return 1 if value is not None else 0


def _foundation_groups(tokens: dict | None) -> list[dict]:
    if not isinstance(tokens, dict):
        return []
    return [
        {
            "key": str(key),
            "name": str(key).replace("_", " ").replace("-", " ").title(),
            "tokenCount": _token_leaf_count(value),
        }
        for key, value in sorted(tokens.items(), key=lambda item: str(item[0]))
    ]


def _assembled_screens(components: list[dict], tokens: dict | None) -> list[dict]:
    """Describe page compositions without copying component IR into the registry."""
    viewport_names = sorted({
        name
        for component in components
        for name in (component.get("responsive") or {})
    })
    token_mode = tokens.get("mode") if isinstance(tokens, dict) else None
    theme = token_mode if isinstance(token_mode, str) and token_mode.strip() else None
    screens = []
    for viewport in viewport_names:
        hierarchy = []
        widths = []
        heights = []
        layers = []
        editable_layers = []
        fidelities = []
        layout_errors = []
        component_keys = []
        for component in components:
            responsive = component.get("responsive") or {}
            metrics = responsive.get(viewport)
            if not isinstance(metrics, dict):
                continue
            component_keys.append(component["componentKey"])
            hierarchy.append({
                "componentKey": component["componentKey"],
                "name": component["name"],
                "role": component["role"],
                "blockIndex": component["master"]["blockIndex"],
                "selector": component["master"]["selector"],
            })
            size = metrics.get("size") if isinstance(metrics.get("size"), dict) else {}
            if isinstance(size.get("width"), (int, float)):
                widths.append(size["width"])
            if isinstance(size.get("height"), (int, float)):
                heights.append(size["height"])
            if isinstance(metrics.get("layers"), (int, float)):
                layers.append(metrics["layers"])
            if isinstance(metrics.get("editableLayers"), (int, float)):
                editable_layers.append(metrics["editableLayers"])
            if isinstance(metrics.get("fidelity"), (int, float)):
                fidelities.append(metrics["fidelity"])
            if isinstance(metrics.get("p95LayoutError"), (int, float)):
                layout_errors.append(metrics["p95LayoutError"])

        width = max(widths) if widths else None
        height = sum(heights) if heights else None
        size = {key: value for key, value in {"width": width, "height": height}.items()
                if value is not None}
        screen_name = f"{int(width) if width is not None else viewport}w"
        if theme:
            screen_name += f" {theme}"
        screen = {
            "screenKey": f"screen:{viewport}",
            "name": screen_name,
            "viewport": viewport,
            "basis": "assembled-from-source-blocks",
            "size": size,
            "componentKeys": component_keys,
            "hierarchy": hierarchy,
            "metrics": {
                "layers": sum(layers) if layers else None,
                "editableLayers": sum(editable_layers) if editable_layers else None,
                "fidelityMean": round(sum(fidelities) / len(fidelities), 6) if fidelities else None,
                "fidelityMin": min(fidelities) if fidelities else None,
                "p95LayoutErrorMax": max(layout_errors) if layout_errors else None,
            },
        }
        if theme:
            screen["theme"] = theme
        screen["metrics"] = {key: value for key, value in screen["metrics"].items()
                             if value is not None}
        screens.append(screen)
    return screens


def collect_ambiguities(blocks: list[dict]) -> list[dict]:
    """Места, где детерминированный разбор не уверен, — вход AI-уточнения.

    Эвристики честно перечисляют, чего не смогли решить, вместо того чтобы
    молча выдать спорный результат: блоки без внятной роли, компоненты без
    осмысленного имени и сообщённое усечение списка блоков.
    """
    items: list[dict] = []
    for index, block in enumerate(blocks or []):
        if not isinstance(block, dict) or not isinstance(block.get("ir"), dict):
            continue
        name = str(block.get("name") or f"block-{index + 1}")
        kind = str(block.get("kind") or "")
        if kind in ("", "section", "panel"):
            items.append({
                "type": "block-role",
                "block": name,
                "selector": block.get("selector"),
                "label": block.get("label"),
                "reason": "структура не определила роль блока однозначно",
            })
        if block.get("truncatedAfter"):
            items.append({
                "type": "truncated",
                "block": name,
                "dropped": int(block["truncatedAfter"]),
                "reason": "страница дала больше блоков, чем разрешает лимит",
            })
        unnamed: list[str] = []
        for node in _walk_ir_nodes(block["ir"].get("tree") or []):
            meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
            if not meta.get("componentBoundary"):
                continue
            label = str(meta.get("componentLabel") or "")
            # Имя вида "role: image + text" сгенерировано из формы содержимого:
            # человекочитаемого названия у компонента нет.
            if ":" in label or not label:
                key = str(node.get("sourceKey") or "")
                if key:
                    unnamed.append(key)
        if unnamed:
            items.append({
                "type": "unnamed-components",
                "block": name,
                "sourceKeys": unnamed[:40],
                "reason": "имя компонента выведено из формы содержимого, а не из разметки",
            })
    return items


def _walk_ir_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.get("children") or []:
            yield from _walk_ir_nodes(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_ir_nodes(item)


_REFINE_OPS = ("rename-block", "rename-component", "set-block-role")


def apply_refinements(blocks: list[dict], operations: list) -> tuple[list[dict], list[dict]]:
    """Применить AI-уточнения к разобранным блокам. Возвращает (blocks, applied).

    Строго по образцу design_system.organizer: модель может менять ТОЛЬКО
    подписи и роль блока. Геометрия, стили и IR неприкосновенны, поэтому
    fidelity-гейт не может быть обойдён через этот путь. Неизвестные операции
    и цели молча пропускаются, а не применяются частично.
    """
    by_name = {str(block.get("name")): block for block in blocks
               if isinstance(block, dict) and block.get("name")}
    applied: list[dict] = []
    for operation in operations or []:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "")
        if op not in _REFINE_OPS:
            continue
        block = by_name.get(str(operation.get("block") or ""))
        if block is None:
            continue
        if op == "rename-block":
            label = str(operation.get("label") or "").strip()[:80]
            if not label:
                continue
            block["label"] = label
            applied.append({"op": op, "block": block["name"], "label": label})
        elif op == "set-block-role":
            role = str(operation.get("role") or "").strip().lower()
            if role not in _SEMANTIC_ROLES:
                continue
            block["kind"] = role
            applied.append({"op": op, "block": block["name"], "role": role})
        elif op == "rename-component":
            source_key = str(operation.get("sourceKey") or "")
            label = str(operation.get("label") or "").strip()[:100]
            if not source_key or not label:
                continue
            ir = block.get("ir")
            if not isinstance(ir, dict):
                continue
            for node in _walk_ir_nodes(ir.get("tree") or []):
                meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else None
                if not meta or not meta.get("componentBoundary"):
                    continue
                if str(node.get("sourceKey") or "") != source_key:
                    continue
                meta["componentLabel"] = label
                applied.append({"op": op, "block": block["name"],
                                "sourceKey": source_key, "label": label})
                break
    return blocks, applied


def _build_source_artifact(url: str, blocks: list[dict], tokens: dict | None,
                           authenticated: bool) -> dict:
    """Build a compact, stable Source registry without duplicating master IR.

    Each component points back to its block index. The block remains the single
    render-time IR payload; the artifact adds the html.to.design-like library
    structure needed by Design UI: foundations, components, observed states,
    responsive measurements, quality and provenance.
    """
    components = []
    for block_index, block in enumerate(blocks):
        if not isinstance(block, dict) or not isinstance(block.get("ir"), dict):
            continue
        parser_contract = block.get("parserContract") if isinstance(block.get("parserContract"), dict) else {}
        source_record = parser_contract.get("sourceRecord") if isinstance(parser_contract.get("sourceRecord"), dict) else {}
        component_key = str(source_record.get("id") or f"source-component-{block_index + 1}")
        viewport_names = set()
        for field in ("sizes", "layersByViewport", "editableLayersByViewport", "coverage",
                      "paintCoverage", "fidelity", "p95LayoutError"):
            value = block.get(field)
            if isinstance(value, dict):
                viewport_names.update(str(name) for name in value)
        viewports = {}
        for name in sorted(viewport_names):
            size = (block.get("sizes") or {}).get(name) if isinstance(block.get("sizes"), dict) else None
            if not isinstance(size, dict) and name == "desktop" and isinstance(block.get("size"), dict):
                size = block["size"]
            viewports[name] = {
                "size": copy.deepcopy(size) if isinstance(size, dict) else None,
                "layers": (block.get("layersByViewport") or {}).get(name),
                "editableLayers": (block.get("editableLayersByViewport") or {}).get(name),
                "coverage": (block.get("coverage") or {}).get(name),
                "paintCoverage": (block.get("paintCoverage") or {}).get(name),
                "fidelity": (block.get("fidelity") or {}).get(name),
                "p95LayoutError": (block.get("p95LayoutError") or {}).get(name),
            }
            viewports[name] = {key: value for key, value in viewports[name].items() if value is not None}
        canonical_ir = json.dumps(block["ir"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        components.append({
            "componentKey": component_key,
            "name": str(block.get("label") or block.get("name") or component_key),
            "role": str(block.get("kind") or "section"),
            "master": {
                "blockIndex": block_index,
                "selector": str(block.get("selector") or ""),
                "irContentHash": "sha256:" + hashlib.sha256(canonical_ir.encode("utf-8")).hexdigest(),
            },
            "states": {
                "default": {
                    "observed": True,
                    "basis": "measured",
                    "viewports": sorted(viewports),
                },
            },
            "stateCoverage": {"observed": ["default"], "inferred": []},
            "responsive": viewports,
            "quality": {
                "gate": copy.deepcopy((block.get("fidelityReport") or {}).get("gate")),
                "warnings": copy.deepcopy(block.get("warnings") or []),
            },
            "provenance": {
                "sourceRecord": copy.deepcopy(source_record),
                "parserContractVersion": parser_contract.get("version"),
                "nodeStateCount": len(parser_contract.get("nodeStates") or {}),
            },
        })
    foundations = {
        "tokens": copy.deepcopy(tokens) if isinstance(tokens, dict) else None,
        "groups": _foundation_groups(tokens),
    }
    screens = _assembled_screens(components, tokens)
    variant_count = sum(len(component.get("states") or {}) for component in components)
    library = {
        "componentSetCount": len(components),
        "variantCount": variant_count,
        "observedStateCount": sum(
            len((component.get("stateCoverage") or {}).get("observed") or [])
            for component in components
        ),
    }
    return {
        "version": SOURCE_ARTIFACT_VERSION,
        "source": {
            "url": url,
            "authenticated": authenticated,
            "pipelineVersion": SOURCE_COMPILER_VERSION,
        },
        "foundations": foundations,
        "screens": screens,
        "library": library,
        "components": components,
        "summary": {
            "screenCount": len(screens),
            "componentCount": len(components),
            "componentSetCount": library["componentSetCount"],
            "variantCount": library["variantCount"],
            "observedStateCount": library["observedStateCount"],
            "viewportCount": len({name for component in components for name in component["responsive"]}),
            "tokenGroupCount": len(foundations["groups"]),
            "tokenCount": sum(group["tokenCount"] for group in foundations["groups"]),
        },
    }


def parse_blocks(url: str, blocks: list | None = None,
                 provider: str = DEFAULT_PROVIDER,
                 viewports: list[dict] | None = None,
                 auth_cookies: list[dict] | None = None,
                 full_resolution_evidence: bool = False,
                 on_stage: Callable[[str, int, dict[str, int]], None] | None = None) -> dict:
    """BlockParse: список блоков-IR + design-токены по URL.

    blocks — опциональный список {name, selector}: клонировать только их
    (экономия LLM-вызовов, §7.4); по умолчанию — все найденные detect_blocks.
    Ошибка отдельного блока возвращается в его записи, остальные продолжаются.
    """
    run_started = time.perf_counter()
    stage_started = run_started
    timings_ms: dict[str, int] = {}

    def stage_done(name: str) -> None:
        nonlocal stage_started
        duration = _elapsed_ms(stage_started)
        timings_ms[name] = duration
        if on_stage is not None:
            on_stage(name, duration, dict(timings_ms))

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
    stage_done("prepare")

    # кэш полного разбора — только когда берём все блоки (выборочный список не кэшируем)
    # Не читаем результаты v1: там лежат LLM-аппроксимации, а не DOM-слои.
    viewport_key = json.dumps({
        "viewports": viewports or "default",
        "fullResolutionEvidence": bool(full_resolution_evidence),
    }, sort_keys=True, separators=(",", ":"))
    full_key = cache_store.key_url(SOURCE_COMPILER_VERSION + "|" + viewport_key + "|" + url)
    stage_started = time.perf_counter()
    if wanted is None and cache_enabled:
        hit = cache_store.get("blockparse_url", full_key)
        # Ошибочный частичный ответ никогда не должен выглядеть как успешный
        # «кэш»: иначе временный 429/timeout навсегда блокирует повторный запуск.
        if hit and not any(isinstance(block, dict) and block.get("error")
                           for block in hit.get("blocks", [])):
            stage_done("cacheLookup")
            return _finish_source_import(
                hit,
                timings_ms=timings_ms,
                started_at=run_started,
                cached=True,
                authenticated=authenticated,
            )
    stage_done("cacheLookup")

    # Retained only as a compatibility fallback while the fast path is rolled
    # out. The production path detects blocks inside capture_block_irs from the
    # same hydrated page and never enters this two-navigation/LLM branch.
    if wanted is None and False:
        # Детекция и refine — по живому DOM после JS (Chromium), чтобы селекторы
        # гарантированно resolve'ились в capture; SSR/hydration-расхождение с raw
        # HTML делало их хрупкими. При сбое рендера — тихий fallback на httpx
        # (у payload нет warnings-канала).
        stage_started = time.perf_counter()
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
        stage_done("renderDom")
        stage_started = time.perf_counter()
        wanted = detect_blocks(html)
        stage_done("detectBlocks")
        stage_started = time.perf_counter()
        wanted = _refine_ambiguous_blocks(html, wanted, provider)
        stage_done("semanticRefine")
        if not wanted:
            raise RuntimeError("на странице не найдено ни одного блока "
                               "(нет семантических тегов и заголовков)")

    # Токены страницы приезжают из capture (замер живого DOM); CSS-фолбэк по
    # inline <style> больше не нужен — без capture осмысленных токенов нет.
    tokens = None

    # Один Chromium на всю страницу: снимаем реальный DOM после JS, computed
    # styles и bbox каждого блока. Это даёт редактируемый фрейм, а не догадку
    # LLM о том, к какому из 19 шаблонов отнести произвольный компонент.
    stage_started = time.perf_counter()

    def capture_progress(viewport_name: str, viewport_index: int,
                         viewport_count: int, elapsed_ms: int) -> None:
        if on_stage is None:
            return
        stage_name = "capture" + viewport_name[:1].upper() + viewport_name[1:]
        on_stage(stage_name, elapsed_ms, {
            **timings_ms,
            "captureCompileElapsed": elapsed_ms,
            "captureViewportIndex": viewport_index,
            "captureViewportCount": viewport_count,
        })

    try:
        if wanted is None:
            captured, rendered_tokens, wanted = capture_block_irs(
                url, None, return_tokens=True, return_blocks=True,
                viewports=viewports, cookies=auth_cookies,
                on_progress=capture_progress)
        else:
            captured, rendered_tokens = capture_block_irs(
                url, wanted, return_tokens=True, viewports=viewports, cookies=auth_cookies,
                on_progress=capture_progress)
        tokens = _normalize_captured_page_tokens(rendered_tokens, source=url)
    except Exception as e:
        traceback.print_exc()
        if wanted is None:
            raise RuntimeError(f"source capture failed before block detection: {e}") from e
        captured = {b["selector"]: {"error": f"не удалось снять DOM-слепок: {e}"}
                    for b in wanted}
        tokens = None
    stage_done("captureCompile")

    stage_started = time.perf_counter()
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
    stage_done("assemble")
    # Fail-closed прогрев кэша: harness рендерит финальные IR в точном размере
    # каждого viewport и сравнивает со скриншотами источника. Нет обязательных
    # метрик или gate не пройден → записи нет, но IR всё равно возвращается.
    stage_started = time.perf_counter()
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
            viewport_metrics = report.get("viewports") or {}
            block["fidelity"] = {
                name: metrics.get("pixel_similarity")
                for name, metrics in viewport_metrics.items()
                if isinstance(metrics, dict) and metrics.get("pixel_similarity") is not None
            }
            block["paintCoverage"] = {
                name: metrics.get("paint_coverage")
                for name, metrics in viewport_metrics.items()
                if isinstance(metrics, dict) and metrics.get("paint_coverage") is not None
            }
            block["p95LayoutError"] = {
                name: metrics.get("bbox_p95")
                for name, metrics in viewport_metrics.items()
                if isinstance(metrics, dict) and metrics.get("bbox_p95") is not None
            }
    payload["sourceArtifact"] = _build_source_artifact(
        url, results, payload_tokens, authenticated)
    payload["ambiguities"] = collect_ambiguities(results)
    stage_done("fidelity")
    stage_started = time.perf_counter()
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
    stage_done("cacheWrite")
    return _finish_source_import(
        payload,
        timings_ms=timings_ms,
        started_at=run_started,
        cached=False,
        authenticated=authenticated,
    )
