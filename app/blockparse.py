"""BlockParse: детекция блоков страницы и параллельный clone каждого в Design IR.

Обвязка над готовыми механизмами (docs/NODES-HOUDINI.md §7.3):
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
import re
import traceback
from pathlib import Path

from bs4 import BeautifulSoup

import llm_client as llm
import cache_store
from scraper import fetch_html, detect_blocks, extract_css, parse_design_tokens

import jsonschema

ROOT = Path(__file__).resolve().parent.parent

MAX_WORKERS = 4            # как EXECUTOR в server.py
FRAGMENT_LIMIT = 12000     # HTML блока в промпте, символов
STYLES_LIMIT = 6000        # CSS страницы в промпте, символов
DEFAULT_PROVIDER = "qwen"  # решение владельца 7: разработка/ревью — только qwencloud

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)

_SCHEMA = json.loads((ROOT / "schema" / "design-ir.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = jsonschema.Draft7Validator(_SCHEMA)


def _validate(ir: dict) -> list:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return sorted(
        (f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
         for e in _VALIDATOR.iter_errors(ir)),
        key=str,
    )


def _block_cache_key(url: str, name: str, selector: str) -> str:
    raw = f"{url.strip().lower().rstrip('/')}|{name}|{selector}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clone_block_prompt(name: str, selector: str, styles: str, fragment: str) -> str:
    return (
        "Ты — senior фронтенд-разработчик и дизайн-инженер. Тебе дали HTML+CSS реальной страницы.\n"
        f"Задача: воспроизвести блок «{name}» (на странице он выбран селектором {selector}) "
        "как Design IR (JSON).\n\n"
        "ПРАВИЛА:\n"
        "- Воспроизведи структуру блока ТОЧНО: те же элементы, тот же порядок, тот же текст.\n"
        "- НЕ добавляй элементы, которых нет в HTML.\n"
        "- НЕ убирай элементы из HTML.\n"
        "- Тексты — verbatim из HTML (не перефразируй).\n"
        "- Цвета/шрифты/радиусы — извлеки из CSS и запиши в tokens.\n"
        "- Раскладку (flex/grid/позиции) — передай через frame (layout/direction/gap/padding).\n"
        "- Верни ОДИН JSON-объект по схеме Design IR. Без markdown.\n\n"
        f"## CSS стили страницы\n{styles}\n\n## HTML блока\n{fragment}"
    )


def _clone_one(url: str, html: str, styles: str, block: dict, provider: str) -> dict:
    """Клон одного блока: кэш → фрагмент HTML → LLM(edit) → валидация → один repair."""
    name, selector = block["name"], block["selector"]
    head = {"name": name, "selector": selector}

    hit = cache_store.get("clone_block", _block_cache_key(url, name, selector))
    if hit and isinstance(hit.get("ir"), dict):
        return {**head, "ir": hit["ir"], "cached": True}

    try:
        el = BeautifulSoup(html, "lxml").select_one(selector)
    except Exception as e:
        return {**head, "error": f"не удалось выбрать элемент по селектору: {e}"}
    if el is None:
        return {**head, "error": f"блок не найден по селектору {selector!r}"}

    fragment = re.sub(r"<script[^>]*>.*?</script>", "", str(el), flags=re.S)
    fragment = re.sub(r"\s+", " ", fragment)[:FRAGMENT_LIMIT]

    def messages(user: str) -> list:
        # системный промпт режима edit, как в /api/clone
        return [{"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": user}]

    try:
        raw = llm.chat(provider, messages(_clone_block_prompt(name, selector, styles, fragment)),
                       0.2, role="clone")
    except Exception as e:
        return {**head, "error": f"LLM-вызов: {e}"}

    try:
        ir = json.loads(llm.extract_json(raw))
    except (json.JSONDecodeError, ValueError) as e:
        return {**head, "error": f"невалидный JSON от модели: {e}"}

    errors = _validate(ir) if isinstance(ir, dict) else ["модель вернула не объект"]
    if errors:
        # один repair-вызов — существующий паттерн /api/clone
        repair = (
            "Следующий JSON не прошёл валидацию. Ошибки:\n- " + "\n- ".join(errors[:8]) +
            "\n\nИсправь минимально и верни только JSON:\n\n" + json.dumps(ir, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, messages(repair), 0.2, role="repair")
            ir2 = json.loads(llm.extract_json(raw2))
            if isinstance(ir2, dict) and not _validate(ir2):
                ir, errors = ir2, []
        except Exception:
            pass
    if errors:
        return {**head, "error": "блок не прошёл валидацию после repair: " + "; ".join(errors[:5])}

    cache_store.put("clone_block", _block_cache_key(url, name, selector), {"ir": ir})
    return {**head, "ir": ir, "cached": False}


def parse_blocks(url: str, blocks: list | None = None,
                 provider: str = DEFAULT_PROVIDER) -> dict:
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
    full_key = cache_store.key_url(url)
    if wanted is None:
        hit = cache_store.get("blockparse_url", full_key)
        if hit:
            return {**hit, "cached": True}

    try:
        html = fetch_html(url)  # внутри SSRF-гард
    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(f"не удалось загрузить {url}: {e}")

    if wanted is None:
        wanted = detect_blocks(html)
    if not wanted:
        raise RuntimeError("на странице не найдено ни одного блока "
                           "(нет семантических тегов и заголовков)")

    styles = extract_css(html)
    tokens = parse_design_tokens(styles)

    futures = {_EXECUTOR.submit(_clone_one, url, html, styles, b, provider): b
               for b in wanted}
    results = []
    for f, b in futures.items():  # порядок wanted сохранён — dict упорядочен
        try:
            results.append(f.result())
        except Exception as e:  # ошибка блока не роняет остальные
            traceback.print_exc()
            results.append({"name": b["name"], "selector": b["selector"], "error": str(e)})

    payload = {"url": url, "blocks": results, "tokens": tokens}
    if blocks is None:
        cache_store.put("blockparse_url", full_key, payload)
    return {**payload, "cached": False}
