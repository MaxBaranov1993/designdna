"""Скрейп сайта, воспроизведение экрана по скриншоту и сегментация: /api/scrape, /api/reproduce, /api/reproduce/segment."""
import base64
import io
import json
import re
import traceback
from pydantic import BaseModel
import llm_client as llm
from scraper import analyze_url
from reproduce import run_pipeline as reproduce_pipeline
from urlguard import validate_public_url
import cache_store
import blockparse
import ir
from ir import ensure_current as ensure_current_ir
from fastapi import APIRouter
from api.common import (  # noqa: F401
    APP_ROOT, CANCELLED_STATUS, DATA_ROOT, ROOT, _finish_run, err, parse_ir_response,
    sanitize_font_face_weights, validate_ir,
)

router = APIRouter()


class ScrapeReq(BaseModel):
    url: str = ""
    use_playwright: bool = True


class ReproduceReq(BaseModel):
    image: str = ""  # base64 data URL
    url: str = ""  # или URL сайта: скриншот снимем сами, результат кэшируется
    provider: str = "auto"  # роль vision выбирает модель из ROUTING
    regions: list | None = None  # опциональные регионы для diff: [["name", x1, y1, x2, y2], ...]


class SegmentReq(BaseModel):
    """Агент-сегментатор скриншота. prepareOnly отдаёт задания разметки по
    тайлам для провайдера пользователя (Claude/GPT); rawOutputs — ответы;
    сервер валидирует рамки против пикселей и схлопывает повторы."""
    image: str = ""  # base64 data URL скриншота
    prepareOnly: bool = False
    rawOutputs: list = []  # [{tileIndex, content}]


@router.post("/api/scrape")
def scrape(req: ScrapeReq):
    """Полный анализ реального сайта: контент + стили + структура + скриншот."""
    url = req.url.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    try:
        validate_public_url(url)  # SSRF-гард (422, а не 502)
    except ValueError as e:
        return err(422, str(e))
    try:
        data = analyze_url(url, use_playwright=req.use_playwright)
    except Exception as e:
        return err(502, f"Ошибка анализа: {e}")

    return {
        "url": data.url,
        "title": data.title,
        "text_content": data.text_content[:4000],
        "structure": data.structure,
        "tokens": data.tokens,
        "screenshot": f"data:image/png;base64,{data.screenshot_b64}" if data.screenshot_b64 else "",
        "viewport": data.viewport,
    }


def _with_reproduce_parser_contract(payload: dict, source_ref: str, source_kind: str) -> dict:
    """Attach Parser v2 metadata to cached and fresh screenshot reproductions."""
    if isinstance(payload.get("parserContract"), dict):
        return payload
    document = payload.get("ir")
    if not isinstance(document, dict) or not document:
        return payload
    # Пустое дерево (VLM ничего не распознал, старый кэш): конверту нечего
    # описывать — nodeStates обязан быть непустым, иначе валидация роняла 500.
    if not isinstance(document.get("tree"), list) or not document["tree"]:
        return payload
    diff = payload.get("diff") if isinstance(payload.get("diff"), dict) else {}
    fidelity = diff.get("overall_pct")
    capture = {
        "preview": payload.get("repro_png") or "",
        "fidelity": fidelity,
        "warnings": [diff["error"]] if diff.get("error") else [],
    }
    return {
        **payload,
        "parserContract": ir.build_parser_envelope(
            document,
            url=source_ref,
            selector="screenshot",
            label="Website screenshot" if source_kind == "url" else "Uploaded screenshot",
            parser_version="vision-v2",
            kind=source_kind,
            capture=capture,
        ),
    }


@router.post("/api/reproduce")
def reproduce(req: ReproduceReq):
    """Pixel-perfect reproduction: скриншот → VLM-структура → Python-измерения → HTML → diff.

    Работает с любым провайдером для VLM-анализа. Все измерения — из пикселей.
    Повторный запрос того же скриншота/сайта — из кэша, без траты токенов.
    """
    provider = req.provider if req.provider in ("openai", "astra", "claude", "codex") else "auto"
    url = req.url.strip()
    image = req.image
    url_key = None
    if url:
        try:
            validate_public_url(url)
        except ValueError as e:
            return err(422, str(e))
        url_key = cache_store.key_url(url)
        if provider != "auto":
            url_key = f"{url_key}:{provider}"
        hit = cache_store.get("reproduce_url", url_key)
        if hit:
            return {**_with_reproduce_parser_contract(hit, url, "url"), "cached": True}
        # скриншот сайта снимаем один раз — дальше он же и кэшируется
        try:
            page = analyze_url(url, use_playwright=True)
        except Exception as e:
            return err(502, f"Не удалось снять скриншот {url}: {e}")
        if not page.screenshot_b64:
            return err(502, "Пустой скриншот сайта.")
        image = f"data:image/png;base64,{page.screenshot_b64}"
    if not image:
        return err(422, "Нужно изображение (base64 data URL) или URL сайта.")

    # кэш по хэшу изображения: тот же скриншот от любого пользователя — бесплатно
    img_key = cache_store.key_image(image)
    if provider != "auto":
        img_key = f"{img_key}:{provider}"
    hit = cache_store.get("reproduce_img", img_key)
    if hit:
        source_ref = url or f"image-sha256:{img_key}"
        source_kind = "url" if url else "image"
        return {**_with_reproduce_parser_contract(hit, source_ref, source_kind), "cached": True}

    regions = None
    if req.regions:
        regions = [tuple(r) for r in req.regions]

    try:
        result = reproduce_pipeline(
            image_b64=image,
            provider=provider,
            llm_module=llm,
            regions=regions,
        )
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка пайплайна: {e}")

    payload = {
        "structure": result.get("structure", {}),
        "colors": result.get("colors", {}),
        "measurements": result.get("measurements", {}),
        "icons_count": len(result.get("icons", [])),
        "contents_count": len(result.get("contents", [])),
        "html": result.get("html", ""),
        "diff": result.get("diff", {}),
        "ir": ensure_current_ir(result.get("ir", {}), source="reproduce"),
        "repro_png": f"data:image/png;base64,{result['repro_png_b64']}" if result.get("repro_png_b64") else "",
        "provider_used": provider,
    }
    source_ref = url or f"image-sha256:{img_key}"
    source_kind = "url" if url else "image"
    payload = _with_reproduce_parser_contract(payload, source_ref, source_kind)
    cache_store.put("reproduce_img", img_key, payload)
    if url_key:
        cache_store.put("reproduce_url", url_key, payload)
    return {**payload, "cached": False}


@router.post("/api/reproduce/segment")
def reproduce_segment(req: SegmentReq):
    """Скриншот → границы компонентов через агента с детерминированной проверкой.

    Контракт тот же, что у AI-починки: модель только размечает, сервер
    клампит координаты, отклоняет рамки без пиксельного содержимого и
    группирует повторы. Ни одна цифра модели не принимается на веру.
    """
    import numpy as np
    from PIL import Image as PILImage

    import screenshot_segmenter as seg

    image = req.image or ""
    if not image.startswith("data:image"):
        return err(422, "Нужен скриншот как base64 data URL.")
    try:
        raw = base64.b64decode(image.split(",", 1)[1])
        img = PILImage.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        return err(422, f"Не удалось декодировать изображение: {e}")
    width, height = img.size
    tiles = seg.tile_grid(width, height)
    if not tiles:
        return err(422, "Пустое изображение.")

    if req.prepareOnly:
        tasks = []
        for tile in tiles:
            crop = img.crop((tile["x"], tile["y"],
                             tile["x"] + tile["width"], tile["y"] + tile["height"]))
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG")
            data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
            tasks.append({
                "tileIndex": tile["index"],
                "messages": seg.build_segment_prompt(
                    tile, data_url, {"width": width, "height": height}),
            })
        return {"tasks": tasks, "imageSize": {"width": width, "height": height}}

    arr_rgb = np.array(img)
    tiles_by_index = {tile["index"]: tile for tile in tiles}
    regions: list[dict] = []
    rejected = 0
    for item in req.rawOutputs or []:
        if not isinstance(item, dict):
            continue
        tile = tiles_by_index.get(item.get("tileIndex"))
        if tile is None:
            continue
        match = re.search(r"\{.*\}", str(item.get("content") or ""), re.S)
        if not match:
            rejected += 1
            continue
        try:
            parsed = json.loads(match.group(0))
            validated = seg.validate_regions(parsed, tile, arr_rgb)
        except (ValueError, json.JSONDecodeError):
            rejected += 1
            continue
        regions.extend(validated)
    merged = seg.merge_regions(regions)
    # Сразу собираем Source-блок: рамки → boundary-узлы с растровыми кропами.
    # Фронту не из чего собирать IR самому — вся геометрия и пиксели тут.
    import screenshot_capture
    block = screenshot_capture.build_screenshot_block(image, merged)
    block["ir"] = ensure_current_ir(block["ir"], source="screenshot-import")
    # Тот же реестр Source, что у URL-импорта: без него раздел «Компоненты»
    # редактора дизайн-системы показывает «No Source Artifact».
    artifact = blockparse._build_source_artifact(
        "screenshot", [block], block["ir"].get("tokens"), False)
    return {
        "ok": True,
        "imageSize": {"width": width, "height": height},
        "regions": merged,
        "repeatGroups": sorted({r["repeatGroup"] for r in merged if r.get("repeatGroup")}),
        "rejectedOutputs": rejected,
        "block": block,
        "tokens": block["ir"].get("tokens"),
        "sourceArtifact": artifact,
    }
