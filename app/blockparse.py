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
import hashlib
import json
import traceback
from pathlib import Path

from bs4 import BeautifulSoup

import llm_client as llm
import cache_store
from scraper import fetch_html, detect_blocks, rendered_html, capture_block_irs

import jsonschema

ROOT = Path(__file__).resolve().parent.parent

MAX_WORKERS = 4            # как EXECUTOR в server.py
FRAGMENT_LIMIT = 12000     # HTML блока в промпте, символов
STYLES_LIMIT = 6000        # CSS страницы в промпте, символов
DEFAULT_PROVIDER = "openrouter"  # роль clone/repair выбирает модель из ROUTING

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)

_SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = jsonschema.Draft7Validator(_SCHEMA)

_SEMANTIC_ROLES = {
    "header", "footer", "carousel", "categories", "product-grid", "services-grid",
    "journal", "how-it-works", "faq", "cta", "trust", "pricing", "testimonials",
    "gallery", "section",
}

SOURCE_COMPILER_VERSION = "dom-v21"


def _validate(ir: dict) -> list:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return sorted(
        (f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
         for e in _VALIDATOR.iter_errors(ir)),
        key=str,
    )


def _block_cache_key(url: str, name: str, selector: str) -> str:
    # Bump when the deterministic DOM compiler or responsive merge contract changes.
    raw = f"{SOURCE_COMPILER_VERSION}|{url.strip().lower().rstrip('/')}|{name}|{selector}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _refine_ambiguous_blocks(html: str, blocks: list[dict], provider: str) -> list[dict]:
    """Use a small semantic LLM pass only when DOM/tag/class heuristics are unsure.

    Selectors and geometry remain deterministic. The model can label a candidate,
    but cannot invent, resize, merge or reorder source blocks.
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
        ], 0.1, role="source_semantics")
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


def parse_blocks(url: str, blocks: list | None = None,
                 provider: str = DEFAULT_PROVIDER,
                 viewports: list[dict] | None = None) -> dict:
    """BlockParse: список блоков-IR + design-токены по URL.

    blocks — опциональный список {name, selector}: клонировать только их
    (экономия LLM-вызовов, §7.4); по умолчанию — все найденные detect_blocks.
    Ошибка отдельного блока возвращается в его записи, остальные продолжаются.
    """
    url = url.strip()

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
    viewport_key = json.dumps(viewports or "default", sort_keys=True, separators=(",", ":"))
    full_key = cache_store.key_url(SOURCE_COMPILER_VERSION + "|" + viewport_key + "|" + url)
    if wanted is None:
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
            html = rendered_html(url)  # внутри SSRF-гард
        except ValueError:
            raise
        except Exception:
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
        captured, rendered_tokens = capture_block_irs(url, wanted, return_tokens=True, viewports=viewports)
        if rendered_tokens:
            tokens = rendered_tokens
    except Exception as e:
        traceback.print_exc()
        captured = {b["selector"]: {"error": f"не удалось снять DOM-слепок: {e}"}
                    for b in wanted}

    results = []
    for b in wanted:  # порядок детекции остаётся порядком выходных портов
        head = {"name": b["name"], "selector": b["selector"],
                "label": b.get("label") or b["name"], "kind": b.get("kind", "section")}
        item = captured.get(b["selector"], {"error": "DOM-слепок не получен"})
        if item.get("error"):
            # Responsive duplicates that are hidden at the canonical desktop viewport
            # are not meaningful Source Import outputs.
            if "не виден" in str(item["error"]):
                continue
            results.append({**head, "error": item["error"]})
            continue
        ir = item.get("ir")
        errors = _validate(ir) if isinstance(ir, dict) else ["DOM-слепок не является IR"]
        if errors:
            results.append({**head, "error": "внутренняя ошибка DOM-импорта: " + "; ".join(errors[:3])})
            continue
        cache_store.put("clone_block", _block_cache_key(url, b["name"], b["selector"]), {"ir": ir})
        results.append({**head, "ir": ir, "cached": False, "source": "dom",
                        "layers": item.get("layer_count", 0), "size": {
                            "width": item.get("width"), "height": item.get("height")},
                        "preview": item.get("preview"), "previews": item.get("previews", {}),
                        "sizes": item.get("sizes", {}),
                        "layersByViewport": item.get("layers_by_viewport", {}),
                        "coverage": item.get("coverage", {}),
                        "fidelity": item.get("fidelity"),
                        "warnings": item.get("warnings", []), "repeat": item.get("repeat")})

    payload = {"url": url, "blocks": results, "tokens": tokens}
    # Сохраняем только полностью успешный разбор. Отдельные удачные блоки уже
    # имеют свой clone_block-кэш; неудачные должны иметь шанс на повтор.
    if blocks is None and not any(block.get("error") for block in results if isinstance(block, dict)):
        cache_store.put("blockparse_url", full_key, payload)
    return {**payload, "cached": False}
