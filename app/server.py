#!/usr/bin/env python3
"""DesignAI Web — локальный dev-сервер генерации веб-дизайна (Design IR).

Запуск:  .venv/Scripts/python app/server.py   (порт 8420)
"""
import concurrent.futures
import contextlib
import copy
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
import uuid
import webbrowser
from pathlib import Path

# Windows: реестр может не знать MIME для .js/.css/woff — без корректного
# content-type браузер отказывается выполнять module-скрипты сборки /flow
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from interaction_capture import capture_live_flow
from motion_render import render_video, validate_render_input

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client as llm  # chat, chat_vision, build_system_prompt, extract_json
from colorutils import mix_hex_colors
from scraper import analyze_url
from reproduce import run_pipeline as reproduce_pipeline
from urlguard import validate_public_url
import cache_store
import blockparse
import mergeback
import qualitygate
import generation_quality
import visual_quality
import project_store
import typography
import designkb
import video_client

import ir
from ir import ensure_current as ensure_current_ir
from config import FEATURE_FLAGS

EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
VARIANT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
RENDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
RENDER_JOBS: dict[str, dict] = {}
RENDER_JOBS_LOCK = threading.Lock()
RENDER_DIR = ROOT / "data" / "renders"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    EXECUTOR.shutdown(wait=True)
    VARIANT_EXECUTOR.shutdown(wait=True)
    RENDER_EXECUTOR.shutdown(wait=True)
    llm.GLOBAL_AI_QUEUE.shutdown()


app = FastAPI(title="DesignAI Web", docs_url=None, redoc_url=None, lifespan=lifespan)

COLOR_TOKEN_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"]
PRODUCT_PROVIDER = "codex"

# роли вызовов для Codex routing — см. таблицу llm_client.ROUTING
# (generate/edit/repair/clone/reference/...)


# ---------- helpers ----------

def validate_ir(doc: dict) -> list[str]:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    if isinstance(doc, dict):
        ir.repair_for_schema(doc)
    return ir.format_errors(ir.validate_ir(doc))


def parse_ir_response(raw: str):
    """extract_json + json.loads -> (ir, error)."""
    try:
        return json.loads(llm.extract_json(raw)), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"невалидный JSON от модели: {e}"


def call_llm_ir(provider: str, user_content: str, temperature: float = 0.8,
                mode: str = "generate", timeout: float | None = None):
    """Вызов LLM с системным промптом генератора -> (ir, error)."""
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt(mode)},
            {"role": "user", "content": user_content},
        ], temperature, timeout=timeout,
            role="generator" if mode == "generate" else "edit")
    except llm.AIRequestError as e:
        return None, {"reason": e.reason, "error": e.detail}
    except Exception as e:
        return None, {"reason": "лимит провайдера", "error": str(e)}
    parsed, parse_error = parse_ir_response(raw)
    if parsed is None:
        return None, {"reason": "лимит провайдера", "error": parse_error}
    return parsed, None


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def normalize_provider(provider: str | None) -> str:
    # Старые сейвы могли передавать имя прямого провайдера. Продукт всегда
    # использует пользовательское Codex-подключение, поэтому вход не выбирает
    # внешний транспорт и не может переключить ноду на другой vendor.
    return PRODUCT_PROVIDER


# ---------- models ----------

class GenerateReq(BaseModel):
    brief: str = ""
    count: int = 3
    provider: str = "codex"
    styleHint: str | None = None
    seedTag: str | None = None
    tokens: dict | None = None  # Style DNA: залоченные design-токены
    preset: str = ""  # стилевой пресет: minimal|bento|editorial|brutal|glass
    deadlineSeconds: float | None = None
    tasteEnabled: bool = True
    tasteWeight: float = Field(default=0.35, ge=0.0, le=1.0)
    tasteScope: str = "project"  # project|recent|none


class MixReq(BaseModel):
    irs: list
    weights: list


class CloneReq(BaseModel):
    url: str = ""
    component: str = ""
    provider: str = "codex"


class BlockParseReq(BaseModel):
    url: str = ""
    blocks: list | None = None  # опционально: [{name, selector}] — клонировать только их
    viewports: list[dict] | None = None


class ReskinReq(BaseModel):
    ir: dict
    prompt: str = ""
    tokens: dict | None = None  # источник нового стиля (design-токены)
    mask: dict = {}             # чекбоксы: colors/fonts/radii/shadows/texts/images


class QualityGateReq(BaseModel):
    ir: dict
    fix: bool = True  # авто-доводка solver'ом (без LLM) того, что чинится


class QualityPassReq(BaseModel):
    ir: dict
    brief: str = ""
    min_score: int = 85
    repair: bool = True
    rejudge: bool = True


class ConstraintsCheckReq(BaseModel):
    ir: dict
    constraints: list  # [{path, lock?, min?, max?, enum?, max_len?}]


class StyleDnaReq(BaseModel):
    ir: dict


class StyleDnaApplyReq(BaseModel):
    ir: dict
    tokens: dict


class EditorAssistScope(BaseModel):
    sourceKeys: list[str] = Field(default_factory=list)
    viewport: str = "current"


class EditorAssistConstraints(BaseModel):
    allowStructure: bool = False
    allowContent: bool = True
    allowStyle: bool = True
    allowFrame: bool = True


class EditorAssistReq(BaseModel):
    ir: dict
    prompt: str = ""
    action: str = "custom"
    scope: EditorAssistScope = Field(default_factory=EditorAssistScope)
    constraints: EditorAssistConstraints = Field(default_factory=EditorAssistConstraints)


class StyleNormalizeReq(BaseModel):
    ir: dict
    tolerance: float = 0.12


class TailwindProjectionReq(BaseModel):
    ir: dict
    mode: str = "exact"


class InteractionBuildReq(BaseModel):
    base_ir: dict
    source: dict = Field(default_factory=dict)
    scenes: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    variables: dict = Field(default_factory=dict)


class InteractionValidateReq(BaseModel):
    interaction: dict


class InteractionReplayReq(BaseModel):
    base_ir: dict
    interaction: dict
    scene_id: str


class InteractionCaptureReq(BaseModel):
    base_ir: dict
    url: str
    mine: bool = False
    viewport: str = "desktop"
    actions: list[dict] = Field(default_factory=list)


class MotionBuildReq(BaseModel):
    base_ir: dict
    interaction: dict | None = None
    prompt: str = ""
    composition: dict = Field(default_factory=dict)
    scene_settings: dict = Field(default_factory=dict)
    render_settings: dict = Field(default_factory=dict)


class MotionValidateReq(BaseModel):
    motion: dict
    interaction: dict | None = None


class MotionRenderReq(BaseModel):
    base_ir: dict
    interaction: dict | None = None
    motion: dict


class AiVideoGenerateReq(BaseModel):
    prompt: str
    tier: str = "studio"
    duration: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    generate_audio: bool = False
    references: list[str] = Field(default_factory=list)
    seed: int | None = None
    confirmed: bool = False


class ScrapeReq(BaseModel):
    url: str = ""
    use_playwright: bool = True


class ReproduceReq(BaseModel):
    image: str = ""  # base64 data URL
    url: str = ""  # или URL сайта: скриншот снимем сами, результат кэшируется
    provider: str = "codex"  # роль vision выбирает модель из Codex routing
    regions: list | None = None  # опциональные регионы для diff: [["name", x1, y1, x2, y2], ...]


class ProjectSaveReq(BaseModel):
    project: dict
    user_id: str = project_store.DEFAULT_USER_ID
    project_id: str = project_store.DEFAULT_PROJECT_ID


class ProjectLoadReq(BaseModel):
    user_id: str = project_store.DEFAULT_USER_ID
    project_id: str = project_store.DEFAULT_PROJECT_ID


# ---------- endpoints ----------

@app.post("/api/generate")
def generate(req: GenerateReq):
    provider = normalize_provider(req.provider)
    brief = req.brief.strip()
    if not brief:
        return err(422, "Пустой бриф: опишите, что нужно сгенерировать.")
    count = max(1, min(int(req.count or 1), 5))
    batch_timeout = req.deadlineSeconds if req.deadlineSeconds is not None else float(
        os.environ.get("AI_BATCH_DEADLINE_S", "420")
    )
    batch_timeout = max(1.0, min(float(batch_timeout), 900.0))
    batch_deadline = time.monotonic() + batch_timeout
    has_style = bool(req.styleHint and req.styleHint.strip())
    style = f"\n\n## Reference / style context\n{req.styleHint.strip()}" if has_style else ""
    taste_scope = req.tasteScope if req.tasteScope in {"project", "recent", "none"} else "project"
    memory_hint = project_store.build_prompt_memory_hint(
        weight=req.tasteWeight if req.tasteEnabled else 0.0,
        scope=taste_scope if req.tasteEnabled else "none",
    )
    memory = f"\n\n{memory_hint}" if memory_hint else ""
    mode = "edit" if has_style else "generate"
    dna_keys = ("mode", "color", "font", "radius", "spacing", "shadow")
    if isinstance(req.tokens, dict):
        dna = {k: v for k, v in req.tokens.items() if k in dna_keys}
        if not dna:
            dna = None
    else:
        dna = None
    preset = typography.PRESETS.get(req.preset or "")
    ptype, pinfo = designkb.detect_product(brief)
    # Compile a deterministic art-direction contract before the creative call.
    # This keeps the node's UX simple while giving the model concrete visual
    # intent, layout, content and asset constraints even for short prompts.
    art_direction = designkb.compile_art_direction(
        brief,
        ptype,
        pinfo,
        preset_label=(preset.get("label") if preset else ""),
        style_hint=req.styleHint or "",
    )
    active_design_skills = designkb.select_design_skills(
        brief,
        preset_label=(preset.get("label") if preset else ""),
        style_hint=req.styleHint or "",
    )
    # Шрифт из Style DNA — без подбора своей пары; иначе — библиотека typography.
    # Предпочтение: пресет → рекомендация design KB по типу продукта → настроение брифа.
    pair = None
    if not (dna and isinstance(dna.get("font"), dict)):
        pair = typography.pick_pair(
            set(preset["moods"]) if preset else typography.brief_moods(brief),
            prefer=(preset.get("font") if preset else None) or pinfo["fonts"][0])
    scale = typography.type_scale()

    def gen_one(n: int):
        if mode == "edit":
            user = (
                f"## Reference context\n{req.styleHint.strip()}\n\n"
                f"## Modification instruction\n{brief}\n\n"
                f"REPRODUCE the reference structure and content EXACTLY. "
                f"Apply ONLY the modification above. Do NOT add or remove sections/elements. "
                f"Do NOT invent content not present in the reference."
            )
        else:
            vary = ("своя композиция, раскладка и настроение в рамках токенов DNA" if dna
                    else "своя палитра, типографика, настроение и композиция")
            user = (
                f"## Brief\n{brief}\n\n"
                f"Вариант {n} из {count}: сделай визуально отличное решение №{n} — "
                f"{vary}, не повторяй другие варианты."
            )
        if req.seedTag:
            user += f"\nseedTag: {req.seedTag}"
        if style and mode != "edit":
            user += style
        if memory:
            user += memory
        if mode == "generate":
            user += "\n\n" + art_direction
        if dna:
            user += ("\n\n## Style DNA — обязательные design-токены (залочены)\n"
                     + json.dumps(dna, ensure_ascii=False)
                     + "\nГотовый IR обязан использовать эти tokens в точности "
                       "(mode/color/font/radius/spacing/shadow): вариативность — "
                       "в композиции и контенте, не в токенах.")
            if preset:
                user += (f"\n\nСтилевое направление «{preset['label']}»: "
                         + preset["prompt"])
        elif pair:
            user += "\n\n" + typography.typography_guide(pair, scale, preset)
        palette = None
        if mode == "generate":
            if not dna:
                direction, palette = designkb.design_direction(ptype, pinfo, n)
                user += "\n\n" + direction
            else:
                user += ("\n\nАнти-паттерны — НИКОГДА так не делай:\n"
                         + "\n".join("- " + a for a in designkb.ANTI_AI))
        remaining = batch_deadline - time.monotonic()
        if remaining <= 0:
            return None, {"reason": "таймаут", "error": "общий deadline batch истёк"}, None
        ir, error = call_llm_ir(
            provider, user, 0.8 if mode == "generate" else 0.3, mode,
            timeout=remaining,
        )
        qa = None
        if ir is not None:
            if dna:
                # DNA залочена: токены — не предмет вариативности, фиксируем детерминированно
                ir["tokens"] = copy.deepcopy(dna)
            elif isinstance(ir.get("tokens"), dict):
                # без DNA: шрифтовая пара и кураторская палитра из design KB — лок
                if pair:
                    ir["tokens"]["font"] = typography.font_tokens(pair)
                if palette:
                    ir["tokens"]["color"] = dict(palette)
            # сгенерированный IR — responsive-документ: вьюпорты артборда, чтобы
            # Page/редактор переключали устройства и per-device правки имели куда писаться
            ir.setdefault("responsive", {"viewports": {
                "desktop": {"width": 1440}, "tablet": {"width": 768}, "mobile": {"width": 390}}})
            ir, acceptance = _run_generation_acceptance(ir, brief, n, batch_deadline)
            qa = acceptance
            if ir is None:
                return None, {
                    "reason": "quality rejected",
                    "error": acceptance.get("summary", "Вариант не прошёл quality acceptance."),
                    "issues": acceptance.get("issues", [])[:8],
                    "score": acceptance.get("score", 0),
                }, acceptance
        return ir, error, qa

    futures = {VARIANT_EXECUTOR.submit(gen_one, i + 1): i + 1 for i in range(count)}
    variants, errors, qa = [], [], []
    pending = set(futures)
    while pending:
        remaining = batch_deadline - time.monotonic()
        if remaining <= 0:
            break
        done, pending = concurrent.futures.wait(
            pending, timeout=remaining,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        if not done:
            break
        for future in done:
            index = futures[future]
            try:
                generated_ir, failure, result_qa = future.result()
            except Exception as exc:
                generated_ir, failure, result_qa = None, {
                    "reason": "лимит провайдера", "error": str(exc),
                }, None
            if generated_ir is not None:
                variants.append((index, generated_ir))
                qa.append(result_qa)
            else:
                detail = failure if isinstance(failure, dict) else {
                    "reason": "лимит провайдера", "error": str(failure),
                }
                errors.append({"index": index, **detail})
    for future in pending:
        index = futures[future]
        future.cancel()
        errors.append({
            "index": index,
            "reason": "таймаут",
            "error": "отменено после общего deadline batch",
        })
    variants.sort(key=lambda item: item[0])
    qa.sort(key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0)
    errors.sort(key=lambda item: item["index"])
    ready_variants = [item[1] for item in variants]
    if errors and ready_variants:
        reason = "частичный результат"
    elif errors:
        reason = errors[0]["reason"]
    else:
        reason = None
    return {"variants": ready_variants, "errors": errors, "qa": qa,
            "reason": reason, "complete": not errors,
            "design": {"type": ptype, "label": pinfo["label"],
                       "artDirection": art_direction,
                       "skills": active_design_skills}}


@app.post("/api/mix")
def mix(req: MixReq):
    irs, weights = req.irs, [float(w) for w in req.weights]
    if not irs:
        return err(422, "Нужен хотя бы один IR для микса.")
    if len(irs) != len(weights):
        return err(422, "Количество IR и весов не совпадает.")
    if any(w < 0 for w in weights):
        return err(422, "Веса должны быть >= 0.")

    dom = max(range(len(irs)), key=lambda i: weights[i])  # при всех нулях -> 0
    result = copy.deepcopy(irs[dom])
    if not isinstance(result, dict):
        return err(422, f"IR #{dom + 1} не является объектом.")
    result_colors = result.setdefault("tokens", {}).setdefault("color", {})

    # цвета — взвешенный микс в OKLCH
    for key in COLOR_TOKEN_KEYS:
        pairs = [(ir["tokens"]["color"][key], weights[i])
                 for i, ir in enumerate(irs)
                 if isinstance(ir, dict) and key in ir.get("tokens", {}).get("color", {})]
        if pairs:
            result_colors[key] = mix_hex_colors(pairs)

    meta = result.setdefault("meta", {})
    if "name" in meta:
        meta["name"] = f"{meta['name']} (mix)"
    meta["mixOf"] = [{"index": i, "weight": weights[i]} for i in range(len(irs))]
    return {"ir": ensure_current_ir(result, source="mix")}


@app.post("/api/clone")
def clone(req: CloneReq):
    """Клонирование компонента с внешнего сайта: fetch HTML → LLM → IR."""
    url = req.url.strip()
    component = req.component.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    if not component:
        return err(422, "Опишите, какой компонент клонировать.")
    provider = normalize_provider(req.provider)

    # SSRF-гард: только публичные http/https URL
    try:
        validate_public_url(url)
    except ValueError as e:
        return err(422, str(e))

    # кэш: тот же сайт повторно — без траты токенов
    hit = cache_store.get("clone_url", cache_store.key_url(url))
    if hit:
        return {**hit, "cached": True}

    # fetch страницы
    try:
        req_obj = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.9",
        })
        with urllib.request.urlopen(req_obj, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return err(502, f"Не удалось загрузить {url}: {e}")

    # извлекаем стили и body (обрезаем до 12000 символов чтобы уложиться в контекст)
    styles = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))[:6000]
    body = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)  # убираем скрипты
    body = re.sub(r"\s+", " ", body)[:12000]

    user = (
        "Ты — senior фронтенд-разработчик и дизайн-инженер. Тебе дали HTML+CSS реальной страницы.\n"
        f"Задача: выделить компонент «{component}» из этой страницы и представить его как Design IR (JSON).\n\n"
        "ПРАВИЛА:\n"
        "- Воспроизведи структуру компонента ТОЧНО: те же элементы, тот же порядок, тот же текст.\n"
        "- НЕ добавляй элементы, которых нет в HTML.\n"
        "- НЕ убирай элементы из HTML.\n"
        "- Тексты — verbatim из HTML (не перефразируй).\n"
        "- Цвета/шрифты/радиусы — извлеки из CSS и запиши в tokens.\n"
        "- Раскладку (flex/grid/позиции) — передай через frame (layout/direction/gap/padding).\n"
        "- Верни ОДИН JSON-объект по схеме Design IR. Без markdown.\n\n"
        f"## CSS стили\n{styles}\n\n## HTML страницы\n{body}"
    )
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], 0.2, role="clone")
    except Exception as e:
        return err(502, str(e))
    ir, error = parse_ir_response(raw)
    if ir is None:
        return err(502, error)
    errors = validate_ir(ir)
    if errors:
        # repair
        repair = (
            "Следующий JSON не прошёл валидацию. Ошибки:\n- " + "\n- ".join(errors[:8]) +
            "\n\nИсправь минимально и верни только JSON:\n\n" + json.dumps(ir, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": repair},
            ], 0.2, role="repair")
            ir2, _ = parse_ir_response(raw2)
            if ir2 and not validate_ir(ir2):
                ir = ir2
        except Exception:
            pass
    cache_store.put("clone_url", cache_store.key_url(url), {"ir": ir})
    return {"ir": ensure_current_ir(ir, source="clone"), "cached": False}


# ---------- Source Import / Reskin (см. docs/ARCHITECTURE.md и docs/NODES.md) ----------

# человекочитаемые категории маски для промпта Reskin
_MASK_LABELS = {
    "colors": "цвета (tokens.color, tokens.mode) и fill элементов",
    "fonts": "шрифты (tokens.font: family/weight/scale)",
    "radii": "радиусы (tokens.radius)",
    "shadows": "тени (tokens.shadow)",
    "texts": "тексты в props (заголовки, подписи, кнопки)",
    "images": "изображения (src/imagePrompt/alt/aspect)",
}


@app.post("/api/block-parse")
def block_parse(req: BlockParseReq):
    """BlockParse: детекция блоков страницы + параллельный clone каждого в IR."""
    url = req.url.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    try:
        validate_public_url(url)  # SSRF-гард (422, а не 502)
    except ValueError as e:
        return err(422, str(e))
    try:
        return blockparse.parse_blocks(url, blocks=req.blocks, viewports=req.viewports)
    except ValueError as e:  # кривой список блоков
        return err(422, str(e))
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка block-parse: {e}")


@app.post("/api/reskin")
def reskin(req: ReskinReq):
    """Reskin: AI-рестайл блока с локом структуры.

    LLM через GPT Codex → детерминированный merge-back
    (залоченные поля принудительно из входного IR) → валидация по схеме →
    один repair-вызов по существующему паттерну. Дрейф структуры невозможен.
    """
    errors = validate_ir(req.ir)
    if errors:
        return err(422, "Входной IR невалиден: " + "; ".join(errors[:5]))

    mask = mergeback.normalize_mask(req.mask)
    if not any(mask.values()):
        return {"ir": req.ir,
                "log": ["пустая маска: возвращён входной IR без LLM-вызова"]}

    allowed = "\n".join(f"- {label}" for key, label in _MASK_LABELS.items() if mask[key])
    user = (
        "Ты — дизайн-инженер. Ниже — Design IR блока и источник нового стиля.\n"
        "Верни ПОЛНЫЙ Design IR того же блока в новом стиле: один JSON по схеме, без markdown.\n\n"
        "ЖЁСТКИЕ ОГРАНИЧЕНИЯ (проверяются программой, нарушения будут отброшены):\n"
        "- структура дерева НЕ меняется: те же секции и элементы, id, типы, порядок, вложенность;\n"
        "- frame (геометрия и раскладка) НЕ меняется;\n"
        "- props-разметка (состав ключей, варианты, ссылки, иконки) НЕ меняется;\n"
        f"- менять разрешено ТОЛЬКО:\n{allowed}\n\n"
        f"## Входной Design IR\n{json.dumps(req.ir, ensure_ascii=False)}"
    )
    if req.tokens:
        user += f"\n\n## Design-токены нового стиля (источник)\n{json.dumps(req.tokens, ensure_ascii=False)}"
    if req.prompt.strip():
        user += f"\n\n## Пожелания по новому стилю\n{req.prompt.strip()}"

    provider = PRODUCT_PROVIDER  # reskin остаётся в пользовательском Codex routing
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], 0.7, role="reskin")
    except Exception as e:
        return err(502, str(e))
    model_ir, parse_error = parse_ir_response(raw)
    if model_ir is None:
        return err(502, parse_error)

    # детерминированный merge-back: залоченные поля — из входа, попытки в журнал
    merged, journal = mergeback.merge_back(req.ir, model_ir, mask)
    errors = validate_ir(merged)
    if errors:
        # один repair-вызов; после repair — повторный merge-back
        repair = (
            "Следующий JSON не прошёл валидацию по схеме. Ошибки:\n- " + "\n- ".join(errors[:10]) +
            "\n\nИсправь минимально и верни только исправленный JSON:\n\n" +
            json.dumps(merged, ensure_ascii=False)
        )
        try:
            raw2 = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt("edit")},
                {"role": "user", "content": repair},
            ], 0.2, role="repair")
            ir2, _ = parse_ir_response(raw2)
            if ir2 is not None:
                merged2, journal2 = mergeback.merge_back(req.ir, ir2, mask)
                if not validate_ir(merged2):
                    merged, journal, errors = merged2, journal + journal2, []
        except Exception:
            pass
    if errors:
        return err(502, "reskin не прошёл валидацию после repair: " + "; ".join(errors[:5]))
    return {"ir": ensure_current_ir(merged, source="reskin"), "log": journal}


# ---------- Quality Gate / Constraints (решение владельца 12.2, бэклог §8) ----------

@app.post("/api/quality-gate")
def quality_gate(req: QualityGateReq):
    """Детерминированный Quality Gate: правила v1 + авто-доводка без LLM.

    passed/violations — по входному IR; fixed_ir/journal — результат solver'а
    (починено только то, что чинится детерминированно: сетка 8px, overflow).
    """
    violations = qualitygate.check(req.ir)
    if req.fix:
        fixed_ir, journal = qualitygate.autofix(req.ir)
    else:
        fixed_ir, journal = copy.deepcopy(req.ir), []
    return {"passed": not violations, "violations": violations,
            "fixed_ir": fixed_ir, "journal": journal}


QUALITY_JUDGE_SYSTEM = """Ты — строгий арт-директор и QA-судья DesignAI.
Оцениваешь Design IR, а не пишешь новый дизайн. Проверяй соответствие брифу,
визуальную иерархию, композицию, консистентность токенов, семантику блоков,
реалистичность контента и доступность. Не хвали и не придумывай отсутствующие факты.
Верни только JSON-объект:
{
  "score": 0,
  "verdict": "pass|needs_repair",
  "summary": "краткий вывод",
  "issues": [{"category": "brief|hierarchy|composition|consistency|content|accessibility", "severity": "critical|major|minor", "path": "путь IR или (root)", "problem": "что не так", "instruction": "как исправить"}],
  "repair_instruction": "единая точная инструкция; пустая строка, если repair не нужен"
}
score — целое 0..100. Учитывай только наблюдаемые данные в IR и брифе."""


def _quality_scorecard(ir: dict, brief: str) -> dict:
    """Независимая LLM-оценка. Нормализует недоверенный JSON до публичного контракта."""
    raw = llm.chat(PRODUCT_PROVIDER, [
        {"role": "system", "content": QUALITY_JUDGE_SYSTEM},
        {"role": "user", "content": "## Бриф\n" + (brief.strip() or "(не указан)")
         + "\n\n## Design IR\n" + json.dumps(ir, ensure_ascii=False)},
    ], 0.2, role="quality_judge")
    try:
        parsed = json.loads(llm.extract_json(raw))
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"судья вернул невалидный JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("судья вернул не объект")
    try:
        score = int(parsed.get("score"))
    except (TypeError, ValueError) as e:
        raise ValueError("судья не вернул числовой score") from e
    issues = []
    for item in parsed.get("issues", []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "minor"))
        if severity not in {"critical", "major", "minor"}:
            severity = "minor"
        issues.append({
            "category": str(item.get("category", "consistency")),
            "severity": severity,
            "path": str(item.get("path", "(root)")),
            "problem": str(item.get("problem", "")),
            "instruction": str(item.get("instruction", "")),
        })
    verdict = str(parsed.get("verdict", "needs_repair"))
    return {
        "score": max(0, min(score, 100)),
        "verdict": verdict if verdict in {"pass", "needs_repair"} else "needs_repair",
        "summary": str(parsed.get("summary", "")),
        "issues": issues[:12],
        "repair_instruction": str(parsed.get("repair_instruction", "")),
        "model_route": "GPT Codex / quality_judge",
    }


def _quality_repair(ir: dict, scorecard: dict, brief: str,
                    timeout: float | None = None) -> tuple[dict | None, str | None]:
    """Адресная починка только по замечаниям независимого судьи."""
    instructions = scorecard.get("repair_instruction", "").strip()
    if not instructions:
        instructions = "\n".join(
            str(issue.get("instruction", "")) for issue in scorecard.get("issues", [])
            if issue.get("severity") in {"critical", "major"}
        ).strip()
    if not instructions:
        return None, "судья не дал инструкций для repair"
    user = (
        "Исправь Design IR строго по замечаниям Quality Pass. Сохрани полезный контент, "
        "не добавляй неупомянутые секции и верни только полный валидный JSON.\n\n"
        f"## Бриф\n{brief.strip() or '(не указан)'}\n\n"
        f"## Инструкции\n{instructions}\n\n"
        f"## Входной Design IR\n{json.dumps(ir, ensure_ascii=False)}"
    )
    try:
        raw = llm.chat(PRODUCT_PROVIDER, [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], 0.25, timeout=timeout, role="quality_repair")
        repaired, parse_error = parse_ir_response(raw)
        if repaired is None:
            return None, parse_error
        repaired, _ = generation_quality.resolve_assets(repaired)
        schema_errors = validate_ir(repaired)
        if schema_errors:
            return None, "; ".join(schema_errors[:5])
        return repaired, None
    except Exception as e:
        return None, str(e)


VISUAL_QUALITY_SYSTEM = """Ты — строгий мультимодальный арт-директор DesignAI.
Перед тобой один коллаж: desktop 1440 слева и mobile 390 справа. Оцени только
наблюдаемое качество рендера и соответствие брифу: полноту, композицию, иерархию,
реальные изображения, типографику, плотность, адаптивность, overflow и доступность.
Серые заглушки, текст imagePrompt, пустые карточки, случайные большие пустоты и
сломанный mobile — critical. Верни только JSON:
{"score":0,"verdict":"pass|needs_repair","summary":"...","issues":[{"category":"brief|hierarchy|composition|consistency|content|accessibility","severity":"critical|major|minor","path":"desktop|mobile|(root)","problem":"...","instruction":"..."}],"repair_instruction":"..."}.
Pass допустим только при score >= 78 и отсутствии critical/major дефектов."""


def _visual_quality_scorecard(ir: dict, brief: str, bundle: dict,
                              deterministic_issues: list[dict], timeout: float) -> dict:
    prompt = (
        "## Бриф\n" + (brief.strip() or "(не указан)")
        + "\n\n## Browser DOM metrics\n" + json.dumps(bundle.get("metrics", {}), ensure_ascii=False)
        + "\n\n## Deterministic issues\n" + json.dumps(deterministic_issues, ensure_ascii=False)
        + "\n\nОцени приложенный desktop/mobile коллаж."
    )
    raw = llm.chat_vision(
        PRODUCT_PROVIDER, bundle["montage"], prompt,
        system_prompt=VISUAL_QUALITY_SYSTEM, temperature=0.1,
        timeout=timeout, role="vision_pixel_qa",
    )
    try:
        parsed = json.loads(llm.extract_json(raw))
        score = max(0, min(int(parsed.get("score", 0)), 100))
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(f"visual judge вернул невалидный scorecard: {exc}") from exc
    issues = []
    for item in parsed.get("issues", []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "minor"))
        if severity not in {"critical", "major", "minor"}:
            severity = "minor"
        issues.append({
            "category": str(item.get("category", "composition")),
            "severity": severity,
            "path": str(item.get("path", "(root)")),
            "problem": str(item.get("problem", "")),
            "instruction": str(item.get("instruction", "")),
        })
    important = any(item["severity"] in {"critical", "major"} for item in issues)
    verdict = "pass" if str(parsed.get("verdict")) == "pass" and score >= 78 and not important else "needs_repair"
    return {
        "score": score, "verdict": verdict,
        "summary": str(parsed.get("summary", "")), "issues": issues[:12],
        "repair_instruction": str(parsed.get("repair_instruction", "")),
        "model_route": "GPT Codex / vision_pixel_qa",
    }


def _acceptance_scorecard(issues: list[dict], summary: str) -> dict:
    mapped = [{
        "category": "content" if "card" in item.get("code", "") or "asset" in item.get("code", "") else "composition",
        "severity": item.get("severity", "major"),
        "path": item.get("path", "(root)"),
        "problem": item.get("message", ""),
        "instruction": "Исправь указанный дефект и сохрани остальные части IR без изменений.",
    } for item in issues]
    return {
        "score": 0, "verdict": "needs_repair", "summary": summary,
        "issues": mapped[:12],
        "repair_instruction": "\n".join(f"- {i['path']}: {i['problem']}" for i in mapped[:12]),
    }


def _run_generation_acceptance(candidate: dict, brief: str, index: int,
                               batch_deadline: float) -> tuple[dict | None, dict]:
    """generate -> validate -> rendered judge -> repair -> rendered rejudge."""
    min_score = max(0, min(int(os.environ.get("GENERATION_MIN_SCORE", "78")), 100))
    work = ensure_current_ir(copy.deepcopy(candidate), source="generate")
    work, fixlog = qualitygate.autofix(work)
    work, assets = generation_quality.resolve_assets(work)
    stages = ["schema", "semantic", "assets", "dom", "visual-judge"]
    repair = {"attempted": False, "applied": False, "error": None}

    def deterministic(ir_doc: dict) -> list[dict]:
        found: list[dict] = []
        for message in validate_ir(ir_doc):
            found.append({"code": "schema", "severity": "critical", "path": "(schema)", "message": message})
        found.extend(generation_quality.semantic_validate(ir_doc, brief, require_resolved_assets=True))
        for item in qualitygate.check(ir_doc):
            found.append({"code": item.get("rule", "quality"), "severity": "major",
                          "path": item.get("path", "(root)"), "message": item.get("message", "")})
        return found

    preflight = deterministic(work)
    if preflight:
        repair["attempted"] = True
        remaining = batch_deadline - time.monotonic()
        if remaining > 1:
            repaired, repair_error = _quality_repair(
                work, _acceptance_scorecard(preflight, "IR не прошёл обязательную проверку."),
                brief, timeout=remaining,
            )
            if repaired is not None:
                work, extra_assets = generation_quality.resolve_assets(repaired)
                assets.extend(extra_assets)
                work, extra_fixes = qualitygate.autofix(work)
                fixlog.extend(extra_fixes)
                repair["applied"] = True
            else:
                repair["error"] = repair_error
        preflight = deterministic(work)
        if preflight:
            scorecard = _acceptance_scorecard(preflight, "Вариант отклонён: структура или контент неполны.")
            return None, {"index": index, "score": 0, "verdict": "rejected", "summary": scorecard["summary"],
                          "issues": scorecard["issues"], "fixed": len(fixlog), "assets": assets,
                          "repair": repair, "stages": stages}

    try:
        bundle = visual_quality.capture_quality_bundle(work)
    except Exception as exc:
        issue = {"category": "accessibility", "severity": "critical", "path": "render",
                 "problem": f"Не удалось проверить итоговый DOM: {exc}",
                 "instruction": "Восстанови quality renderer и повтори генерацию."}
        return None, {"index": index, "score": 0, "verdict": "rejected",
                      "summary": "Вариант не возвращён без desktop/mobile проверки.",
                      "issues": [issue], "fixed": len(fixlog), "assets": assets,
                      "repair": repair, "stages": stages}

    dom_issues = generation_quality.dom_contract_audit(bundle.get("metrics", {}))
    remaining = batch_deadline - time.monotonic()
    if remaining <= 1:
        return None, {"index": index, "score": 0, "verdict": "rejected", "summary": "Истёк deadline до visual judge.",
                      "issues": _acceptance_scorecard(dom_issues, "DOM не прошёл проверку.")["issues"],
                      "fixed": len(fixlog), "assets": assets, "repair": repair, "stages": stages}
    try:
        initial = _visual_quality_scorecard(work, brief, bundle, dom_issues, remaining)
    except Exception as exc:
        return None, {"index": index, "score": 0, "verdict": "rejected", "summary": f"Visual judge недоступен: {exc}",
                      "issues": [], "fixed": len(fixlog), "assets": assets, "repair": repair, "stages": stages}

    blocking_dom = any(item.get("severity") in {"critical", "major"} for item in dom_issues)
    passed = initial["score"] >= min_score and initial["verdict"] == "pass" and not blocking_dom
    final = initial
    if not passed:
        repair["attempted"] = True
        combined = copy.deepcopy(initial)
        combined["issues"] = list(initial.get("issues", [])) + _acceptance_scorecard(dom_issues, "DOM issues")["issues"]
        if dom_issues:
            combined["repair_instruction"] = (combined.get("repair_instruction", "") + "\n" +
                "\n".join(f"- {item['path']}: {item['message']}" for item in dom_issues)).strip()
        remaining = batch_deadline - time.monotonic()
        repaired, repair_error = _quality_repair(work, combined, brief, timeout=max(1.0, remaining)) if remaining > 1 else (None, "deadline")
        if repaired is not None:
            repaired, extra_assets = generation_quality.resolve_assets(repaired)
            assets.extend(extra_assets)
            repaired, extra_fixes = qualitygate.autofix(repaired)
            fixlog.extend(extra_fixes)
            remaining_issues = deterministic(repaired)
            if not remaining_issues:
                try:
                    repaired_bundle = visual_quality.capture_quality_bundle(repaired)
                    repaired_dom = generation_quality.dom_contract_audit(repaired_bundle.get("metrics", {}))
                    remaining = batch_deadline - time.monotonic()
                    if remaining > 1:
                        final = _visual_quality_scorecard(repaired, brief, repaired_bundle, repaired_dom, remaining)
                        work, bundle, dom_issues = repaired, repaired_bundle, repaired_dom
                        repair["applied"] = True
                except Exception as exc:
                    repair_error = str(exc)
            else:
                repair_error = "; ".join(item["message"] for item in remaining_issues[:4])
        repair["error"] = repair_error

    blocking_dom = any(item.get("severity") in {"critical", "major"} for item in dom_issues)
    passed = final["score"] >= min_score and final["verdict"] == "pass" and not blocking_dom
    issues = list(final.get("issues", [])) + _acceptance_scorecard(dom_issues, "DOM issues")["issues"]
    qa = {"index": index, "score": final["score"], "verdict": "pass" if passed else "rejected",
          "summary": final.get("summary", ""), "issues": issues[:16], "fixed": len(fixlog),
          "violations": [item.get("category", "quality") for item in issues[:16]],
          "assets": assets, "repair": repair, "stages": stages,
          "metrics": bundle.get("metrics", {})}
    return (ensure_current_ir(work, source="generate"), qa) if passed else (None, qa)


@app.post("/api/quality-pass")
def quality_pass(req: QualityPassReq):
    """Премиальный контур: детерминированные правила → независимый judge → repair → rejudge.

    API всегда возвращает исходный валидный IR, если repair не удался: результат
    контролируем и не подменяем граф битым ответом модели.
    """
    schema_errors = validate_ir(req.ir)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    deterministic_before = qualitygate.check(req.ir)
    try:
        initial = _quality_scorecard(req.ir, req.brief)
    except Exception as e:
        return err(502, f"Quality Pass judge недоступен: {e}")
    min_score = max(0, min(int(req.min_score), 100))
    important = any(i["severity"] in {"critical", "major"} for i in initial["issues"])
    needs_repair = bool(deterministic_before) or important or initial["score"] < min_score
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None}
    final = initial
    if req.repair and needs_repair:
        repair["attempted"] = True
        repaired, repair_error = _quality_repair(req.ir, initial, req.brief)
        if repaired is None:
            repair["error"] = repair_error
        else:
            output_ir = repaired
            repair["applied"] = True
            if req.rejudge:
                try:
                    final = _quality_scorecard(output_ir, req.brief)
                except Exception as e:
                    repair["error"] = f"rejudge недоступен: {e}"
    deterministic_after = qualitygate.check(output_ir)
    passed = (final["score"] >= min_score and final["verdict"] == "pass"
              and not deterministic_after)
    return {
        "ir": output_ir,
        "passed": passed,
        "min_score": min_score,
        "scorecard": final,
        "initial_scorecard": initial,
        "deterministic": {"before": deterministic_before, "after": deterministic_after},
        "repair": repair,
    }


@app.post("/api/constraints/check")
def constraints_check(req: ConstraintsCheckReq):
    """Проверка декларативных ограничений (локи полей по путям + диапазоны)."""
    try:
        violations = qualitygate.check_constraints(req.ir, req.constraints)
    except ValueError as e:
        return err(422, str(e))
    return {"ok": not violations, "violations": violations}


@app.post("/api/scrape")
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


@app.post("/api/reproduce")
def reproduce(req: ReproduceReq):
    """Pixel-perfect reproduction: скриншот → VLM-структура → Python-измерения → HTML → diff.

    Работает с любым провайдером для VLM-анализа. Все измерения — из пикселей.
    Повторный запрос того же скриншота/сайта — из кэша, без траты токенов.
    """
    url = req.url.strip()
    image = req.image
    url_key = None
    if url:
        try:
            validate_public_url(url)
        except ValueError as e:
            return err(422, str(e))
        url_key = cache_store.key_url(url)
        hit = cache_store.get("reproduce_url", url_key)
        if hit:
            return {**hit, "cached": True}
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
    hit = cache_store.get("reproduce_img", img_key)
    if hit:
        return {**hit, "cached": True}

    provider = normalize_provider(req.provider)

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
    cache_store.put("reproduce_img", img_key, payload)
    if url_key:
        cache_store.put("reproduce_url", url_key, payload)
    return {**payload, "cached": False}


@app.get("/api/cache/stats")
def cache_stats():
    """Наблюдаемость кэша: сколько LLM-вызовов сэкономлено повторами."""
    return cache_store.stats()


@app.post("/api/project/save")
def project_save(req: ProjectSaveReq):
    return project_store.save_project(req.project, req.user_id, req.project_id)


@app.post("/api/project/load")
def project_load(req: ProjectLoadReq):
    saved = project_store.load_project(req.user_id, req.project_id)
    if not saved:
        return {"project": None, "updated_at": None}
    return {"project": saved["payload"], "updated_at": saved["updated_at"]}


EDITOR_ASSIST_ACTIONS = {
    "adapt", "overflow", "content-fit", "align", "accessibility",
    "rename-layers", "style", "custom",
}
EDITOR_ASSIST_VIEWPORTS = {"current", "desktop", "tablet", "mobile", "all"}
EDITOR_ASSIST_FORBIDDEN_FIELDS = {"id", "type", "sourceKey"}
EDITOR_ASSIST_STRUCTURAL_COLLECTIONS = {"tree", "children"}


def _editor_pointer_parts(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("patch path должен быть JSON Pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/") if part != ""]


def _editor_pointer_get(doc: dict, path: str):
    current = doc
    for part in _editor_pointer_parts(path):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return copy.deepcopy(current)


def _editor_pointer_apply(doc: dict, operation: dict):
    parts = _editor_pointer_parts(operation.get("path", ""))
    if not parts:
        raise ValueError("изменение корневого IR запрещено")
    parent = doc
    for part in parts[:-1]:
        if isinstance(parent, list):
            parent = parent[int(part)]
        else:
            parent = parent[part]
    last = parts[-1]
    op = operation.get("op")
    if isinstance(parent, list):
        if op == "add" and last == "-":
            parent.append(copy.deepcopy(operation.get("after")))
        elif op == "add":
            parent.insert(int(last), copy.deepcopy(operation.get("after")))
        elif op == "replace":
            parent[int(last)] = copy.deepcopy(operation.get("after"))
        elif op == "remove":
            parent.pop(int(last))
        else:
            raise ValueError(f"неподдерживаемая операция: {op}")
    else:
        if op in {"add", "replace"}:
            parent[last] = copy.deepcopy(operation.get("after"))
        elif op == "remove":
            parent.pop(last, None)
        else:
            raise ValueError(f"неподдерживаемая операция: {op}")


def _editor_structure_signature(doc: dict) -> list[tuple]:
    result = []

    def visit(node: dict, path: str):
        if not isinstance(node, dict):
            return
        result.append((path, node.get("id"), node.get("type"), node.get("sourceKey")))
        for index, child in enumerate(node.get("children") or []):
            visit(child, f"{path}/children/{index}")

    for index, section in enumerate(doc.get("tree") or []):
        visit(section, f"/tree/{index}")
    return result


def _editor_source_paths(doc: dict) -> dict[str, str]:
    """Map stable editor identities to their JSON Pointer paths."""
    result: dict[str, str] = {}

    def visit(node: dict, path: str):
        if not isinstance(node, dict):
            return
        source_key = node.get("sourceKey")
        if isinstance(source_key, str) and source_key:
            result[source_key] = path
        for index, child in enumerate(node.get("children") or []):
            visit(child, f"{path}/children/{index}")

    for index, section in enumerate(doc.get("tree") or []):
        visit(section, f"/tree/{index}")
    return result


def _editor_ensure_source_keys(doc: dict) -> dict:
    """Assign deterministic editor identities to legacy nodes that lack them."""
    seen: set[str] = set()

    def visit(node: dict, path: str):
        if not isinstance(node, dict):
            return
        source_key = str(node.get("sourceKey") or "").strip()
        if not source_key:
            source_key = f"editor:{path}"
        base = source_key
        suffix = 1
        while source_key in seen:
            source_key = f"{base}#{suffix:03d}"
            suffix += 1
        node["sourceKey"] = source_key
        seen.add(source_key)
        for index, child in enumerate(node.get("children") or []):
            visit(child, f"{path}/children/{index}")

    for index, section in enumerate(doc.get("tree") or []):
        visit(section, f"/tree/{index}")
    return doc


def _editor_path_exists(doc: dict, path: str) -> bool:
    try:
        _editor_pointer_get(doc, path)
        return True
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def _editor_commands_to_ops(base: dict, commands: list, scope: EditorAssistScope) -> list[dict]:
    """Resolve semantic, sourceKey-based AI commands into guarded IR operations."""
    if not isinstance(commands, list) or len(commands) > 60:
        raise ValueError("AI должен вернуть от 0 до 60 редакторских команд")
    source_paths = _editor_source_paths(base)
    allowed_groups = {"frame", "style", "styleBindings", "props"}
    content_fields = {"text", "title", "placeholder", "value", "label", "name", "alt", "ariaLabel"}
    ops: list[dict] = []
    shadow = copy.deepcopy(base)

    def ensure_object(path: str, reason: str) -> None:
        parts = _editor_pointer_parts(path)
        for end in range(1, len(parts) + 1):
            current_path = "/" + "/".join(
                part.replace("~", "~0").replace("/", "~1") for part in parts[:end]
            )
            if _editor_path_exists(shadow, current_path):
                continue
            operation = {"op": "add", "path": current_path, "after": {}, "reason": reason}
            _editor_pointer_apply(shadow, operation)
            ops.append(operation)
    for raw in commands:
        if not isinstance(raw, dict) or raw.get("command") != "update":
            raise ValueError("поддерживается только редакторская команда update")
        target = str(raw.get("targetSourceKey") or "")
        target_path = source_paths.get(target)
        if not target_path:
            raise ValueError(f"не найден элемент редактора: {target or 'без sourceKey'}")
        if scope.sourceKeys and target not in scope.sourceKeys:
            allowed_paths = [source_paths[key] for key in scope.sourceKeys if key in source_paths]
            if not any(target_path == prefix or target_path.startswith(prefix + "/") for prefix in allowed_paths):
                raise ValueError("AI попытался изменить элемент вне текущего выделения")
        viewport = str(raw.get("viewport") or scope.viewport or "current").lower()
        if viewport == "current":
            viewport = scope.viewport if scope.viewport in {"desktop", "tablet", "mobile"} else "shared"
        if viewport in {"all", "desktop"}:
            viewport = "shared"
        if viewport not in {"shared", "tablet", "mobile"}:
            raise ValueError(f"неизвестный viewport команды: {viewport}")
        changes = raw.get("changes")
        if not isinstance(changes, dict) or not changes:
            raise ValueError("команда update должна содержать changes")
        reason = str(raw.get("reason") or "").strip()
        for group, values in changes.items():
            if group in allowed_groups:
                if not isinstance(values, dict):
                    raise ValueError(f"{group} должен быть объектом")
                group_path = f"{target_path}/{group}" if viewport == "shared" else f"{target_path}/responsive/{viewport}/{group}"
                ensure_object(group_path, reason)
                for key, value in values.items():
                    key_part = str(key).replace("~", "~0").replace("/", "~1")
                    path = f"{group_path}/{key_part}"
                    operation = {
                        "op": "replace" if _editor_path_exists(shadow, path) else "add",
                        "path": path,
                        "after": copy.deepcopy(value),
                        "reason": reason,
                    }
                    _editor_pointer_apply(shadow, operation)
                    ops.append(operation)
            elif group in content_fields and viewport == "shared":
                path = f"{target_path}/{group}"
                operation = {
                    "op": "replace" if _editor_path_exists(shadow, path) else "add",
                    "path": path,
                    "after": copy.deepcopy(values),
                    "reason": reason,
                }
                _editor_pointer_apply(shadow, operation)
                ops.append(operation)
            else:
                raise ValueError(f"недопустимая группа изменения: {group}")
    return ops


def _editor_validate_scope(base: dict, ops: list[dict], source_keys: list[str]) -> None:
    if not source_keys:
        return
    source_paths = _editor_source_paths(base)
    allowed_paths = [source_paths[key] for key in source_keys if key in source_paths]
    if not allowed_paths:
        raise ValueError("выделенные элементы больше не найдены в документе")
    for operation in ops:
        path = str(operation.get("path") or "")
        if not any(path == prefix or path.startswith(prefix + "/") for prefix in allowed_paths):
            raise ValueError("AI попытался изменить элемент вне текущего выделения")


def _editor_diff(before, after, path: str = "") -> list[dict]:
    if isinstance(before, dict) and isinstance(after, dict):
        ops: list[dict] = []
        keys = list(dict.fromkeys([*before.keys(), *after.keys()]))
        for key in keys:
            child_path = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in after:
                ops.append({"op": "remove", "path": child_path, "before": copy.deepcopy(before[key])})
            elif key not in before:
                ops.append({"op": "add", "path": child_path, "after": copy.deepcopy(after[key])})
            else:
                ops.extend(_editor_diff(before[key], after[key], child_path))
        return ops
    if isinstance(before, list) and isinstance(after, list):
        if len(before) == len(after):
            ops: list[dict] = []
            for index, (before_item, after_item) in enumerate(zip(before, after)):
                ops.extend(_editor_diff(before_item, after_item, f"{path}/{index}"))
            return ops
        if before != after:
            return [{"op": "replace", "path": path or "/tree", "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]
        return []
    if isinstance(before, list) or isinstance(after, list):
        return [{"op": "replace", "path": path or "/tree", "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]
    if before != after:
        return [{"op": "replace", "path": path or "/frame", "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]
    return []


def _editor_validate_and_apply(base: dict, raw_ops: list, constraints: EditorAssistConstraints) -> tuple[dict, list[dict]]:
    if not isinstance(raw_ops, list) or len(raw_ops) > 100:
        raise ValueError("AI patch должен содержать от 0 до 100 операций")
    candidate = copy.deepcopy(base)
    normalized: list[dict] = []
    for raw in raw_ops:
        if not isinstance(raw, dict):
            raise ValueError("операция AI patch должна быть объектом")
        op = str(raw.get("op", ""))
        path = str(raw.get("path", ""))
        if op not in {"add", "remove", "replace"}:
            raise ValueError(f"неподдерживаемая операция: {op}")
        parts = _editor_pointer_parts(path)
        if not parts or parts[0] not in {"tree", "frame", "responsive", "tokens", "styleBindings"}:
            raise ValueError(f"недопустимый путь: {path}")
        changes_identity = parts[-1] in EDITOR_ASSIST_FORBIDDEN_FIELDS
        changes_collection = (
            parts[-1] in EDITOR_ASSIST_STRUCTURAL_COLLECTIONS
            or (len(parts) > 1 and parts[-2] in EDITOR_ASSIST_STRUCTURAL_COLLECTIONS)
        )
        if not constraints.allowStructure and (changes_identity or changes_collection):
            raise ValueError(f"структурное изменение запрещено: {path}")
        if any(part in {"frame", "responsive"} for part in parts) and not constraints.allowFrame:
            raise ValueError(f"изменение frame запрещено: {path}")
        if any(part in {"style", "styleBindings", "tokens"} for part in parts) and not constraints.allowStyle:
            raise ValueError(f"изменение style запрещено: {path}")
        if any(part in {"text", "title", "placeholder", "value", "label", "name", "props"} for part in parts) and not constraints.allowContent:
            raise ValueError(f"изменение content запрещено: {path}")
        before = raw.get("before")
        if before is None and op != "add":
            try:
                before = _editor_pointer_get(base, path)
            except (KeyError, IndexError, TypeError, ValueError):
                before = None
        operation = {
            "op": op,
            "path": path,
            "before": copy.deepcopy(before),
            "after": copy.deepcopy(raw.get("after")),
            "reason": str(raw.get("reason", "")).strip(),
        }
        _editor_pointer_apply(candidate, operation)
        normalized.append(operation)
    if not constraints.allowStructure and _editor_structure_signature(base) != _editor_structure_signature(candidate):
        raise ValueError("AI patch изменил структуру дерева")
    schema_errors = validate_ir(candidate)
    if schema_errors:
        raise ValueError("AI patch создал невалидный IR: " + "; ".join(schema_errors[:5]))
    return candidate, normalized


def _editor_changed_viewports(ops: list[dict]) -> list[str]:
    found = []
    for viewport in ("desktop", "tablet", "mobile"):
        if any(
            f"/responsive/{viewport}" in str(op.get("path", ""))
            or f"/responsive/viewports/{viewport}" in str(op.get("path", ""))
            or (
                str(op.get("path", "")).endswith("/responsive")
                and isinstance(op.get("after"), dict)
                and viewport in op["after"]
            )
            or (
                str(op.get("path", "")).endswith("/responsive/viewports")
                and isinstance(op.get("after"), dict)
                and viewport in op["after"]
            )
            for op in ops
        ):
            found.append(viewport)
    return found


def _editor_adapt_preview(base: dict, scope: EditorAssistScope) -> dict:
    """Create conservative, selection-aware responsive overrides."""
    candidate = ir.ensure_fluid_layout(base)
    if not scope.sourceKeys:
        return candidate
    paths = _editor_source_paths(candidate)
    for source_key in scope.sourceKeys:
        path = paths.get(source_key)
        if not path:
            continue
        try:
            node = _editor_pointer_get(candidate, path)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
        responsive = node.setdefault("responsive", {})
        if not isinstance(responsive, dict):
            responsive = {}
            node["responsive"] = responsive

        mobile = responsive.setdefault("mobile", {})
        if isinstance(mobile, dict):
            mobile_frame = mobile.setdefault("frame", {})
            if isinstance(mobile_frame, dict):
                mobile_frame.setdefault("width", "fill")
                mobile_frame.setdefault("minWidth", 0)
                if frame.get("layout") == "auto" and frame.get("direction") == "row":
                    mobile_frame.setdefault("direction", "column")
                    mobile_frame.setdefault("wrap", False)
                    if isinstance(frame.get("gap"), (int, float)):
                        mobile_frame.setdefault("gap", min(float(frame["gap"]), 16))
                    mobile_frame.setdefault("align", "stretch")

        tablet = responsive.setdefault("tablet", {})
        if isinstance(tablet, dict):
            tablet_frame = tablet.setdefault("frame", {})
            if isinstance(tablet_frame, dict):
                if isinstance(frame.get("width"), (int, float)) and frame["width"] > 720:
                    tablet_frame.setdefault("width", "fill")
                    tablet_frame.setdefault("minWidth", 0)
                if frame.get("layout") == "auto" and frame.get("direction") == "row":
                    tablet_frame.setdefault("wrap", True)
                    tablet_frame.setdefault("align", "stretch")

        _editor_pointer_apply(candidate, {"op": "replace", "path": path, "after": node})
    return candidate


def _editor_assist_llm(base: dict, req: EditorAssistReq) -> tuple[dict, list[dict], str]:
    system = (
        "You are a visual editor agent. Return JSON only with keys summary and commands. "
        "Each command must be {command:'update', targetSourceKey, viewport, changes, reason}. "
        "viewport is shared, tablet, or mobile. changes may contain frame, style, "
        "styleBindings, props, text, title, placeholder, value, label, name, alt, or ariaLabel. "
        "Use only sourceKeys present in the IR and stay inside scope.sourceKeys when supplied. "
        "Never change hierarchy, ids, types, sourceKeys, children, or array order. "
        "Prefer auto-layout, fill sizing, consistent spacing, and existing design tokens; "
        "preserve the current visual direction and make the smallest coherent change."
    )
    user = json.dumps({
        "action": req.action,
        "prompt": req.prompt.strip(),
        "scope": req.scope.model_dump() if hasattr(req.scope, "model_dump") else req.scope.dict(),
        "constraints": req.constraints.model_dump() if hasattr(req.constraints, "model_dump") else req.constraints.dict(),
        "ir": base,
    }, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: ValueError | None = None
    for attempt in range(2):
        raw = llm.chat(PRODUCT_PROVIDER, messages, 0.2, role="edit", priority="high")
        try:
            parsed = json.loads(llm.extract_json(raw))
            if not isinstance(parsed, dict):
                raise ValueError("AI вернул не объект")
            if "commands" in parsed:
                ops = _editor_commands_to_ops(base, parsed.get("commands", []), req.scope)
            else:
                # Backward compatibility for providers/tests still returning guarded ops.
                ops = parsed.get("ops", [])
            _editor_validate_scope(base, ops, req.scope.sourceKeys)
            candidate, ops = _editor_validate_and_apply(base, ops, req.constraints)
            return candidate, ops, str(parsed.get("summary") or "Изменения готовы к применению")
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = ValueError(f"AI вернул невалидное изменение: {exc}")
            if attempt == 0:
                messages.extend([
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"Команда отклонена редактором: {exc}. Верни исправленный JSON по схеме."},
                ])
                continue
    raise last_error or ValueError("AI не смог подготовить безопасное изменение")


@app.post("/api/editor/assist")
def editor_assist(req: EditorAssistReq):
    """Return a validated visual-edit preview; never mutates the submitted IR."""
    if not FEATURE_FLAGS.is_enabled("editorAiAssist"):
        return err(404, "AI assist редактора отключён feature flag.")
    action = req.action.strip().lower()
    if action not in EDITOR_ASSIST_ACTIONS:
        return err(422, "Неизвестное AI-действие редактора.")
    if req.scope.viewport not in EDITOR_ASSIST_VIEWPORTS:
        return err(422, "Неизвестный viewport.")
    schema_errors = validate_ir(req.ir)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    if not req.prompt.strip():
        return err(422, "Опишите, что нужно изменить.")
    base = _editor_ensure_source_keys(ensure_current_ir(copy.deepcopy(req.ir), source="editor-assist"))
    try:
        if action == "adapt":
            candidate = _editor_adapt_preview(base, req.scope)
            ops = _editor_diff(base, candidate)[:100]
            summary = "Адаптивные настройки выделения подготовлены" if req.scope.sourceKeys else "Адаптивные fallback-настройки подготовлены"
        elif action == "overflow":
            candidate, journal = qualitygate.autofix(base)
            ops = _editor_diff(base, candidate)[:100]
            summary = journal[0] if journal else "Переполнения не найдены"
        else:
            candidate, ops, summary = _editor_assist_llm(base, req)
        if not ops:
            summary = summary or "Изменений не требуется"
        remaining_overflow = qualitygate.check(candidate)
        warnings = [
            {"code": str(item.get("rule", "quality")), "message": str(item.get("message", item)), "path": str(item.get("path", ""))}
            for item in remaining_overflow[:12]
            if isinstance(item, dict)
        ]
        return {
            "summary": summary,
            "ops": ops,
            "previewIr": candidate,
            "changedViewports": _editor_changed_viewports(ops),
            "warnings": warnings,
            "validation": {"schema": True, "overflow": remaining_overflow, "constraints": []},
        }
    except llm.AIRequestError as exc:
        status = 429 if exc.reason in {"очередь", "лимит провайдера"} else 504
        return err(status, exc.reason)
    except ValueError as exc:
        return err(422, str(exc))
    except Exception as exc:
        return err(502, f"AI assist недоступен: {exc}")


@app.get("/api/project/taste")
def project_taste():
    return project_store.load_taste_profile()


@app.get("/api/config")
def app_config():
    """Runtime configuration and feature flags for the frontend."""
    return {
        "schemaVersion": ir.CURRENT_SCHEMA_VERSION,
        "flags": FEATURE_FLAGS.all(),
        "models": {
            "generator": llm.routing_models("generator")[0],
            "motionDirector": llm.routing_models("motion_director")[0],
            "video": video_client.public_models(),
        },
        "provider": llm.public_config(),
        "videoProvider": video_client.public_config(),
    }


@app.post("/api/style-dna/extract")
def style_dna_extract(req: StyleDnaReq):
    """Extract primitives + semantic Style DNA from an IR document."""
    schema_errors = validate_ir(req.ir)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    return {"tokens": ir.build_style_dna(req.ir)}


@app.post("/api/style-dna/apply")
def style_dna_apply(req: StyleDnaApplyReq):
    """Apply a Style DNA token set to an IR document, updating bound styles.

    First re-binds element styles to the new token set so semantic changes
    propagate even to documents that did not yet carry styleBindings.
    """
    schema_errors = validate_ir(req.ir)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    bound = ir.bind_element_styles(req.ir, req.tokens)
    updated = ir.apply_tokens(bound, req.tokens)
    return {"ir": updated}


@app.post("/api/style/normalize/preview")
def style_normalize_preview(req: StyleNormalizeReq):
    """Build an opt-in normalization patch without mutating the input IR."""
    current = ensure_current_ir(req.ir)
    schema_errors = validate_ir(current)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    result = ir.preview_normalization(current, tolerance=req.tolerance)
    normalized_errors = validate_ir(result["normalizedIr"])
    if normalized_errors:
        return err(500, "Normalize создал невалидный IR: " + "; ".join(normalized_errors[:5]))
    return result


@app.post("/api/export/tailwind")
def export_tailwind(req: TailwindProjectionReq):
    """Return a deterministic Tailwind projection derived from Design IR."""
    if not FEATURE_FLAGS.is_enabled("tailwindProjection"):
        return err(404, "Tailwind projection отключён feature flag.")
    current = ensure_current_ir(req.ir)
    schema_errors = validate_ir(current)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    try:
        return ir.project_tailwind(current, mode=req.mode)
    except ValueError as exc:
        return err(422, str(exc))


@app.post("/api/interaction/build")
def interaction_build(req: InteractionBuildReq):
    """Build sanitized Interaction IR from event payloads and scene snapshots."""
    if not FEATURE_FLAGS.is_enabled("interactionRecorder"):
        return err(404, "Interaction Recorder отключён feature flag.")
    base_ir = ensure_current_ir(req.base_ir)
    schema_errors = validate_ir(base_ir)
    if schema_errors:
        return err(422, "Base IR не проходит schema: " + "; ".join(schema_errors[:5]))
    try:
        interaction = ir.build_interaction(base_ir, req.source, req.scenes, req.events, req.variables)
    except ValueError as exc:
        return err(422, str(exc))
    return {"interaction": interaction}


@app.post("/api/interaction/validate")
def interaction_validate(req: InteractionValidateReq):
    errors = ir.validate_interaction(req.interaction)
    return {"valid": not errors, "errors": errors}


@app.post("/api/interaction/replay")
def interaction_replay(req: InteractionReplayReq):
    base_ir = ensure_current_ir(req.base_ir)
    schema_errors = validate_ir(base_ir)
    if schema_errors:
        return err(422, "Base IR не проходит schema: " + "; ".join(schema_errors[:5]))
    try:
        scene_ir = ir.replay_interaction(base_ir, req.interaction, req.scene_id)
    except ValueError as exc:
        return err(422, str(exc))
    replay_errors = validate_ir(scene_ir)
    if replay_errors:
        return err(422, "Scene patch создаёт невалидный IR: " + "; ".join(replay_errors[:5]))
    return {"ir": ensure_current_ir(scene_ir)}


@app.post("/api/interaction/capture")
def interaction_capture(req: InteractionCaptureReq):
    """Replay a transient, same-origin action script against an owned site."""
    if not FEATURE_FLAGS.is_enabled("interactionRecorder"):
        return err(404, "Interaction Recorder отключён feature flag.")
    if not req.mine:
        return err(403, "Подтвердите, что сайт принадлежит вам или у вас есть разрешение на запись.")
    base_ir = ensure_current_ir(req.base_ir)
    schema_errors = validate_ir(base_ir)
    if schema_errors:
        return err(422, "Base IR не проходит schema: " + "; ".join(schema_errors[:5]))
    try:
        interaction = capture_live_flow(base_ir, req.url, req.actions, req.viewport)
    except ValueError as exc:
        return err(422, str(exc))
    except Exception as exc:
        return err(502, f"Hybrid capture failed: {exc}")
    return {"interaction": interaction}


@app.post("/api/motion/build")
def motion_build(req: MotionBuildReq):
    """Build Motion IR and materialize editable preview scenes."""
    if not FEATURE_FLAGS.is_enabled("motionEditor"):
        return err(404, "Motion Editor отключён feature flag.")
    base_ir = ensure_current_ir(req.base_ir)
    base_errors = validate_ir(base_ir)
    if base_errors:
        return err(422, "Base IR не проходит schema: " + "; ".join(base_errors[:5]))
    try:
        if req.interaction:
            interaction_errors = ir.validate_interaction(req.interaction)
            if interaction_errors:
                return err(422, "Interaction IR не проходит schema: " + "; ".join(interaction_errors[:5]))
            motion = ir.build_motion(req.interaction, req.composition, req.scene_settings, req.render_settings)
            scene_irs = []
            for scene in motion["scenes"]:
                scene_ir = ir.replay_interaction(base_ir, req.interaction, scene["interactionSceneId"])
                replay_errors = validate_ir(scene_ir)
                if replay_errors:
                    raise ValueError("Motion scene создаёт невалидный IR: " + "; ".join(replay_errors[:5]))
                scene_irs.append({"sceneId": scene["id"], "ir": ensure_current_ir(scene_ir)})
        else:
            plan = None
            prompt = (req.prompt or "").strip()
            if prompt:
                plan = ir.direct_comp_plan(base_ir, prompt, req.composition)
            motion = ir.build_motion_from_design(base_ir, req.composition, req.render_settings, plan)
            scene_irs = [{"sceneId": motion["scenes"][0]["id"], "ir": base_ir}]
    except ValueError as exc:
        return err(422, str(exc))
    return {"motion": motion, "sceneIrs": scene_irs}


@app.post("/api/motion/validate")
def motion_validate(req: MotionValidateReq):
    errors = ir.validate_motion(req.motion, req.interaction)
    return {"valid": not errors, "errors": errors}


def _materialize_motion_scenes(base_ir: dict, interaction: dict, motion: dict) -> list[dict]:
    scene_irs = []
    for scene in motion["scenes"]:
        scene_ir = ir.replay_interaction(base_ir, interaction, scene["interactionSceneId"])
        replay_errors = validate_ir(scene_ir)
        if replay_errors:
            raise ValueError("Motion scene produced invalid IR: " + "; ".join(replay_errors[:5]))
        scene_irs.append({"sceneId": scene["id"], "ir": ensure_current_ir(scene_ir)})
    return scene_irs


def _run_motion_render(render_id: str, motion: dict, scene_irs: list[dict], output: Path) -> None:
    def progress(done: int, total: int) -> None:
        with RENDER_JOBS_LOCK:
            job = RENDER_JOBS.get(render_id)
            if job:
                job.update(status="rendering", progress=round(done * 100 / total), framesDone=done)

    try:
        with RENDER_JOBS_LOCK:
            RENDER_JOBS[render_id].update(status="rendering", progress=0)
        result = render_video(motion, scene_irs, output, progress)
        with RENDER_JOBS_LOCK:
            RENDER_JOBS[render_id].update(
                status="complete",
                progress=100,
                result={key: value for key, value in result.items() if key != "path"},
                downloadUrl=f"/api/motion/render/{render_id}/download",
            )
    except Exception as exc:
        with RENDER_JOBS_LOCK:
            job = RENDER_JOBS.get(render_id)
            if job:
                job.update(status="error", error=str(exc)[:500])


@app.post("/api/motion/render")
def motion_render(req: MotionRenderReq):
    """Queue a deterministic local video render from validated Motion IR."""
    if not FEATURE_FLAGS.is_enabled("videoRender"):
        return err(404, "Video render is disabled by feature flag.")
    base_ir = ensure_current_ir(req.base_ir)
    base_errors = validate_ir(base_ir)
    motion_errors = ir.validate_motion(req.motion, req.interaction)
    if base_errors:
        return err(422, "Base IR does not pass schema: " + "; ".join(base_errors[:5]))
    if motion_errors:
        return err(422, "Motion IR does not pass schema: " + "; ".join(motion_errors[:5]))
    base_hash = base_ir.get("contentHash") or ir.content_hash(base_ir)
    if req.motion["source"]["baseDesignIrHash"] != base_hash:
        return err(409, "Motion IR does not belong to the supplied Design IR.")
    try:
        if req.motion.get("layers"):
            scene_irs = [{"sceneId": req.motion["scenes"][0]["id"], "ir": base_ir}]
        else:
            if not req.interaction:
                return err(422, "Для старого slideshow-ролика нужен Interaction IR.")
            interaction_errors = ir.validate_interaction(req.interaction)
            if interaction_errors:
                return err(422, "Interaction IR does not pass schema: " + "; ".join(interaction_errors[:5]))
            if req.motion["source"]["interactionHash"] != ir.content_hash(req.interaction):
                return err(409, "Motion IR does not belong to the supplied Interaction IR.")
            scene_irs = _materialize_motion_scenes(base_ir, req.interaction, req.motion)
        total_frames, output_format = validate_render_input(req.motion, scene_irs)
    except ValueError as exc:
        return err(422, str(exc))

    render_id = uuid.uuid4().hex
    output = RENDER_DIR / f"{render_id}.{output_format}"
    with RENDER_JOBS_LOCK:
        RENDER_JOBS[render_id] = {
            "id": render_id,
            "status": "queued",
            "progress": 0,
            "framesDone": 0,
            "framesTotal": total_frames,
            "format": output_format,
            "filename": f"designai-motion-{render_id[:8]}.{output_format}",
            "output": output,
        }
    RENDER_EXECUTOR.submit(_run_motion_render, render_id, copy.deepcopy(req.motion), scene_irs, output)
    return {key: value for key, value in RENDER_JOBS[render_id].items() if key != "output"}


@app.get("/api/motion/render/{render_id}")
def motion_render_status(render_id: str):
    with RENDER_JOBS_LOCK:
        job = RENDER_JOBS.get(render_id)
        if not job:
            return err(404, "Render job not found.")
        return {key: value for key, value in job.items() if key != "output"}


@app.get("/api/motion/render/{render_id}/download")
def motion_render_download(render_id: str):
    with RENDER_JOBS_LOCK:
        job = RENDER_JOBS.get(render_id)
        if not job:
            return err(404, "Render job not found.")
        if job["status"] != "complete":
            return err(409, "Render is not complete.")
        output = Path(job["output"])
        filename = job["filename"]
    if not output.is_file() or output.parent.resolve() != RENDER_DIR.resolve():
        return err(404, "Rendered artifact not found.")
    media_type = "video/mp4" if output.suffix == ".mp4" else "video/webm"
    return FileResponse(output, media_type=media_type, filename=filename)


@app.post("/api/ai-video/generate")
def ai_video_generate(req: AiVideoGenerateReq):
    """Submit an explicitly confirmed generative B-roll job to Seedance."""
    if not FEATURE_FLAGS.is_enabled("generativeVideo"):
        return err(404, "Generative video is disabled by feature flag.")
    if not req.confirmed:
        return err(409, "Confirm the paid Seedance video generation before submitting.")
    if len(req.references) > 4:
        return err(422, "At most four video reference images are allowed.")
    safe_references = []
    try:
        for reference in req.references:
            safe = validate_public_url(reference)
            if not safe.startswith("https://"):
                raise ValueError("Video reference images must use HTTPS.")
            safe_references.append(safe)
        return video_client.submit(
            req.prompt,
            tier=req.tier,
            duration=req.duration,
            aspect_ratio=req.aspect_ratio,
            resolution=req.resolution,
            generate_audio=req.generate_audio,
            references=safe_references,
            seed=req.seed,
        )
    except ValueError as exc:
        return err(422, str(exc))
    except RuntimeError as exc:
        return err(502, str(exc))


@app.get("/api/ai-video/{job_id}")
def ai_video_status(job_id: str):
    """Poll one Seedance video job without accepting arbitrary polling URLs."""
    if not FEATURE_FLAGS.is_enabled("generativeVideo"):
        return err(404, "Generative video is disabled by feature flag.")
    try:
        return video_client.status(job_id)
    except ValueError as exc:
        return err(422, str(exc))
    except RuntimeError as exc:
        return err(502, str(exc))


@app.get("/nodes")
def nodes_page():
    # Legacy-граф снят: старый адрес ведёт в единственную актуальную SPA.
    return RedirectResponse(url="/flow", status_code=307)


@app.get("/")
def root_page():
    # Корень не является отдельной поверхностью продукта: канонический UI только /flow.
    return RedirectResponse(url="/flow", status_code=307)


@app.get("/flow")
@app.get("/flow/{rest:path}")
def flow_page():
    # Единственная актуальная SPA: новый нодовый редактор (React Flow, сборка из
    # frontend/). Любой подпуть /flow отдаёт index.html, ассеты приходят через
    # /static/flow/.
    return FileResponse(Path(__file__).resolve().parent / "static" / "flow" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

# ---------- база захваченных шрифтов сайтов (Source Import) ----------
FONTS_DIR = ROOT / "data" / "fonts"
_FONT_NAME = re.compile(r"^[0-9a-f]{16}\.(woff2|woff|ttf|otf)$")


@app.get("/fonts/{name}")
def serve_font(name: str):
    safe = Path(name).name
    if not _FONT_NAME.match(safe):
        return JSONResponse({"detail": "not found"}, status_code=404)
    p = FONTS_DIR / safe
    if not p.exists():
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(p, media_type=mimetypes.guess_type(safe)[0] or "font/woff2")


@app.exception_handler(Exception)
async def unhandled(request, exc):
    traceback.print_exc()
    return JSONResponse({"detail": f"Внутренняя ошибка: {exc}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    url = "http://127.0.0.1:8420/flow"
    print(f"DesignAI Web: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="warning")
