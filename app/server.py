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
import traceback
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
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from interaction_capture import capture_live_flow
from motion_render import render_video, validate_render_input

APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or APP_ROOT.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")
sys.path.insert(0, str(APP_ROOT))

import llm_client as llm  # chat, chat_vision, build_system_prompt, extract_json
from colorutils import mix_hex_colors
from scraper import analyze_url
from reproduce import run_pipeline as reproduce_pipeline
from urlguard import fetch_public_bytes, validate_public_url
import cache_store
import blockparse
import mergeback
import qualitygate
import project_store
import typography
import designkb
from editor_assist import router as editor_assist_router

import ir
from ir import apply_tokens as apply_ir_tokens
from ir import bind_element_styles as bind_ir_element_styles
from ir import ensure_current as ensure_current_ir
from config import FEATURE_FLAGS

EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
RENDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
RENDER_JOBS: dict[str, dict] = {}
RENDER_JOBS_LOCK = threading.Lock()
RENDER_DIR = DATA_ROOT / "renders"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    EXECUTOR.shutdown(wait=True)
    RENDER_EXECUTOR.shutdown(wait=True)


app = FastAPI(title="DesignAI Web", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"],
)
app.include_router(editor_assist_router)

COLOR_TOKEN_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"]
MAX_CLONE_HTML_BYTES = 2_000_000


def _locked_generation_dna(tokens: dict | None) -> tuple[dict | None, dict | None]:
    """Return prompt-safe public DNA and a complete DNA used to style output IR.

    Older callers may provide only the schema-level color/font/radius fields,
    while Source Import also provides semantic/primitives.  Generation needs
    both forms: compact public tokens in the LLM prompt and semantic values for
    deterministic application to inline styles returned by the model.
    """
    if not isinstance(tokens, dict):
        return None, None
    public_keys = ("mode", "color", "font", "radius", "spacing", "shadow")
    public = {key: copy.deepcopy(tokens[key]) for key in public_keys if key in tokens}
    if not public:
        return None, None
    complete = copy.deepcopy(public)
    for key in ("primitives", "semantic", "provenance"):
        if key in tokens:
            complete[key] = copy.deepcopy(tokens[key])
    if not isinstance(complete.get("semantic"), dict):
        colors = complete.get("color") if isinstance(complete.get("color"), dict) else {}
        fonts = complete.get("font") if isinstance(complete.get("font"), dict) else {}
        radii = complete.get("radius") if isinstance(complete.get("radius"), dict) else {}
        spacing = complete.get("spacing") if isinstance(complete.get("spacing"), dict) else {}
        radius_px = {"none": 0, "xs": 2, "sm": 4, "md": 8, "lg": 16, "xl": 24, "full": 1000}
        section_px = {"sm": 64, "md": 80, "lg": 96, "xl": 128}
        complete["semantic"] = {
            **copy.deepcopy(colors),
            "displayFont": copy.deepcopy(fonts.get("display") or {"family": "Inter", "weight": 700}),
            "bodyFont": copy.deepcopy(fonts.get("body") or {"family": "Inter", "weight": 400}),
            "buttonRadius": radius_px.get(str(radii.get("button") or "md"), 8),
            "cardRadius": radius_px.get(str(radii.get("card") or "lg"), 16),
            "inputRadius": radius_px.get(str(radii.get("input") or "md"), 8),
            "sectionGap": section_px.get(str(spacing.get("section") or "lg"), 96),
            "containerWidth": 1200,
        }
    else:
        # DOM capture represents pill radii as 9999px, while the IR semantic
        # contract caps numeric radii at 1000. Preserve the pill result without
        # emitting an invalid generated document.
        for key in ("buttonRadius", "cardRadius", "inputRadius"):
            value = complete["semantic"].get(key)
            if isinstance(value, (int, float)):
                complete["semantic"][key] = min(1000, max(0, value))
    return public, complete

# роли вызовов для роутинга LLM — см. таблицу llm_client.ROUTING
# (generate/edit/repair/clone/reference/...)


# ---------- helpers ----------

def validate_ir(doc: dict) -> list[str]:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return ir.format_errors(ir.validate_ir(doc))


def sanitize_font_face_weights(doc: dict) -> dict:
    """Variable-шрифты отдают диапазон весов («400 800»), а схема принимает один
    вес. IR, захваченные до нормализации на захвате (scraper._resolve_font_faces),
    чиним на входе: диапазон → базовый вес. Мутирует и возвращает документ."""
    meta = doc.get("meta") if isinstance(doc, dict) else None
    faces = meta.get("fontFaces") if isinstance(meta, dict) else None
    if isinstance(faces, list):
        for face in faces:
            weight = face.get("weight") if isinstance(face, dict) else None
            if isinstance(weight, str) and len(weight.split()) > 1:
                face["weight"] = weight.split()[0]
    return doc


def parse_ir_response(raw: str):
    """extract_json + json.loads -> (ir, error)."""
    try:
        return json.loads(llm.extract_json(raw)), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"невалидный JSON от модели: {e}"


def call_llm_ir(provider: str, user_content: str, temperature: float = 0.8, mode: str = "generate"):
    """Вызов LLM с системным промптом генератора -> (ir, error)."""
    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt(mode)},
            {"role": "user", "content": user_content},
        ], temperature, role="generator" if mode == "generate" else "edit")
    except Exception as e:
        return None, str(e)
    return parse_ir_response(raw)


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


# Поле provider в запросах сохранено для совместимости со старыми сейвами;
# продукт маршрутизирует вызовы по цепочке ROUTING подключённых аккаунтов,
# поэтому вход намеренно игнорируется (всегда "auto").


# ---------- models ----------

class GenerateReq(BaseModel):
    brief: str = ""
    count: int = 3
    provider: str = "auto"
    styleHint: str | None = None
    seedTag: str | None = None
    tokens: dict | None = None  # Style DNA: залоченные design-токены
    preset: str = ""  # стилевой пресет: minimal|bento|editorial|brutal|glass
    prepareOnly: bool = False
    rawOutputs: list[str] | None = None


class MixReq(BaseModel):
    irs: list
    weights: list


class CloneReq(BaseModel):
    url: str = ""
    component: str = ""
    provider: str = "auto"


class BlockParseReq(BaseModel):
    url: str = ""
    blocks: list | None = None  # опционально: [{name, selector}] — клонировать только их
    viewports: list[dict] | None = None
    authCookies: list[dict] | None = None
    authSessionFallback: bool = False


class ReskinReq(BaseModel):
    ir: dict
    prompt: str = ""
    tokens: dict | None = None  # источник нового стиля (design-токены)
    mask: dict = {}             # чекбоксы: colors/fonts/radii/shadows/texts/images
    provider: str = "auto"      # фильтр цепочки ROUTING: auto | openai | kimi


class QualityGateReq(BaseModel):
    ir: dict
    fix: bool = True  # авто-доводка solver'ом (без LLM) того, что чинится


class QualityPassReq(BaseModel):
    ir: dict
    brief: str = ""
    min_score: int = 85
    repair: bool = True
    rejudge: bool = True


class QualityPassCodexOutputs(BaseModel):
    judge: str | None = None
    repair: str | None = None
    rejudge: str | None = None


class QualityPassCodexReq(QualityPassReq):
    outputs: QualityPassCodexOutputs = QualityPassCodexOutputs()


class ConstraintsCheckReq(BaseModel):
    ir: dict
    constraints: list  # [{path, lock?, min?, max?, enum?, max_len?}]


class StyleDnaReq(BaseModel):
    ir: dict


class StyleDnaApplyReq(BaseModel):
    ir: dict
    tokens: dict


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
    interaction: dict
    composition: dict = Field(default_factory=dict)
    scene_settings: dict = Field(default_factory=dict)
    render_settings: dict = Field(default_factory=dict)


class MotionValidateReq(BaseModel):
    motion: dict
    interaction: dict | None = None


class MotionRenderReq(BaseModel):
    base_ir: dict
    interaction: dict
    motion: dict


class ScrapeReq(BaseModel):
    url: str = ""
    use_playwright: bool = True


class ReproduceReq(BaseModel):
    image: str = ""  # base64 data URL
    url: str = ""  # или URL сайта: скриншот снимем сами, результат кэшируется
    provider: str = "auto"  # роль vision выбирает модель из ROUTING
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
    # Browser mode may explicitly select a direct API account. Codex is a
    # desktop-only transport, so unknown/desktop values fall back to ROUTING.
    provider = req.provider if req.provider in ("openai", "kimi") else "auto"
    brief = req.brief.strip()
    if not brief:
        return err(422, "Пустой бриф: опишите, что нужно сгенерировать.")
    count = max(1, min(int(req.count or 1), 5))
    if req.rawOutputs is not None and len(req.rawOutputs) < count:
        return err(422, "Модель вернула меньше ответов, чем запрошено вариантов.")
    has_style = bool(req.styleHint and req.styleHint.strip())
    style = f"\n\n## Reference / style context\n{req.styleHint.strip()}" if has_style else ""
    memory_hint = project_store.build_prompt_memory_hint()
    memory = f"\n\n{memory_hint}" if memory_hint else ""
    mode = "edit" if has_style else "generate"
    dna, complete_dna = _locked_generation_dna(req.tokens)
    preset = typography.PRESETS.get(req.preset or "")
    ptype, pinfo = designkb.detect_product(brief)
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
        if dna:
            user += ("\n\n## Style DNA — обязательные design-токены (залочены)\n"
                     + json.dumps(dna, ensure_ascii=False)
                     + "\nГотовый IR обязан использовать эти tokens в точности "
                       "(mode/color/font/radius/spacing/shadow): вариативность — "
                       "в композиции и контенте, не в токенах.\n"
                       "Токены — это голос бренда, а не декорация: CTA и ключевые "
                       "акценты — tokens.color.primary, фон секций чередуй "
                       "background/surface, текст — text/textMuted. Страница, где "
                       "всё бело-серое и primary нигде не виден, — провал (wireframe, "
                       "а не дизайн). Изображения — только с imagePrompt и конкретным "
                       "арт-дирекшном (объект, свет, палитра).")
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
                # С залоченной DNA палитра не нужна, но UX-правила типа продукта
                # и анти-клише остаются — иначе выходит безликий каркас.
                user += (f"\n\n## UX-правила для типа «{pinfo['label']}»:\n"
                         + "\n".join("- " + r for r in pinfo["rules"])
                         + "\n\nАнти-паттерны — НИКОГДА так не делай:\n"
                         + "\n".join("- " + a for a in designkb.ANTI_AI))
        if req.prepareOnly:
            return user, None, None
        if req.rawOutputs is not None:
            ir, error = parse_ir_response(req.rawOutputs[n - 1])
        else:
            ir, error = call_llm_ir(provider, user, 0.8 if mode == "generate" else 0.3, mode)
        qa = None
        if ir is not None:
            if dna:
                # Give QA the locked palette first; inline styles are applied
                # after autofix so QA cannot silently overwrite the DNA lock.
                ir["tokens"] = copy.deepcopy(complete_dna or dna)
            elif isinstance(ir.get("tokens"), dict):
                # без DNA: шрифтовая пара и кураторская палитра из design KB — лок
                if pair:
                    ir["tokens"]["font"] = typography.font_tokens(pair)
                if palette:
                    ir["tokens"]["color"] = dict(palette)
            # сгенерированный IR — responsive-документ: вьюпорты артборда, чтобы
            # Page/редактор переключали устройства и per-device правки имели куда писаться
            ir.setdefault("responsive", {"viewports": {
                "desktop": {"width": 1440, "height": 900},
                "tablet": {"width": 768, "height": 1024},
                "mobile": {"width": 390, "height": 844}}})
            # авто quality-gate: детерминированный autofix (контраст/сетка/overflow)
            ir, fixlog = qualitygate.autofix(ir)
            if dna:
                # Deterministically update model-provided inline styles. Without
                # this, a black button from the LLM overrides primary in renderer.
                ir = bind_ir_element_styles(ir, complete_dna or dna)
                ir = apply_ir_tokens(ir, complete_dna or dna)
            qa = {"index": n, "fixed": len(fixlog),
                  "violations": [v["rule"] for v in qualitygate.check(ir)]}
            ir = ensure_current_ir(ir, source="generate")
        return ir, error, qa

    if req.prepareOnly:
        system = llm.build_system_prompt(mode)
        return {
            "prompts": [
                {"messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": gen_one(i + 1)[0]},
                ]}
                for i in range(count)
            ],
            "design": {"type": ptype, "label": pinfo["label"]},
        }

    futures = [EXECUTOR.submit(gen_one, i + 1) for i in range(count)]
    variants, errors, qa = [], [], []
    for i, f in enumerate(futures):
        ir, error, q = f.result()
        if ir is not None:
            variants.append(ir)
            qa.append(q)
        else:
            errors.append({"index": i + 1, "error": error})
    if not variants:
        return err(502, f"Ни один вариант не сгенерирован. {errors[0]['error'] if errors else ''}")
    return {"variants": variants, "errors": errors, "qa": qa,
            "design": {"type": ptype, "label": pinfo["label"]}}


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
    provider = "auto"  # вся цепочка ROUTING подключённых аккаунтов

    # SSRF-гард: только публичные http/https URL
    try:
        validate_public_url(url)
    except ValueError as e:
        return err(422, str(e))

    # кэш: тот же сайт повторно — без траты токенов
    hit = cache_store.get("clone_url", cache_store.key_url(url))
    if hit:
        return {**hit, "cached": True}

    # fetch страницы: redirect-ы валидируются пошагово, body ограничен
    try:
        response = fetch_public_bytes(
            url,
            timeout=15,
            max_bytes=MAX_CLONE_HTML_BYTES,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru,en;q=0.9",
            },
        )
        html = response.content.decode("utf-8", errors="replace")
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
        result = blockparse.parse_blocks(
            url,
            blocks=req.blocks,
            viewports=req.viewports,
            auth_cookies=req.authCookies,
        )
        if req.authSessionFallback:
            result["authWarning"] = "В сессии нет cookie для этого URL — выполнен публичный импорт"
        return result
    except ValueError as e:  # кривой список блоков
        return err(422, str(e))
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка block-parse: {e}")


@app.post("/api/reskin")
def reskin(req: ReskinReq):
    """Reskin: AI-рестайл блока с локом структуры.

    LLM (прямой вызов OpenAI/Kimi) → детерминированный merge-back
    (залоченные поля принудительно из входного IR) → валидация по схеме →
    один repair-вызов по существующему паттерну. Дрейф структуры невозможен.
    """
    errors = validate_ir(sanitize_font_face_weights(req.ir))
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

    # выбор пользователя в ноде (openai/kimi) — фильтр цепочки ROUTING, auto = вся цепочка
    provider = req.provider if req.provider in ("openai", "kimi") else "auto"
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


def _quality_judge_messages(ir: dict, brief: str) -> list[dict]:
    return [
        {"role": "system", "content": QUALITY_JUDGE_SYSTEM},
        {"role": "user", "content": "## Бриф\n" + (brief.strip() or "(не указан)")
         + "\n\n## Design IR\n" + json.dumps(ir, ensure_ascii=False)},
    ]


def _parse_quality_scorecard(raw: str, model_route: str) -> dict:
    """Нормализует недоверенный JSON judge до публичного контракта."""
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
        "model_route": model_route,
    }


def _quality_repair_messages(ir: dict, scorecard: dict, brief: str) -> tuple[list[dict] | None, str | None]:
    """Готовит адресную починку только по замечаниям judge."""
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
    return [
            {"role": "system", "content": llm.build_system_prompt("edit")},
            {"role": "user", "content": user},
        ], None


def _parse_quality_repair(raw: str) -> tuple[dict | None, str | None]:
    try:
        repaired, parse_error = parse_ir_response(raw)
        if repaired is None:
            return None, parse_error
        schema_errors = validate_ir(repaired)
        if schema_errors:
            return None, "; ".join(schema_errors[:5])
        return repaired, None
    except Exception as e:
        return None, str(e)


def _quality_scorecard(ir: dict, brief: str) -> dict:
    """Серверный LLM-путь standalone веб-сервера (прямой вызов OpenAI/Kimi)."""
    raw = llm.chat("auto", _quality_judge_messages(ir, brief), 0.2, role="quality_judge")
    return _parse_quality_scorecard(raw, "LLM / quality_judge")


def _quality_repair(ir: dict, scorecard: dict, brief: str) -> tuple[dict | None, str | None]:
    """Серверный LLM-путь standalone веб-сервера (прямой вызов OpenAI/Kimi)."""
    messages, error = _quality_repair_messages(ir, scorecard, brief)
    if messages is None:
        return None, error
    try:
        raw = llm.chat("auto", messages, 0.25, role="quality_repair")
    except Exception as e:
        return None, str(e)
    return _parse_quality_repair(raw)


@app.post("/api/quality-pass")
def quality_pass(req: QualityPassReq):
    """Премиальный контур: детерминированные правила → независимый judge → repair → rejudge.

    API всегда возвращает исходный валидный IR, если repair не удался: результат
    контролируем и не подменяем граф битым ответом модели.
    """
    schema_errors = validate_ir(sanitize_font_face_weights(req.ir))
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


@app.post("/api/quality-pass/codex-step")
def quality_pass_codex_step(req: QualityPassCodexReq):
    """Pure Quality Pass state machine for the desktop Codex transport.

    This endpoint prepares prompts and validates model outputs, but never calls
    an LLM itself. Every request is reconstructed from the source IR plus the
    three bounded raw outputs, so the renderer cannot smuggle trusted state.
    """
    schema_errors = validate_ir(sanitize_font_face_weights(req.ir))
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    outputs = req.outputs
    for stage in ("judge", "repair", "rejudge"):
        raw = getattr(outputs, stage)
        if raw is not None and len(raw.encode("utf-8")) > 2 * 1024 * 1024:
            return err(413, f"Quality Pass {stage}: ответ Codex слишком большой")
    if outputs.judge is None and (outputs.repair is not None or outputs.rejudge is not None):
        return err(422, "Quality Pass: repair/rejudge без judge — неконсистентное состояние Codex")
    if outputs.rejudge is not None and outputs.repair is None:
        return err(422, "Quality Pass: rejudge без repair — неконсистентное состояние Codex")

    deterministic_before = qualitygate.check(req.ir)
    if outputs.judge is None:
        return {"pending": {
            "stage": "judge",
            "profile": "quality_judge",
            "messages": _quality_judge_messages(req.ir, req.brief),
        }}
    try:
        initial = _parse_quality_scorecard(outputs.judge, "Codex app-server / quality_judge")
    except Exception as e:
        return err(502, f"Quality Pass judge вернул неверный ответ: {e}")

    min_score = max(0, min(int(req.min_score), 100))
    important = any(i["severity"] in {"critical", "major"} for i in initial["issues"])
    needs_repair = bool(deterministic_before) or important or initial["score"] < min_score
    if outputs.repair is not None and (not req.repair or not needs_repair):
        return err(422, "Quality Pass: repair не запрашивался — неконсистентное состояние Codex")
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None}
    final = initial

    if req.repair and needs_repair:
        repair["attempted"] = True
        messages, message_error = _quality_repair_messages(req.ir, initial, req.brief)
        if messages is None:
            repair["error"] = message_error
        elif outputs.repair is None:
            return {"pending": {
                "stage": "repair",
                "profile": "quality_repair",
                "messages": messages,
            }}
        else:
            repaired, repair_error = _parse_quality_repair(outputs.repair)
            if repaired is None:
                repair["error"] = repair_error
            else:
                output_ir = repaired
                repair["applied"] = True
                if req.rejudge:
                    if outputs.rejudge is None:
                        return {"pending": {
                            "stage": "rejudge",
                            "profile": "quality_judge",
                            "messages": _quality_judge_messages(output_ir, req.brief),
                        }}
                    try:
                        final = _parse_quality_scorecard(
                            outputs.rejudge, "Codex app-server / quality_judge"
                        )
                    except Exception as e:
                        return err(502, f"Quality Pass rejudge вернул неверный ответ: {e}")

    if outputs.rejudge is not None and not repair["applied"]:
        return err(422, "Quality Pass: rejudge без применённого repair — неконсистентное состояние Codex")
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


def _with_reproduce_parser_contract(payload: dict, source_ref: str, source_kind: str) -> dict:
    """Attach Parser v2 metadata to cached and fresh screenshot reproductions."""
    if isinstance(payload.get("parserContract"), dict):
        return payload
    document = payload.get("ir")
    if not isinstance(document, dict) or not document:
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
    hit = cache_store.get("reproduce_img", img_key)
    if hit:
        source_ref = url or f"image-sha256:{img_key}"
        source_kind = "url" if url else "image"
        return {**_with_reproduce_parser_contract(hit, source_ref, source_kind), "cached": True}

    provider = "auto"  # вся цепочка ROUTING подключённых аккаунтов

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
        },
    }


@app.post("/api/style-dna/extract")
def style_dna_extract(req: StyleDnaReq):
    """Extract primitives + semantic Style DNA from an IR document."""
    current = ensure_current_ir(req.ir)
    schema_errors = validate_ir(current)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    return {"tokens": ir.build_style_dna(current)}


@app.post("/api/style-dna/apply")
def style_dna_apply(req: StyleDnaApplyReq):
    """Apply a Style DNA token set to an IR document, updating bound styles.

    First re-binds element styles to the new token set so semantic changes
    propagate even to documents that did not yet carry styleBindings.
    """
    current = ensure_current_ir(req.ir)
    schema_errors = validate_ir(current)
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    bound = ir.bind_element_styles(current, req.tokens)
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
    interaction_errors = ir.validate_interaction(req.interaction)
    if base_errors:
        return err(422, "Base IR не проходит schema: " + "; ".join(base_errors[:5]))
    if interaction_errors:
        return err(422, "Interaction IR не проходит schema: " + "; ".join(interaction_errors[:5]))
    try:
        motion = ir.build_motion(req.interaction, req.composition, req.scene_settings, req.render_settings)
        scene_irs = []
        for scene in motion["scenes"]:
            scene_ir = ir.replay_interaction(base_ir, req.interaction, scene["interactionSceneId"])
            replay_errors = validate_ir(scene_ir)
            if replay_errors:
                raise ValueError("Motion scene создаёт невалидный IR: " + "; ".join(replay_errors[:5]))
            scene_irs.append({"sceneId": scene["id"], "ir": ensure_current_ir(scene_ir)})
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
    interaction_errors = ir.validate_interaction(req.interaction)
    motion_errors = ir.validate_motion(req.motion, req.interaction)
    if base_errors:
        return err(422, "Base IR does not pass schema: " + "; ".join(base_errors[:5]))
    if interaction_errors:
        return err(422, "Interaction IR does not pass schema: " + "; ".join(interaction_errors[:5]))
    if motion_errors:
        return err(422, "Motion IR does not pass schema: " + "; ".join(motion_errors[:5]))
    if req.motion["source"]["interactionHash"] != ir.content_hash(req.interaction):
        return err(409, "Motion IR does not belong to the supplied Interaction IR.")
    base_hash = base_ir.get("contentHash") or ir.content_hash(base_ir)
    if req.motion["source"]["baseDesignIrHash"] != base_hash:
        return err(409, "Motion IR does not belong to the supplied Design IR.")
    try:
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
    index_path = APP_ROOT / "static" / "flow" / "index.html"
    html = index_path.read_text(encoding="utf-8")
    # The static build must stay relative for Electron file://. For the HTTP
    # surface, inject a literal base before SvelteKit's preload links so the
    # browser preload scanner resolves them through the existing /static mount.
    html = html.replace("<head>", '<head><base href="/static/flow/">', 1)
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")

# ---------- база захваченных шрифтов сайтов (Source Import) ----------
FONTS_DIR = DATA_ROOT / "fonts"
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
