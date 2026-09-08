#!/usr/bin/env python3
"""DesignAI Web — локальный dev-сервер генерации веб-дизайна (Design IR).

Запуск:  .venv/Scripts/python app/server.py   (порт 8420)
"""
import base64
import asyncio
import concurrent.futures
import contextlib
import contextvars
import copy
import io
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
from typing import Literal

# Windows: реестр может не знать MIME для .js/.css/woff — без корректного
# content-type браузер отказывается выполнять module-скрипты сборки /flow
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from interaction_capture import capture_live_flow
from motion_render import render_video, validate_render_input, validate_composition_layers, prepare_composition_layers
from ir.motion_v2 import migrate_motion_v1_to_v2, validate_motion_v2
from quality_certification_adapter import certify_from_reports

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
import run_registry
import cli_llm
import blockparse
import mergeback
import qualitygate
import rules as project_rules
from ir_render import render_png, render_svg_png
import project_store
import typography
import designkb
import generator_policy
from editor_assist import router as editor_assist_router

import ir
from ir import apply_tokens as apply_ir_tokens
from ir import bind_element_styles as bind_ir_element_styles
from ir import ensure_current as ensure_current_ir
from ir import sanitize_generated_ir
from config import FEATURE_FLAGS

EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
SOURCE_IMPORT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
RENDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
SOURCE_IMPORT_JOBS: dict[str, dict] = {}
SOURCE_IMPORT_JOBS_LOCK = threading.Lock()
RENDER_JOBS: dict[str, dict] = {}
RENDER_JOBS_LOCK = threading.Lock()
RENDER_DIR = DATA_ROOT / "renders"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    EXECUTOR.shutdown(wait=True)
    SOURCE_IMPORT_EXECUTOR.shutdown(wait=True)
    RENDER_EXECUTOR.shutdown(wait=True)


app = FastAPI(title="DesignAI Web", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"],
)
app.include_router(editor_assist_router)

from design_system.api import router as design_system_router  # noqa: E402
app.include_router(design_system_router)

from timeline_api import router as timeline_router  # noqa: E402
app.include_router(timeline_router)

from video_api import router as video_router  # noqa: E402
app.include_router(video_router)

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
    # Порт Design System отдаёт плоскую shadcn-карту или foundations, старые
    # Style DNA — частичные tokens v1. Всё приводим к ПОЛНЫМ tokens v1: лок
    # одного совпавшего ключа (radius) ронял IR на схеме.
    from design_system.style_review import coerce_ir_tokens
    coerced = coerce_ir_tokens(tokens)
    if coerced is None:
        return None, None
    public_keys = ("mode", "color", "font", "radius", "spacing", "shadow")
    public = {key: copy.deepcopy(coerced[key]) for key in public_keys}
    tokens = {**coerced, **{key: tokens[key] for key in ("primitives", "semantic", "provenance") if key in tokens}}
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


def call_llm_ir(provider: str, user_content: str, temperature: float = 0.8,
                mode: str = "generate", effort: str = "medium",
                run_id: str | None = None):
    """Вызов LLM с системным промптом генератора -> (ir, error)."""
    pending_chars = 0

    def on_delta(delta: str) -> None:
        nonlocal pending_chars
        if run_registry.is_cancelled(run_id):
            raise RuntimeError("cancelled")
        pending_chars += len(delta)
        if pending_chars >= 512:
            run_registry.add_received_chars(run_id, pending_chars)
            pending_chars = 0

    try:
        raw = llm.chat(provider, [
            {"role": "system", "content": llm.build_system_prompt(mode)},
            {"role": "user", "content": user_content},
        ], temperature, role="generator" if mode == "generate" else "edit",
            reasoning_effort=effort, on_delta=on_delta)
    except Exception as e:
        return None, str(e)
    finally:
        run_registry.add_received_chars(run_id, pending_chars)
    return parse_ir_response(raw)


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


# 499 — клиент отменил запуск (кооперативная отмена через run_registry)
CANCELLED_STATUS = 499


def _finish_run(run_id: str | None, resp) -> None:
    """Закрыть запись реестра по итогу хендлера: отмена > ошибка > успех."""
    if not run_id:
        return
    if run_registry.is_cancelled(run_id):
        status = "cancelled"
    elif isinstance(resp, JSONResponse) and resp.status_code >= 400:
        status = "error"
    else:
        status = "complete"
    run_registry.finish(run_id, status)


# Поле provider в запросах сохранено для совместимости со старыми сейвами;
# продукт маршрутизирует вызовы по цепочке ROUTING подключённых аккаунтов,
# поэтому вход намеренно игнорируется (всегда "auto").


# ---------- models ----------

class GenerateReq(BaseModel):
    brief: str = ""
    count: int = 3
    provider: str = "openai"
    effort: str = "medium"
    styleHint: str | None = None
    seedTag: str | None = None
    tokens: dict | None = None  # Style DNA: залоченные design-токены
    preset: str = ""  # стилевой пресет: minimal|bento|editorial|brutal|glass
    prepareOnly: bool = False
    rawOutputs: list[str] | None = None
    selectedDirection: str = "all"
    surface: str = "auto"
    designStyle: str = "auto"
    preparedContextId: str | None = None
    allowStrictFallback: bool = False
    # ТЗ §19: закреплённая ревизия дизайн-системы {systemId, revision, contentHash, usageMode}
    designSystem: dict | None = None
    # Существующие экраны проекта (порт reference): агент видит их паттерны и
    # мастера, а не «забывает, с чего начинали» на пятом экране.
    referenceIrs: list[dict] | None = None
    # Клиентский id запуска для стадий/отмены (run_registry); старые клиенты не шлют
    runId: str | None = None


class MixReq(BaseModel):
    irs: list
    weights: list


class CloneReq(BaseModel):
    url: str = ""
    component: str = ""
    provider: str = "openai"


class BlockParseReq(BaseModel):
    url: str = ""
    blocks: list | None = None  # опционально: [{name, selector}] — клонировать только их
    viewports: list[dict] | None = None
    authCookies: list[dict] | None = None
    authSessionFallback: bool = False
    fullResolutionEvidence: bool = False
    asyncJob: bool = False


class BlockParseRefineReq(BaseModel):
    """AI-уточнение разбора: только подписи и роли блоков, IR неприкосновенен."""
    blocks: list
    operations: list = []
    source: dict | None = None


class FidelityRepairReq(BaseModel):
    """Цикл AI-починки захвата. prepareOnly отдаёт задания на диагностику
    (регион + узлы), rawOutputs — ответы провайдера; сервер применяет их только
    если пиксельное сходство выросло."""
    blocks: list
    viewport: str = "desktop"
    prepareOnly: bool = False
    rawOutputs: list = []
    maxRegions: int = 3


class ReskinReq(BaseModel):
    ir: dict
    prompt: str = ""
    tokens: dict | None = None  # источник нового стиля (design-токены)
    mask: dict = {}             # чекбоксы: colors/fonts/radii/shadows/texts/images
    provider: str = "openai"    # legacy values migrate to the fixed Sol route
    effort: str = "medium"
    prepareOnly: bool = False     # desktop: вернуть промпты вместо LLM-вызова
    rawOutput: str | None = None  # desktop: ответ подключённого аккаунта
    designSystem: dict | None = None


class ImageGenReq(BaseModel):
    """Нода «Изображение»: SVG от подписочной модели → PNG на сервере."""
    prompt: str = ""
    style: str = "vector"       # vector | texture | icon
    width: int = 1024
    height: int = 1024
    tileable: bool = False
    model: str | None = None
    provider: str = "codex"
    effort: str = "medium"
    prepareOnly: bool = False     # desktop: вернуть промпт вместо LLM-вызова
    rawOutput: str | None = None  # desktop: ответ подключённого аккаунта
    referenceImage: str | None = None  # data:image/… — образец для модели (vision-вход)


class ImageConvertReq(BaseModel):
    image: str
    outputFormat: str = "png"
    requireTransparency: bool = False


class ImageMaskReq(BaseModel):
    image: str
    mask: str


class QualityGateReq(BaseModel):
    ir: dict
    fix: bool = True  # авто-доводка solver'ом (без LLM) того, что чинится
    strictTokens: bool = False  # ДС strict: цвета вне палитры снапятся всегда


class QualityPassReq(BaseModel):
    ir: dict
    provider: str = "auto"
    effort: str = "medium"
    brief: str = ""
    min_score: int = 80
    repair: bool = True
    rejudge: bool = True
    designSystem: dict | None = None
    surface: Literal["auto", "landing", "catalog", "detail", "checkout", "dashboard", "form", "editor", "ai-workspace", "article", "feed", "component"] = "auto"
    visualReview: bool = False
    runId: str | None = None


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


class MotionMigrateV2Req(BaseModel):
    motion: dict
    project_revision: str
    source_mapping: dict = Field(default_factory=dict)


class MotionRenderReq(BaseModel):
    base_ir: dict
    interaction: dict
    motion: dict
    layers: list[dict] | None = None


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


class ProjectSaveReq(BaseModel):
    project: dict
    # CAS-режим: SHA-256 ревизии с прошлого load/save (get.revision).
    # Без поля — прежнее поведение last-write-wins (совместимость, beacon).
    expectedRevision: str | None = None
    user_id: str = project_store.DEFAULT_USER_ID
    project_id: str = project_store.DEFAULT_PROJECT_ID


class ProjectLoadReq(BaseModel):
    user_id: str = project_store.DEFAULT_USER_ID
    project_id: str = project_store.DEFAULT_PROJECT_ID


class TasteOutcomeReq(BaseModel):
    kind: str
    payload: dict = Field(default_factory=dict)
    user_id: str = project_store.DEFAULT_USER_ID
    project_id: str = project_store.DEFAULT_PROJECT_ID


# ---------- endpoints ----------

@app.post("/api/generate")
def generate(req: GenerateReq):
    """Обёртка: регистрирует запуск (стадии/отмена) и закрывает его по итогу."""
    run_id = run_registry.start(req.runId, "generate")
    run_registry.stage(run_id, "prompt", "Собираю промпт")
    resp = None
    try:
        try:
            policy = generator_policy.context(req.brief, surface=req.surface, style=req.designStyle,
                                              ds=req.designSystem, locked=bool(req.tokens), edit=bool(req.styleHint))
        except ValueError as exc:
            return err(422, str(exc))
        prepared = None
        request_key = generator_policy.digest(req.model_dump(exclude={"prepareOnly", "rawOutputs", "runId", "preparedContextId"}))
        if req.preparedContextId:
            prepared = cache_store.get("generator-prepared", req.preparedContextId)
            if not prepared or prepared.get("requestKey") != request_key:
                return err(409, "Контекст генератора изменился или истёк. Запустите генерацию заново.")
        # Pin the same resolved revision in both phases, including refs that omitted a revision.
        resolved = None
        if req.designSystem:
            from design_system import store as ds_store
            resolved, ds_error = ds_store.resolve_ref(req.designSystem)
            if ds_error:
                return err(422, f"Design System: {ds_error}")
        context_key = generator_policy.digest({"policy": policy, "ds": resolved,
            "rules": project_rules.prompt_block("generation"),
            "promptFiles": [llm._file_stamp(llm.ROOT / name) for name in llm._PROMPT_FILES]})
        if prepared and prepared.get("contextKey") != context_key:
            return err(409, "Дизайн-система или правила изменились после подготовки. Запустите генерацию заново.")
        resp = _generate(req, run_id, prepared=prepared, resolved_document=resolved)
        if isinstance(resp, dict):
            records = resp.pop("_directionRecords", [])
            fallback = (resp.get("generationLog") or {}).get("strictFallback")
            policy["effectiveMode"] = fallback or policy["requestedMode"]
            resp["designPolicy"] = policy
            resp.setdefault("generationLog", {})["policy"] = policy
            if req.prepareOnly:
                receipt = uuid.uuid4().hex
                cache_store.put("generator-prepared", receipt, {"requestKey": request_key,
                    "contextKey": context_key, "directions": records})
                resp["preparedContextId"] = receipt
        return resp
    finally:
        _finish_run(run_id, resp)


def _walk_ir_elements(node):
    """Рекурсивно по children секции/элемента."""
    if not isinstance(node, dict):
        return
    for child in node.get("children") or []:
        if isinstance(child, dict):
            yield child
            yield from _walk_ir_elements(child)


def _reference_pinned_component_keys(reference_irs, document: dict) -> list[str]:
    """Resolve DS masters carried by a reference, even when editor metadata is partial."""
    if not isinstance(reference_irs, list):
        return []
    from design_system.compiler import component_shape_hash

    components = {
        str(component.get("componentKey") or key): component
        for key, component in (document.get("components") or {}).items()
        if isinstance(component, dict) and isinstance(component.get("masterIr"), dict)
    }
    result: list[str] = []

    def pin(value) -> None:
        key = str(value or "")
        if key in components and key not in result:
            result.append(key)

    def inspect(value, parent_key: str = "") -> None:
        if isinstance(value, dict):
            if parent_key in ("_dsMaster", "dsMaster", "designSystemMaster"):
                pin(value.get("componentKey"))
            ref = value.get("componentRef")
            if isinstance(ref, dict):
                pin(ref.get("componentKey"))
            for key, child in value.items():
                inspect(child, str(key))
        elif isinstance(value, list):
            for child in value:
                inspect(child, parent_key)

    master_shapes: dict[str, str] = {}
    for key, component in components.items():
        tree = component["masterIr"].get("tree")
        if isinstance(tree, list) and tree and isinstance(tree[0], dict):
            master_shapes[key] = component_shape_hash(tree[0])

    for reference in [item for item in reference_irs if isinstance(item, dict)]:
        inspect(reference)
        tree = reference.get("tree") if isinstance(reference.get("tree"), list) else []
        candidates = [root for root in tree if isinstance(root, dict)]
        for root in list(candidates):
            if root.get("type") == "source-block" and root.get("variant") == "component-master":
                candidates.extend(child for child in (root.get("children") or []) if isinstance(child, dict))
        candidate_shapes = {component_shape_hash(candidate) for candidate in candidates}
        for key, shape in master_shapes.items():
            if shape in candidate_shapes:
                pin(key)
    return result


def _reference_screens_block(irs) -> str:
    """Компактный дайджест существующих экранов: секции, мастера ДС, роли текста.

    Полные IR в промпт не кладём (бюджет), но агент видит, из чего собраны
    соседние экраны, и повторяет те же паттерны — то, чего не умеют
    «креативные» AI-редакторы при росте числа экранов."""
    if not isinstance(irs, list):
        return ""
    lines = []
    for i, ir in enumerate([x for x in irs if isinstance(x, dict)][:3], 1):
        tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
        sections, masters, roles = [], set(), set()
        for sec in tree:
            if not isinstance(sec, dict):
                continue
            label = str(sec.get("type") or "section")
            if sec.get("variant"):
                label += f"/{sec.get('variant')}"
            props = sec.get("props") if isinstance(sec.get("props"), dict) else {}
            head = props.get("heading") or props.get("title") or ""
            if head:
                label += f" «{str(head)[:60]}»"
            sections.append(label)
            for el in [sec, *list(_walk_ir_elements(sec))]:
                meta = el.get("sourceMeta") if isinstance(el.get("sourceMeta"), dict) else {}
                ref = meta.get("componentRef") if isinstance(meta.get("componentRef"), dict) else None
                if ref and ref.get("componentKey"):
                    masters.add(str(ref["componentKey"]))
                if isinstance(el.get("typeRole"), str):
                    roles.add(el["typeRole"])
        tokens = ir.get("tokens") if isinstance(ir.get("tokens"), dict) else {}
        mode = tokens.get("mode") or ""
        lines.append(
            f"Экран {i}{' (' + str(mode) + ')' if mode else ''}: секции — {', '.join(sections) or 'нет'}; "
            f"мастера ДС — {', '.join(sorted(masters)) or 'нет'}; роли текста — {', '.join(sorted(roles)) or 'нет'}."
        )
    if not lines:
        return ""
    return (
        "## Существующие экраны проекта (референс)\n" + "\n".join(lines)
        + "\nСделай так же: те же мастера ДС для тех же ролей (кнопки, карточки, шаги, поля), "
          "та же плотность и ритм секций, те же роли текста и та же тема. Не изобретай новый "
          "компонент там, где на референсе уже используется мастер."
    )


_TYPE_ROLE_RULE = (
    "\n\nТекстовые стили: у heading/text задавай поле typeRole "
    "(display/h1/h2/h3/lead/body/small/eyebrow) вместо инлайновых style.fontSize/"
    "lineHeight/fontWeight/letterSpacing — кегль, интерлиньяж, вес и разрядку даёт роль "
    "из tokens.v2.type.roles, поэтому все абзацы и заголовки одной роли одинаковы. "
    "В style у текста оставляй только цвет."
)


def _embed_mode_block(usage_mode: str) -> str:
    """Режим встраивания зависит от usageMode ДС, а не один текст на все режимы."""
    common = (
        "Результат вставят в существующий сайт из описания выше. "
        "Если бриф просит компонент или секцию — верни ровно её (одна секция в tree), "
        "без навигации, hero и футера; если просит страницу — повтори порядок секций "
        "сайта. Копирайт — в голосе сайта, на его языке, без плейсхолдеров «Lorem»."
    )
    if usage_mode == "extend":
        return (
            "\n\n## Режим встраивания: EXTEND\n"
            "Собирай из зарегистрированных мастеров и их вариантов там, где они подходят; "
            "недостающее строй из примитивов строго в токенах ДС, наследуя геометрию, "
            "радиусы, рамки и типографику мастеров. Новый элемент допустим только если "
            "ни один мастер не закрывает роль. " + common
        )
    if usage_mode == "style-only":
        return (
            "\n\n## Режим встраивания: STYLE ONLY\n"
            "Мастера — стилевой ориентир (характер углов, плотность, рамки, тени), "
            "копировать их не обязательно; токены ДС (цвета, шрифты, радиусы) обязательны, "
            "сырые значения вне токенов — провал. " + common
        )
    return (
        "\n\n## Режим встраивания: STRICT\n"
        "Собирай результат из зарегистрированных мастеров и их вариантов как из "
        "строительных блоков; новые элементы наследуют их геометрию, радиусы, рамки и "
        "типографику. " + common
    )


def _materialize_exact_master(primary: dict, ds_context: dict, ds_compiled: dict | None, reason: str):
    """Точная копия мастера ДС как вариант генерации — без модели.

    Наблюдённый мастер целой секции (шрифты, evidence, responsive) весит десятки
    тысяч токенов и в промпт не помещается; копировать его моделью бессмысленно —
    приложение материализует exact master само и проверяет strict-валидацией.
    Возвращает (ir, check) или (None, check) если копия не прошла проверку."""
    from design_system import compiler as ds_compiler, document as ds_document, resolver as ds_resolver
    recovered = ds_document.preview_ir_for_master(copy.deepcopy(primary["masterIr"]))
    recovered_root = recovered["tree"][0]
    if (recovered_root.get("type") == "source-block"
            and recovered_root.get("variant") == "component-master"
            and recovered_root.get("children")):
        recovered_root = recovered_root["children"][0]
    recovered_root.setdefault("sourceMeta", {})["componentRef"] = ds_compiler.component_handle(
        primary, ds_context.get("systemRef") or {})
    recovered_root["sourceMeta"].setdefault("kind", "component-instance")
    recovered.setdefault("meta", {}).update({
        "designSystemRef": ds_context.get("systemRef"),
        "compiledContextHash": (ds_compiled or {}).get("compiledContextHash"),
        "strictRecovery": "exact-master-materialized",
        "strictRecoveryReason": reason,
        "requestedComponentKey": primary.get("componentKey"),
    })
    check = ds_resolver.validate_generation(recovered, ds_context)
    return (recovered if not check["errors"] else None), check


_CONTENT_SLOT_KEYS = ("text", "title", "placeholder", "value", "label", "alt")
_CONTENT_SLOT_LIMIT = 80


def _content_slots(ir: dict) -> list[dict]:
    """Текстовые слоты точной копии мастера: {id, path, key, role, text}.

    Модель переписывает только их — структура, стили и геометрия мастера
    остаются пиннутыми (component_shape_hash игнорирует контентные ключи)."""
    slots: list[dict] = []

    def role_of(node: dict, key: str) -> str:
        if node.get("typeRole"):
            return str(node["typeRole"])
        t = str(node.get("type") or "")
        if t == "heading":
            return f"h{node.get('level') or 2}"
        if t in ("button", "badge", "input", "stat"):
            return t if key != "placeholder" else "placeholder"
        return "text"

    def walk(node, path):
        if isinstance(node, dict):
            for key in _CONTENT_SLOT_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value.strip() and len(slots) < _CONTENT_SLOT_LIMIT:
                    slots.append({"id": f"s{len(slots) + 1}", "path": f"{path}.{key}", "key": key,
                                  "role": role_of(node, key), "text": value})
            for i, child in enumerate(node.get("children") or []):
                walk(child, f"{path}.children.{i}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}.{i}")

    for i, section in enumerate(ir.get("tree") or []):
        walk(section, f"tree.{i}")
    return slots


def _content_rewrite_messages(slots: list[dict], brief: str, ds_doc: dict | None,
                              variant_index: int, count: int, rules_block: str = "") -> list[dict]:
    """Промпт «тот же мастер, другой контент»: только слоты, без IR — влезает в любой бюджет."""
    site = (ds_doc or {}).get("siteBrief") or {}
    voice = {k: site.get(k) for k in ("summary", "audience", "offer", "tone") if site.get(k)}
    system = (
        "Ты копирайтер и дизайнер интерфейсов. Тебе дан список текстовых слотов существующего компонента "
        "дизайн-системы (структура, стили и геометрия зафиксированы и меняться не будут). "
        "Перепиши тексты под бриф: тот же смысловой порядок и роли слотов, близкая длина (±30%), "
        "тот же формат чисел/валют, без плейсхолдеров и «Lorem». Язык — как в брифе, если бриф не просит иначе. "
        "Верни ТОЛЬКО JSON вида {\"slots\": [{\"id\": \"s1\", \"text\": \"...\"}, ...]} со всеми id из списка."
    )
    user = (
        f"## Бриф\n{brief}\n\n"
        + (f"## Голос сайта\n{json.dumps(voice, ensure_ascii=False)}\n\n" if voice else "")
        + (f"{rules_block}\n\n" if rules_block else "")
        + (f"Вариант {variant_index} из {count}: сделай контент отличным от других вариантов "
           f"(другие акценты/формулировки при том же смысле).\n\n" if count > 1 else "")
        + "## Слоты (id · роль · текущий текст)\n"
        + "\n".join(f"{s['id']} · {s['role']} · {json.dumps(s['text'], ensure_ascii=False)}" for s in slots)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _apply_content_answer(ir: dict, slots: list[dict], raw: str) -> tuple[dict, int, str]:
    """Применить ответ модели к копии мастера. Возвращает (ir, число заменённых слотов, ошибка)."""
    out = copy.deepcopy(ir)
    try:
        parsed = json.loads(llm.extract_json(raw or ""))
    except Exception as exc:  # noqa: BLE001 — ответ модели произвольный
        return out, 0, f"ответ не JSON: {exc}"
    items = parsed.get("slots") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return out, 0, "в ответе нет slots"
    by_id = {str(item.get("id")): item.get("text") for item in items
             if isinstance(item, dict) and isinstance(item.get("text"), str)}
    replaced = 0
    for slot in slots:
        text = by_id.get(slot["id"])
        if text is None or text == slot["text"]:
            continue
        found, container = qualitygate.get_path(out, slot["path"].rsplit(".", 1)[0])
        if found and isinstance(container, dict):
            container[slot["key"]] = text.strip()[:600]
            replaced += 1
    return out, replaced, ""


def _generate(req: GenerateReq, run_id: str | None, *, prepared: dict | None = None,
              resolved_document: dict | None = None):
    # Browser mode may explicitly select a direct API account. Codex is a
    # desktop-only transport, so unknown/desktop values fall back to ROUTING.
    # codex/claude — консольные аккаунты (cli_llm); всё остальное — Sol по ключу
    # или первый доступный CLI, если ключа нет (см. llm_client.chat_envelope).
    provider = req.provider if getattr(req, "provider", None) in ("astra", "codex", "claude") else "openai"
    effort = req.effort if req.effort in ("medium", "high", "max") else "medium"
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
    policy_context = generator_policy.context(req.brief, surface=req.surface, style=req.designStyle,
        ds=req.designSystem, locked=bool(req.tokens), edit=mode == "edit")
    surface = policy_context["surface"]
    policy_block = generator_policy.prompt(policy_context)
    if run_registry.is_cancelled(run_id):
        return err(CANCELLED_STATUS, "Генерация отменена")
    rules_block = project_rules.prompt_block("generation")
    reference_block = _reference_screens_block(req.referenceIrs)
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
    if surface != "landing" and not dna:
        pair = None
    ds_doc = None

    # Design System: закрепляем ревизию на момент старта (§16.2) и строим
    # компактный контекст один раз; в промпт уходит prompt-block, не весь документ
    ds_context = None
    ds_prompt_block = ""
    ds_compiled = None
    ds_usage_mode = ""
    pinned_master_keys: list[str] = []
    ds_reference_instruction = ""
    if isinstance(req.designSystem, dict) and req.designSystem.get("systemId"):
        from design_system import resolver as ds_resolver, store as ds_store
        ds_doc, ds_error = (resolved_document, None) if resolved_document is not None else ds_store.resolve_ref(req.designSystem)
        if ds_error:
            return err(422, f"Design System: {ds_error}")
        ds_usage_mode = str(req.designSystem.get("usageMode") or "strict")
        pinned_master_keys = _reference_pinned_component_keys(req.referenceIrs, ds_doc)
        ds_context = ds_resolver.resolve_context(
            ds_doc, brief, usage_mode=ds_usage_mode, pinned_keys=pinned_master_keys)
        if ds_usage_mode == "strict" and not ds_context.get("components"):
            return err(422, "Design System Strict: нет опубликованных мастеров для этой задачи. Используйте Extend или добавьте мастер.")
        # Strict обязан вместить exact master целой секции — на 4000 токенов
        # он не помещался и генерация падала «не помещается в context budget».
        provider_budget = 24_000 if ds_usage_mode == "strict" else 1200
        ds_compiled = ds_resolver.compiled_context(
            ds_context, brief=brief,
            archetype_id=str(req.designSystem.get("archetypeId") or ""),
            token_budget=int(req.designSystem.get("tokenBudget") or provider_budget),
            pinned_keys=pinned_master_keys,
        )
        if ds_usage_mode == "strict" and not ds_compiled.get("strictReady"):
            # Пиннутый мастер (референс = мастер ДС) не влезает в бюджет промпта —
            # модель тут не нужна: отдаём точную копию мастера как вариант.
            primary = (ds_resolver.primary_component_for_brief(ds_context, brief, pinned_keys=pinned_master_keys)
                       if pinned_master_keys else None)
            recovered, recovered_check = (_materialize_exact_master(
                primary, ds_context, ds_compiled, "pinned-master-exceeds-context-budget")
                if primary is not None else (None, None))
            if recovered is None:
                return err(422, "Design System Strict: exact master не помещается в выбранный context budget. "
                                "Переключите режим ДС на Extend/Style-only или отключите ДС для этой ноды (× в строке «ДС» на ноде)")
            run_registry.stage(run_id, "design-system", "Материализую точный мастер ДС, модель переписывает контент")
            recovered = ensure_current_ir(recovered, source="generate")
            key = str(primary.get("componentKey") or "")
            # Тот же мастер — другой контент: точная копия референса как результат
            # бессмысленна, поэтому модель переписывает только текстовые слоты по брифу.
            slots = _content_slots(recovered)
            content_prompts = [_content_rewrite_messages(slots, brief, ds_doc, n + 1, count, rules_block)
                               for n in range(count)] if slots else []
            for messages in content_prompts:
                messages[0]["content"] += ("\nGenerator policy generator-design/1.0: rewrite only allowed text slots. "
                    "Do not invent ratings, customers, guarantees or prices. Preserve labels, units and the user's task. "
                    "Keep the slots output contract; masters and foundations are immutable.")
            if req.prepareOnly:
                return {
                    "variants": [recovered], "errors": [], "prompts": [{"messages": m} for m in content_prompts],
                    "contentRewrite": {"slots": len(slots), "componentKey": key},
                    "design": {"type": ptype, "label": pinfo["label"]},
                }
            variants_out, journal_lines, errors_out = [], [], []
            for n in range(count):
                if not slots:
                    variants_out.append(copy.deepcopy(recovered))
                    journal_lines.append(["у мастера нет текстовых слотов — отдана точная копия"])
                    continue
                if req.rawOutputs is not None:
                    raw = req.rawOutputs[n] if n < len(req.rawOutputs) else ""
                else:
                    run_registry.stage(run_id, "llm", f"Модель переписывает контент мастера ({n + 1}/{count})")
                    try:
                        raw = llm.chat(provider, content_prompts[n], 0.7, role="edit", reasoning_effort=effort)
                    except Exception as exc:  # noqa: BLE001
                        raw = ""
                        errors_out.append({"index": n + 1, "error": f"контент: {exc}"})
                variant, replaced, apply_error = _apply_content_answer(recovered, slots, raw)
                variant = ensure_current_ir(variant, source="generate")
                schema_errors = validate_ir(variant)
                ds_check = ds_resolver.validate_generation(variant, ds_context)
                if schema_errors or ds_check.get("errors"):
                    variant, replaced = copy.deepcopy(recovered), 0
                    apply_error = "Контент нарушил контракт мастера; сохранён исходник"
                if apply_error:
                    errors_out.append({"index": n + 1, "error": apply_error})
                variant.setdefault("meta", {})["contentRewrite"] = {"slots": len(slots), "replaced": replaced,
                                                                    **({"error": apply_error} if apply_error else {})}
                variants_out.append(variant)
                journal_lines.append([
                    f"strict: мастер «{key}» ≈{ds_compiled.get('estimatedTokens')} токенов не влезает в бюджет "
                    f"{ds_compiled.get('tokenBudget')} — точная копия мастера, модель переписала контент",
                    f"контент: заменено {replaced} из {len(slots)} слотов" + (f" ({apply_error})" if apply_error else ""),
                ])
            return {
                "variants": variants_out, "errors": errors_out, "prompts": [],
                "qa": [{"index": n + 1, "fixed": 0, "violations": generator_policy.lint(variants_out[n], "component"), "recovery": "exact-master-materialized"}
                       for n in range(len(variants_out))],
                "design": {"type": ptype, "label": pinfo["label"]},
                "generationLog": {
                    "product": pinfo["label"], "mode": mode, "tokensLocked": True,
                    "projectRules": bool(rules_block),
                    "referenceScreens": len([x for x in (req.referenceIrs or []) if isinstance(x, dict)]),
                    "designSystem": {
                        "name": (ds_doc or {}).get("name") or "",
                        "systemId": (ds_context.get("systemRef") or {}).get("systemId"),
                        "revision": (ds_context.get("systemRef") or {}).get("revision"),
                        "usageMode": ds_usage_mode,
                        "componentsAvailable": len(ds_context.get("components") or []),
                        "mastersInContext": [key],
                        "strictReady": False,
                        "errors": 0, "warnings": len((recovered_check or {}).get("warnings") or []),
                        "recovered": {"componentKey": key, "reason": "pinned-master-exceeds-context-budget"},
                        "pinnedMaster": key,
                    },
                    "pinnedMaster": key,
                    "strictRecovery": "exact-master-materialized",
                    "contentRewrite": {"slots": len(slots)},
                    "variants": [{"index": n + 1, "autofixes": 0, "journal": journal_lines[n],
                                  "lint": [], "recovery": "exact-master-materialized"}
                                 for n in range(len(variants_out))],
                },
                "designSystem": {"ref": ds_context.get("systemRef"), "errors": [], "warnings": (recovered_check or {}).get("warnings") or [],
                                 "recovered": {"componentKey": key, "reason": "pinned-master-exceeds-context-budget"}},
            }
        ds_prompt_block = ds_compiled["promptBlock"]
        # ДС — источник истины и для токенов, и для атмосферы: если по порту
        # пришло что-то неполное (или ничего), лочим токены из foundations
        # документа и добавляем профиль стиля (тема, углы, плотность, голос копирайта).
        from design_system import style_review as ds_style_review
        ds_dna, ds_complete_dna = _locked_generation_dna(
            ds_style_review.ir_tokens(ds_doc.get("foundations") or {}))
        if ds_dna:
            dna, complete_dna = ds_dna, ds_complete_dna
        ds_prompt_block += "\n\n" + ds_style_review.profile_prompt(ds_doc)
        ds_prompt_block += _embed_mode_block(ds_usage_mode)
        if dna and dna.get("font"):
            pair = None
        if ds_usage_mode == "strict" and pinned_master_keys:
            pinned = next((component for component in ds_context.get("components") or []
                           if str(component.get("componentKey") or "") == pinned_master_keys[0]), None)
            if pinned is not None:
                from design_system import compiler as ds_compiler
                handle = ds_compiler.component_handle(pinned, ds_context.get("systemRef") or {})
                ds_reference_instruction = (
                    f"Референс — это мастер {pinned_master_keys[0]}; результат обязан быть копией этого мастера "
                    f"с componentRef {json.dumps(handle, ensure_ascii=False)}, меняй только контент."
                )

    directions: list[dict] = []
    art_direction_error = ""
    exemplars = ""
    if mode == "generate" and prepared is not None:
        directions = prepared.get("directions") or []
    elif mode == "generate" and (surface != "landing" or policy_context["foundationsLocked"]):
        directions = generator_policy.directions(policy_context)
    elif mode == "generate":
        run_registry.stage(run_id, "art-direction", "Формирую три арт-направления")
        try:
            import art_direction
            generated_directions = art_direction.create_design_brief(
                brief,
                ptype,
                style_dna={"tokens": dna, "designSystem": req.designSystem,
                           "policyHash": policy_context["policyHash"], "surface": surface, "style": req.designStyle},
                provider=provider,
                count=3,
                generate_if_missing=req.rawOutputs is None,
            )
            if isinstance(generated_directions, list):
                directions = generated_directions
        except Exception as exc:
            # Art direction raises the quality ceiling but is deliberately not
            # a dependency: provider/cache failures keep generation available.
            art_direction_error = str(exc)
    if mode == "generate" and surface == "landing" and not ds_context:
        exemplars = llm.load_exemplars(ptype, limit=2)

    public_directions = [
        {key: item[key] for key in ("id", "label", "motivation", "tradeoff")}
        for item in directions
    ]
    requested_direction = str(req.selectedDirection or "all")
    chosen_direction = next(
        (item for item in directions if str(item.get("id")) == requested_direction),
        None,
    )
    selected_direction = requested_direction if chosen_direction is not None else "all"

    def direction_for(n: int) -> dict | None:
        if chosen_direction is not None:
            return chosen_direction
        return directions[(n - 1) % len(directions)] if directions else None

    def call_context_llm(user_content: str, direction: dict | None):
        pending_chars = 0

        def on_delta(delta: str) -> None:
            nonlocal pending_chars
            if run_registry.is_cancelled(run_id):
                raise RuntimeError("cancelled")
            pending_chars += len(delta)
            if pending_chars >= 512:
                run_registry.add_received_chars(run_id, pending_chars)
                pending_chars = 0

        try:
            raw = llm.chat(provider, [
                {"role": "system", "content": llm.build_system_prompt(
                    mode,
                    design_brief=(direction or {}).get("designBrief") or (direction or {}).get("plan") or "",
                    exemplars=exemplars,
                    policy=policy_block + "\n\n" + ds_prompt_block,
                )},
                {"role": "user", "content": user_content},
            ], 0.8 if mode == "generate" else 0.3,
                role="generator" if mode == "generate" else "edit",
                reasoning_effort=effort, on_delta=on_delta)
        except Exception as exc:
            return None, str(exc)
        finally:
            run_registry.add_received_chars(run_id, pending_chars)
        return parse_ir_response(raw)


    def gen_one(n: int):
        variant_direction = direction_for(n)
        variant_pair = pair
        if not dna and not ds_context:
            pair_name = ((variant_direction or {}).get("designBrief") or {}).get("typePair")
            variant_pair = typography.PAIRS_BY_NAME.get(pair_name, pair)
        if mode == "edit":
            user = (
                f"## Reference context\n{req.styleHint.strip()}\n\n"
                f"## Modification instruction\n{brief}\n\n"
                f"REPRODUCE the reference structure and content EXACTLY. "
                f"Apply ONLY the modification above. Do NOT add or remove sections/elements. "
                f"Do NOT invent content not present in the reference."
            )
        else:
            vary = ("своя композиция и раскладка в рамках токенов DNA; настроение, "
                    "тема и характер ИСХОДНИКА сохраняются" if dna
                    else "своя палитра, типографика, настроение и композиция")
            user = (
                f"## Brief\n{brief}\n\n"
                f"Вариант {n} из {count}: сделай визуально отличное решение №{n} — "
                f"{vary}, не повторяй другие варианты."
            )
        if mode == "generate" and variant_direction:
            user += (
                "\n\n## Assigned art direction\n"
                f"ID: {variant_direction['id']}\n"
                f"Label: {variant_direction['label']}\n"
                f"Motivation: {variant_direction['motivation']}\n"
                f"Tradeoff: {variant_direction['tradeoff']}\n"
                "Follow this direction consistently; do not substitute another direction."
            )
        if req.seedTag:
            user += f"\nseedTag: {req.seedTag}"
        if style and mode != "edit":
            user += style
        if memory:
            user += memory
        if dna:
            user += ("\n\n## Locked Style DNA\n" + json.dumps(dna, ensure_ascii=False)
                     + "\nUse these foundations exactly. Preserve the supplied theme, typography, radii and spacing. "
                       "Use semantic color roles according to their purpose. Component masters take precedence over "
                       "generic token application. Do not force alternating backgrounds, border widths or an accent "
                       "that the supplied system does not prescribe. Images need a concrete imagePrompt.")
        elif variant_pair and not ds_context:
            user += "\n\n" + typography.typography_guide(variant_pair, scale, preset)
        palette = None
        # The surface recipe replaces unconditional landing/palette/anti-font defaults.
        user += "\nApply the system's selected surface recipe and locked foundations."
        if mode == "generate":
            user += _TYPE_ROLE_RULE
        if reference_block:
            user += "\n\n" + reference_block
        if ds_prompt_block:
            user += "\n\n" + ds_prompt_block
        if ds_reference_instruction:
            user += "\n\n" + ds_reference_instruction
        if rules_block:
            user += "\n\n" + rules_block
        if req.prepareOnly:
            return user, None, None
        if run_registry.is_cancelled(run_id):
            return None, "cancelled", None
        if req.rawOutputs is not None:
            run_registry.stage(run_id, "parse", "Разбираю ответ модели")
            ir, error = parse_ir_response(req.rawOutputs[n - 1])
        else:
            run_registry.stage(run_id, "llm", f"Модель генерирует IR ({count} вар.)" if count > 1 else "Модель генерирует IR")
            if mode == "generate":
                ir, error = call_context_llm(user, variant_direction)
            else:
                ir, error = call_context_llm(user, variant_direction)
            run_registry.stage(run_id, "validate", "Проверка схемы и автофиксы")
        qa = None
        if ir is not None:
            ir = sanitize_generated_ir(ir)
            # A model can return a schema-valid refusal as empty composition frames.
            # It is not a generated design and must not enter previews or Quality Pass.
            def empty_composition(node):
                if not isinstance(node, dict) or node.get("type") not in {"composition", "frame"}:
                    return False
                props, style = node.get("props") or {}, node.get("style") or {}
                if any(props.get(key) for key in ("heading", "title", "text", "subheading")):
                    return False
                if any(style.get(key) not in (None, "", "none", "transparent") for key in ("background", "backgroundColor", "backgroundImage", "borderColor", "boxShadow")):
                    return False
                return all(empty_composition(child) for child in node.get("children", []))
            if not ir.get("tree") or all(empty_composition(root) for root in ir["tree"]):
                return None, "Модель вернула пустой макет. Проверьте промпт и приложенный референс и повторите запуск.", None
            if variant_direction:
                ir.setdefault("meta", {})["direction"] = {
                    "name": str(variant_direction["label"])[:60],
                    "motivation": str(variant_direction["motivation"])[:200],
                    "tradeoff": str(variant_direction["tradeoff"])[:200],
                }
            if dna:
                # Give QA the locked palette first; inline styles are applied
                # after autofix so QA cannot silently overwrite the DNA lock.
                ir["tokens"] = copy.deepcopy(complete_dna or dna)
            elif isinstance(ir.get("tokens"), dict):
                # без DNA: шрифтовая пара и кураторская палитра из design KB — лок
                if variant_pair:
                    ir["tokens"]["font"] = typography.font_tokens(variant_pair)
                if palette:
                    ir["tokens"]["color"] = dict(palette)
            # сгенерированный IR — responsive-документ: вьюпорты артборда, чтобы
            # Page/редактор переключали устройства и per-device правки имели куда писаться
            ir.setdefault("responsive", {"viewports": {
                "desktop": {"width": 1440, "height": 900},
                "tablet": {"width": 768, "height": 1024},
                "mobile": {"width": 390, "height": 844}}})
            # авто quality-gate: детерминированный autofix (контраст/сетка/overflow,
            # DS-lint: цвета/шрифты/роли — в strict ДС цвета снапятся к токенам всегда)
            protected_masters = ds_usage_mode == "strict" or generator_policy.has_masters(ir)
            if protected_masters:
                fixlog = []  # Exact masters are validated, never snapped/reflowed by generic fixes.
            else:
                ir, fixlog = qualitygate.autofix(ir, rules=[r for r in qualitygate.RULES
                    if r["id"] not in {"grid-8"} and not (surface == "component" and r["id"] in {"single-h1", "frame-overflow"})])
            if dna and not protected_masters:
                # Deterministically update model-provided inline styles. Without
                # this, a black button from the LLM overrides primary in renderer.
                ir = bind_ir_element_styles(ir, complete_dna or dna)
                ir = apply_ir_tokens(ir, complete_dna or dna)
            lint = generator_policy.lint(ir, surface, locked=bool(dna))
            qa = {"index": n, "fixed": len(fixlog),
                  "violations": [v["rule"] for v in lint],
                  "lint": [{"rule": v["rule"], "severity": v.get("severity"), "path": v.get("path"),
                            "message": v.get("message")} for v in lint][:24],
                  "journal": fixlog[:24]}
            ir = ensure_current_ir(ir, source="generate")
            schema_errors = validate_ir(ir)
            if schema_errors:
                return None, "Generated IR does not pass schema: " + "; ".join(schema_errors[:5]), qa
        return ir, error, qa

    if req.prepareOnly:
        prepared_directions = [direction_for(i + 1) for i in range(count)]
        return {
            "prompts": [
                {"messages": [
                    {"role": "system", "content": llm.build_system_prompt(
                        mode,
                        design_brief=(prepared_directions[i] or {}).get("designBrief") or (prepared_directions[i] or {}).get("plan") or "",
                        exemplars=exemplars,
                        policy=policy_block + "\n\n" + ds_prompt_block,
                    )},
                    {"role": "user", "content": gen_one(i + 1)[0]},
                ]}
                for i in range(count)
            ],
            "design": {"type": ptype, "label": pinfo["label"]},
            "directions": public_directions,
            "variantDirections": [item["label"] if item else "" for item in prepared_directions],
            "designBrief": ((prepared_directions[0] or {}).get("designBrief")
                            if prepared_directions else None),
            "designBriefs": [(item or {}).get("designBrief") for item in prepared_directions],
            "_directionRecords": directions,
            **({"designSystem": {"ref": ds_context.get("systemRef"), **ds_compiled}}
               if ds_context is not None and ds_compiled else {}),
        }

    # copy_context: contextvar-токен отмены десктопного воркера (cancel_token)
    # иначе не виден в потоках пула — LLM-вызовы дорабатывали бы после отмены.
    futures = [EXECUTOR.submit(contextvars.copy_context().run, gen_one, i + 1) for i in range(count)]
    variants, errors, qa = [], [], []
    for i, f in enumerate(futures):
        ir, error, q = f.result()
        if ir is not None:
            variants.append(ir)
            qa.append(q)
        else:
            errors.append({"index": i + 1, "error": error})
    if run_registry.is_cancelled(run_id):
        return err(CANCELLED_STATUS, "Генерация отменена")
    if not variants and not (ds_usage_mode == "strict" and ds_context is not None):
        return err(502, f"Ни один вариант не сгенерирован. {errors[0]['error'] if errors else ''}")
    run_registry.stage(run_id, "design-system", "Проверка дизайн-системы и сборка ответа")
    design_system_report = None
    strict_fallback = ""
    if ds_context is not None:
        from design_system import resolver as ds_resolver
        design_system_report = {"errors": [], "warnings": []}
        accepted_variants = []
        strict_candidate_variants = list(variants)
        for variant_index, variant in enumerate(variants, start=1):
            check = ds_resolver.validate_generation(variant, ds_context)
            if check["errors"] or check["warnings"]:
                variant.setdefault("meta", {})
                if check["errors"]:
                    variant["meta"]["designSystemErrors"] = check["errors"]
                if check["warnings"]:
                    variant["meta"]["designSystemWarnings"] = check["warnings"]
            if ds_compiled:
                variant.setdefault("meta", {})
                variant["meta"].update({
                    "designSystemRef": ds_context.get("systemRef"),
                    "compiledContextHash": ds_compiled.get("compiledContextHash"),
                    "archetypeId": ds_compiled.get("archetypeId"),
                    "identityScore": (check.get("identity") or {}).get("score"),
                    "identityReport": check.get("identity"),
                })
            design_system_report["errors"].extend(check["errors"])
            design_system_report["warnings"].extend(check["warnings"])
            if ds_usage_mode == "strict" and check["errors"]:
                errors.append({
                    "index": variant_index,
                    "error": "Design System Strict: " + "; ".join(item["message"] for item in check["errors"][:4]),
                })
            else:
                accepted_variants.append(variant)
        design_system_report["ref"] = ds_context.get("systemRef")
        if ds_compiled:
            design_system_report.update({
                "compiledContextHash": ds_compiled.get("compiledContextHash"),
                "includedRuleIds": ds_compiled.get("includedRuleIds"),
                "omittedRuleIds": ds_compiled.get("omittedRuleIds"),
                "estimatedTokens": ds_compiled.get("estimatedTokens"),
                "archetypeId": ds_compiled.get("archetypeId"),
            })
        if ds_usage_mode == "strict":
            variants = accepted_variants
            if not variants:
                # A large observed master (for example a responsive service card
                # with lossless image evidence) may not fit the provider prompt
                # budget. The provider still interprets the brief, while the
                # application owns exact-master materialisation and verification.
                primary = ds_resolver.primary_component_for_brief(
                    ds_context, brief, pinned_keys=pinned_master_keys)
                if primary is not None:
                    recovered, recovered_check = _materialize_exact_master(
                        primary, ds_context, ds_compiled, "provider-output-failed-strict-exact-master-validation")
                    if recovered is not None:
                        variants = [recovered]
                        qa.append({"index": 1, "fixed": 1, "violations": [],
                                   "recovery": "exact-master-materialized"})
                        design_system_report["recovered"] = {
                            "componentKey": primary.get("componentKey"),
                            "reason": "provider-output-failed-strict-exact-master-validation",
                        }
                if not variants and strict_candidate_variants and req.allowStrictFallback:
                    strict_fallback = "extend"
                    fallback_warning = {
                        "code": "strict-fallback-extend",
                        "message": "Strict: мастера не использованы, результат принят в режиме extend",
                    }
                    for variant in strict_candidate_variants:
                        meta = variant.setdefault("meta", {})
                        meta.pop("designSystemErrors", None)
                        meta.setdefault("designSystemWarnings", []).append(fallback_warning)
                    variants = strict_candidate_variants
                    errors = [item for item in errors
                              if not str(item.get("error") or "").startswith("Design System Strict:")]
                    rejected = list(design_system_report["errors"])
                    design_system_report["errors"] = []
                    design_system_report["warnings"].extend(rejected)
                    design_system_report["warnings"].append(fallback_warning)
                if not variants:
                    first = design_system_report["errors"][0]["message"] if design_system_report["errors"] else "strict validation failed"
                    return err(422, f"Design System Strict отклонил все варианты: {first}")
    # Журнал решений: что агент получил и что проверил — вместо чёрного ящика.
    generation_log = {
        "product": pinfo["label"],
        "mode": mode,
        "tokensLocked": bool(dna),
        "projectRules": bool(rules_block),
        "referenceScreens": len([x for x in (req.referenceIrs or []) if isinstance(x, dict)]),
        **({"strictFallback": strict_fallback} if strict_fallback else {}),
        "direction": {
            "selected": selected_direction,
            "variants": [
                (variant.get("meta") or {}).get("direction", {}).get("name", "")
                for variant in variants
            ],
            "degraded": not bool(directions),
            **({"error": art_direction_error} if art_direction_error else {}),
        },
        "designSystem": ({
            "name": (ds_doc or {}).get("name") or "",
            "systemId": (ds_context.get("systemRef") or {}).get("systemId"),
            "revision": (ds_context.get("systemRef") or {}).get("revision"),
            "usageMode": ds_usage_mode,
            "componentsAvailable": len(ds_context.get("components") or []),
            "mastersInContext": list((ds_compiled or {}).get("includedMasterKeys") or []),
            "pinnedMaster": pinned_master_keys[0] if pinned_master_keys else None,
            "strictReady": (ds_compiled or {}).get("strictReady"),
            "errors": len((design_system_report or {}).get("errors") or []),
            "warnings": len((design_system_report or {}).get("warnings") or []),
            "recovered": (design_system_report or {}).get("recovered"),
        } if ds_context is not None else None),
        "variants": [{
            "index": q.get("index"),
            "autofixes": q.get("fixed", 0),
            "journal": q.get("journal") or [],
            "lint": q.get("lint") or [],
            "recovery": q.get("recovery"),
        } for q in qa],
    }
    return {"variants": variants, "errors": errors, "qa": qa,
            "design": {"type": ptype, "label": pinfo["label"]},
            "directions": public_directions,
            "variantDirections": [
                (variant.get("meta") or {}).get("direction", {}).get("name", "")
                for variant in variants
            ],
            "generationLog": generation_log,
            **({"designSystem": design_system_report} if design_system_report else {})}


class ProjectRulesReq(BaseModel):
    text: str = ""


@app.get("/api/rules")
def get_rules():
    """Правила, по которым работают генератор и судья: встроенные + правила проекта."""
    return project_rules.payload()


@app.post("/api/rules/project")
def save_rules(req: ProjectRulesReq):
    try:
        project_rules.save_project_rules(req.text)
    except ValueError as e:
        return err(422, str(e))
    return project_rules.payload()


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
            ], 0.2, role="repair", reasoning_effort=effort)
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


_SOURCE_STAGE_PROGRESS = {
    "prepare": (3, "Подготовка"),
    "cacheLookup": (7, "Проверка кэша"),
    "renderDom": (22, "Загрузка DOM"),
    "detectBlocks": (30, "Детекция блоков"),
    "semanticRefine": (34, "Разметка секций"),
    "captureCompile": (72, "Слои и responsive"),
    "assemble": (80, "Сборка Design IR"),
    "fidelity": (95, "Проверка fidelity"),
    "cacheWrite": (99, "Сохранение кэша"),
}


def _execute_block_parse(values: dict, on_stage=None) -> dict:
    result = blockparse.parse_blocks(
        values["url"],
        blocks=values.get("blocks"),
        viewports=values.get("viewports"),
        auth_cookies=values.get("authCookies"),
        full_resolution_evidence=bool(values.get("fullResolutionEvidence")),
        on_stage=on_stage,
    )
    if values.get("authSessionFallback"):
        result["authWarning"] = "В сессии нет cookie для этого URL — выполнен публичный импорт"
    return result


def _run_source_import_job(job_id: str, values: dict) -> None:
    def on_stage(stage: str, _duration: int, timings: dict[str, int]) -> None:
        progress, label = _SOURCE_STAGE_PROGRESS.get(stage, (1, stage))
        if stage.startswith("capture") and stage != "captureCompile":
            viewport_index = max(1, int(timings.get("captureViewportIndex", 1)))
            viewport_count = max(1, int(timings.get("captureViewportCount", 3)))
            progress = min(68, 30 + round(38 * viewport_index / viewport_count))
            label = stage.removeprefix("capture") + " layers"
        with SOURCE_IMPORT_JOBS_LOCK:
            job = SOURCE_IMPORT_JOBS.get(job_id)
            if job:
                job.update(status="running", progress=progress, stage=stage,
                           stageLabel=label, timingsMs=timings)

    try:
        result = _execute_block_parse(values, on_stage=on_stage)
        with SOURCE_IMPORT_JOBS_LOCK:
            job = SOURCE_IMPORT_JOBS.get(job_id)
            if job:
                job.update(status="complete", progress=100, stage="complete",
                           stageLabel="Готово", result=result,
                           timingsMs=(result.get("diagnostics") or {}).get("timingsMs", {}))
    except Exception as exc:
        traceback.print_exc()
        with SOURCE_IMPORT_JOBS_LOCK:
            job = SOURCE_IMPORT_JOBS.get(job_id)
            if job:
                job.update(status="error", stage="error", stageLabel="Ошибка",
                           error=str(exc)[:500])


@app.post("/api/block-parse")
def block_parse(req: BlockParseReq):
    """BlockParse: детекция блоков страницы + clone каждого в editable Design IR."""
    url = req.url.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    try:
        validate_public_url(url)  # SSRF-гард (422, а не 502)
    except ValueError as e:
        return err(422, str(e))

    values = {
        "url": url,
        "blocks": copy.deepcopy(req.blocks),
        "viewports": copy.deepcopy(req.viewports),
        "authCookies": copy.deepcopy(req.authCookies),
        "authSessionFallback": req.authSessionFallback,
        "fullResolutionEvidence": req.fullResolutionEvidence,
    }
    if req.asyncJob:
        job_id = uuid.uuid4().hex
        job = {
            "jobId": job_id,
            "status": "queued",
            "progress": 1,
            "stage": "queued",
            "stageLabel": "В очереди",
            "timingsMs": {},
        }
        with SOURCE_IMPORT_JOBS_LOCK:
            # Keep bounded diagnostics; completed payloads can be large.
            completed = [key for key, value in SOURCE_IMPORT_JOBS.items()
                         if value.get("status") in {"complete", "error"}]
            for stale_id in completed[:-9]:
                SOURCE_IMPORT_JOBS.pop(stale_id, None)
            SOURCE_IMPORT_JOBS[job_id] = job
        SOURCE_IMPORT_EXECUTOR.submit(_run_source_import_job, job_id, values)
        return job

    try:
        return _execute_block_parse(values)
    except ValueError as e:  # кривой список блоков
        return err(422, str(e))
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка block-parse: {e}")


@app.get("/api/block-parse/job/{job_id}")
def block_parse_job(job_id: str):
    with SOURCE_IMPORT_JOBS_LOCK:
        job = SOURCE_IMPORT_JOBS.get(job_id)
        if not job:
            return err(404, "Source Import job не найден.")
        # Завершённый job больше не мутирует, а его результат — мегабайты
        # артефакта: deepcopy под глобальным локом на каждом финальном полле
        # был заметной паузой. Копируем только живые (маленькие) записи.
        if job.get("status") in {"complete", "error"}:
            return job
        return copy.deepcopy(job)


@app.post("/api/block-parse/refine")
def block_parse_refine(req: BlockParseRefineReq):
    """Применить AI-уточнения к уже разобранным блокам.

    Разрешены только переименования и смена роли блока (см.
    blockparse.apply_refinements): геометрия и IR не меняются, поэтому
    fidelity-гейт нельзя обойти через этот маршрут. Артефакт пересобирается
    из обновлённых блоков, чтобы UI Kit увидел новые имена и роли.
    """
    if not isinstance(req.blocks, list) or not req.blocks:
        return err(422, "Нет блоков для уточнения.")
    import scraper
    try:
        blocks, applied = blockparse.apply_refinements(
            copy.deepcopy(req.blocks), req.operations)
        blocks = scraper.canonicalize_source_blocks(
            blocks, stage="source-refine-apply", include_evidence=True)
    except scraper.CanonicalRasterAssetError as exc:
        status = 503 if exc.detail["retryable"] else 422
        return JSONResponse({"error": str(exc), "status": status, **exc.detail}, status_code=status)
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка уточнения: {e}")
    tokens = None
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("ir"), dict):
            tokens = block["ir"].get("tokens")
            if tokens:
                break
    source = req.source or {}
    final_url = next((b.get("finalUrl") for b in blocks
                      if isinstance(b, dict) and isinstance(b.get("finalUrl"), str)
                      and b["finalUrl"]), "")
    source_url = source.get("url") if isinstance(source.get("url"), str) else ""
    artifact = blockparse._build_source_artifact(
        source_url or final_url, blocks, tokens, source.get("authenticated") is True)
    # Refinement changes labels, not capture provenance or compiler identity.
    if isinstance(source.get("pipelineVersion"), str) and source["pipelineVersion"]:
        artifact["source"]["pipelineVersion"] = source["pipelineVersion"]
    return {"ok": True, "blocks": blocks, "sourceArtifact": artifact,
            "applied": applied, "appliedCount": len(applied)}


def _block_gate_passed(block: dict) -> bool:
    """Прошёл ли блок fidelity-гейт по последнему отчёту harness."""
    report = block.get("fidelityReport") if isinstance(block.get("fidelityReport"), dict) else {}
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    return gate.get("passed") is True


def _refresh_block_fidelity(block: dict, page) -> bool:
    """Перемерить блок тем же harness после принятой AI-починки.

    Собираем запись захвата обратно: публичный блок несёт IR, эталоны и
    размеры, а измеренные на живой странице листовые кадры и потери лежат в
    кэше улик (blockparse._stash_repair_evidence). Нет улик — перезамера не
    делаем: мерить bbox без листовых кадров значило бы ослабить гейт.
    """
    import blockparse
    import cache_store
    import fidelity_harness

    evidence = cache_store.get("repair_evidence", str(block.get("evidenceKey") or ""))
    if not isinstance(evidence, dict) or not evidence.get("leafBoxesByViewport"):
        return False
    item = {
        "ir": block.get("ir"),
        "previews": block.get("previews") or {},
        "sizes": block.get("sizes") or {},
        "paint_coverage": evidence.get("paintCoverage") or {},
        "leaf_boxes_by_viewport": evidence.get("leafBoxesByViewport") or {},
        "dropped_by_viewport": evidence.get("droppedByViewport") or {},
        "extras_by_viewport": evidence.get("extrasByViewport") or {},
    }
    if evidence.get("provenance"):
        item["provenance"] = evidence["provenance"]
    try:
        report = fidelity_harness.evaluate_capture_item(item, page)
    except Exception:
        traceback.print_exc()
        return False
    block["fidelityReport"] = blockparse._public_fidelity_report(report)
    viewport_metrics = report.get("viewports") or {}
    for field, metric in (("fidelity", "pixel_similarity"),
                          ("paintCoverage", "paint_coverage"),
                          ("p95LayoutError", "bbox_p95")):
        block[field] = {
            name: metrics.get(metric)
            for name, metrics in viewport_metrics.items()
            if isinstance(metrics, dict) and metrics.get(metric) is not None
        }
    return True


@app.post("/api/block-parse/repair")
def block_parse_repair(req: FidelityRepairReq):
    """AI-починка расхождений захвата с детерминированным судьёй.

    prepareOnly → задания диагностики (худшие регионы + узлы в них) для
    выбранного пользователем провайдера. С rawOutputs сервер валидирует
    предложения, применяет каждое к копии IR, ПЕРЕМЕРЯЕТ сходство тем же
    harness и оставляет только те, что реально улучшили картинку.
    """
    import fidelity_repair
    import scraper

    blocks = [b for b in (req.blocks or [])
              if isinstance(b, dict) and isinstance(b.get("ir"), dict) and not b.get("error")]
    if not blocks:
        return err(422, "Нет разобранных блоков для починки.")
    try:
        # Repair requests may contain desktop-expanded assets. Canonical state
        # must be restored before measurement and before returning to Source.
        blocks = scraper.canonicalize_source_blocks(
            blocks, stage="source-repair-input", include_evidence=not req.prepareOnly)
    except scraper.CanonicalRasterAssetError as exc:
        status = 503 if exc.detail["retryable"] else 422
        return JSONResponse({"error": str(exc), "status": status, **exc.detail}, status_code=status)
    viewport = str(req.viewport or "desktop")

    def viewport_report(block: dict) -> dict:
        """Метрики viewport для починки: публичный отчёт + карта расхождений.

        region_diffs намеренно нет в ответе /api/block-parse (сетка 8×8 на
        каждый компонент раздувала полезную нагрузку), поэтому единственная
        нужная починке карта берётся из кэша улик по ключу блока.
        """
        import cache_store

        report = block.get("fidelityReport") if isinstance(block.get("fidelityReport"), dict) else {}
        viewports = report.get("viewports") if isinstance(report.get("viewports"), dict) else {}
        metrics = viewports.get(viewport) if isinstance(viewports.get(viewport), dict) else {}
        if metrics.get("region_diffs"):
            return metrics
        evidence = cache_store.get("repair_evidence", str(block.get("evidenceKey") or ""))
        regions = ((evidence or {}).get("regionDiffsByViewport") or {}).get(viewport)
        return {**metrics, "region_diffs": regions} if regions else metrics

    if req.prepareOnly:
        tasks = []
        for index, block in enumerate(blocks):
            if _block_gate_passed(block):
                continue  # прошедший гейт блок чинить нечего
            metrics = viewport_report(block)
            for rect in fidelity_repair.region_rects(metrics, limit=max(1, min(6, req.maxRegions))):
                nodes = fidelity_repair.nodes_in_region(block["ir"], rect)
                if not nodes:
                    continue
                tasks.append({
                    "blockIndex": index,
                    "block": block.get("name"),
                    "region": rect,
                    "messages": fidelity_repair.build_repair_prompt(
                        str(block.get("name") or f"block-{index}"), viewport, rect, nodes, metrics),
                })
        return {"tasks": tasks, "viewport": viewport}

    try:
        import fidelity_harness
        import scraper
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - окружение без Playwright
        return err(502, f"Harness недоступен: {exc}")

    outputs: dict[int, list[str]] = {}
    for item in req.rawOutputs or []:
        if isinstance(item, dict) and isinstance(item.get("blockIndex"), int):
            outputs.setdefault(int(item["blockIndex"]), []).append(str(item.get("content") or ""))

    results = []
    try:
        with sync_playwright() as playwright:
            browser = scraper.launch_chromium(playwright)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900},
                                        device_scale_factor=1)
                # Тот же блок сетевых шрифтов, что в evaluate_captures: иначе
                # судья мерит текст в fallback-шрифте и врёт в обе стороны.
                page.route("https://fonts.googleapis.com/**",
                           lambda route: route.abort("blockedbyclient"))
                page.route("https://fonts.gstatic.com/**",
                           lambda route: route.abort("blockedbyclient"))
                for index, block in enumerate(blocks):
                    answers = list(outputs.get(index) or [])
                    if not answers:
                        continue
                    metrics = viewport_report(block)
                    render_block = scraper.source_block_render_copy(block)
                    reference = render_block.get("previews", {}).get(viewport) or render_block.get("preview")
                    size = (block.get("sizes") or {}).get(viewport) or block.get("size") or {}
                    width = int(size.get("width") or 1440)
                    height = int(size.get("height") or 900)
                    if not isinstance(reference, str) or not reference.startswith("data:"):
                        continue
                    reference_png = fidelity_harness._decode_data_url(reference)
                    render_measure = fidelity_repair.make_browser_measurer(
                        page, reference_png, viewport, width, height)
                    def measure(candidate):
                        return render_measure(scraper.source_block_render_copy(
                            {"ir": candidate, "name": block.get("name")})["ir"])
                    pending = iter(answers)
                    outcome = fidelity_repair.repair_block(
                        block["ir"], block_name=str(block.get("name") or index),
                        viewport=viewport, report_viewport=metrics,
                        measure=measure,
                        propose=lambda _messages: next(pending, ""),
                        max_regions=max(1, min(6, req.maxRegions)))
                    remeasured = False
                    if outcome.get("ir") and outcome.get("applied"):
                        block["ir"] = scraper.canonicalize_ir_raster_assets(
                            outcome["ir"], stage="source-repair-apply",
                            component=str(block.get("name") or index), path=f"blocks[{index}].ir")
                        # Статус обязан догнать IR: без перезамера правка живёт
                        # в дереве, а гейт продолжает судить по отчёту, снятому
                        # до починки, и компонент навсегда «нужна проверка».
                        # The harness itself resolves canonical IR; only its
                        # screenshot evidence needs expansion here.
                        evidence_block = scraper.source_block_render_copy(block)
                        evidence_block["ir"] = block["ir"]
                        remeasured = _refresh_block_fidelity(evidence_block, page)
                        for field in ("fidelityReport", "fidelity", "paintCoverage", "p95LayoutError"):
                            if field in evidence_block:
                                block[field] = evidence_block[field]
                    results.append({
                        "blockIndex": index, "block": block.get("name"),
                        "baseline": outcome.get("baseline"), "similarity": outcome.get("similarity"),
                        "gain": outcome.get("gain"),
                        "appliedCount": len(outcome.get("applied") or []),
                        "rejectedCount": len(outcome.get("rejected") or []),
                        "applied": outcome.get("applied") or [],
                        "remeasured": remeasured,
                        "gatePassed": _block_gate_passed(block),
                    })
            finally:
                browser.close()
        blocks = scraper.canonicalize_source_blocks(
            blocks, stage="source-repair-apply", include_evidence=True)
    except scraper.CanonicalRasterAssetError as exc:
        status = 503 if exc.detail["retryable"] else 422
        return JSONResponse({"error": str(exc), "status": status, **exc.detail}, status_code=status)
    except Exception as exc:
        traceback.print_exc()
        return err(502, f"Ошибка починки: {exc}")

    return {"ok": True, "viewport": viewport, "blocks": blocks, "results": results,
            "gatePassed": all(_block_gate_passed(block) for block in blocks),
            "totalGain": round(sum(float(r.get("gain") or 0) for r in results), 2)}


_IMAGE_STYLE_HINTS = {
    "vector": "Flat vector illustration: clean shapes, layered gradients, one consistent light direction, no text unless the prompt asks for it.",
    "texture": "Seamless material texture: build it from <pattern> and <filter> noise (feTurbulence, feDisplacementMap, feDiffuseLighting), subtle lighting, fill the whole canvas edge to edge.",
    "icon": "Single icon on a transparent background: bold silhouette, consistent 2px strokes, centered with 8% padding.",
}


def _extract_svg(raw: str) -> str | None:
    match = re.search(r"<svg[\s\S]*?</svg>", raw or "", re.IGNORECASE)
    return match.group(0) if match else None


def _sanitize_svg(svg: str) -> str:
    """Parse XML, allow static SVG only, and never execute returned markup."""
    import xml.etree.ElementTree as ET
    if len(svg.encode("utf-8")) > 100_000 or re.search(r"<!DOCTYPE|<!ENTITY", svg, re.I):
        raise ValueError("SVG слишком большой или содержит запрещённые объявления")
    root = ET.fromstring(svg)
    local = lambda name: name.rsplit("}", 1)[-1]
    allowed = set("svg g defs title desc path rect circle ellipse line polyline polygon text tspan linearGradient radialGradient stop pattern filter clipPath mask use feTurbulence feDisplacementMap feGaussianBlur feColorMatrix feComposite feDiffuseLighting feSpecularLighting feDistantLight fePointLight feSpotLight feBlend feFlood feMerge feMergeNode feOffset feMorphology feComponentTransfer feFuncR feFuncG feFuncB feFuncA".split())
    if local(root.tag) != "svg":
        raise ValueError("Ожидался SVG")
    for parent in root.iter():
        for child in list(parent):
            if local(child.tag) not in allowed or ("}" in child.tag and not child.tag.startswith("{http://www.w3.org/2000/svg}")):
                parent.remove(child)
        for name, value in list(parent.attrib.items()):
            key = local(name).lower()
            if key.startswith("on") or (key == "href" and not value.startswith("#")) or key == "style":
                del parent.attrib[name]
            elif re.search(r"url\((?!['\"]?#)[^)]*\)", value, re.I):
                del parent.attrib[name]
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="unicode")


@app.post("/api/image/convert")
def image_convert(req: ImageConvertReq):
    from image_output import convert_image
    try:
        return convert_image(req.image, req.outputFormat, req.requireTransparency)
    except ValueError as exc:
        return err(422, str(exc))


@app.post("/api/image/remove-background")
def image_remove_background(req: ImageMaskReq):
    from image_output import apply_background_mask
    try:
        return apply_background_mask(req.image, req.mask)
    except ValueError as exc:
        return err(422, str(exc))


@app.post("/api/image/generate")
def image_generate(req: ImageGenReq):
    """«Изображение»: подписочная модель (Codex / Claude) пишет самодостаточный
    SVG по промпту, сервер санитизирует его и рендерит PNG через Playwright.
    prepareOnly → промпт для аккаунта десктопа; rawOutput → ответ модели."""
    prompt = (req.prompt or "").strip()
    if not prompt:
        return err(422, "Опишите изображение")
    width = max(64, min(2048, int(req.width or 1024)))
    height = max(64, min(2048, int(req.height or 1024)))
    style = req.style if req.style in _IMAGE_STYLE_HINTS else "vector"
    system = (
        "You are a senior graphics engineer who draws with SVG only. Return exactly one self-contained "
        "<svg> document and nothing else: no markdown, no explanations, no code fences.\n"
        f"Canvas: width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\". Fill the whole canvas.\n"
        "Allowed: shapes, paths, linear/radial gradients, <pattern>, <filter> (feTurbulence, feDisplacementMap, "
        "feGaussianBlur, feColorMatrix, feComposite, feDiffuseLighting, feSpecularLighting), <clipPath>, <mask>, transforms. "
        "Forbidden: <script>, <foreignObject>, <image>, external hrefs, web fonts. Keep the document under 40 KB.\n"
        f"Style: {_IMAGE_STYLE_HINTS[style]}"
        + ("\nTileable: the result must tile seamlessly. Build it from a <pattern> that repeats at least twice per axis "
           "or make every edge continue exactly into the opposite edge. No vignette, no centered hero object." if req.tileable else "")
    )
    reference = (req.referenceImage or "").strip()
    if reference and (not reference.startswith("data:image/") or len(reference) > 8_000_000):
        return err(422, "Референс должен быть изображением (data:image/…) до 6 МБ")
    if reference:
        user_content = [
            {"type": "text", "text": prompt + "\n\nA reference image is attached. Reproduce its palette, materials, "
                                        "motif, proportions and level of detail in SVG; do not describe it, draw it."},
            {"type": "image_url", "image_url": {"url": reference, "detail": "high"}},
        ]
    else:
        user_content = prompt
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
    if req.prepareOnly:
        return {"prompts": [{"messages": messages}]}
    provider = req.provider if req.provider in ("astra", "codex", "claude") else "openai"
    effort = req.effort if req.effort in ("medium", "high", "max") else "medium"
    try:
        raw = req.rawOutput if req.rawOutput is not None else llm.chat(
            provider, messages, 0.8, role="graphics", reasoning_effort=effort, model=req.model)
    except Exception as e:
        return err(502, str(e))
    svg = _extract_svg(raw)
    if not svg:
        return err(502, "Модель не вернула SVG — попробуйте переформулировать промпт")
    try:
        svg = _sanitize_svg(svg)
        png = render_svg_png(svg, width, height)
    except Exception as e:
        return err(502, f"Не удалось отрисовать SVG: {e}")
    return {"svg": svg, "png": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            "width": width, "height": height}


@app.post("/api/reskin")
def reskin(req: ReskinReq):
    """Reskin: AI-рестайл блока с локом структуры.

    LLM (Sol по ключу или консольный аккаунт Codex/Claude) → детерминированный merge-back
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

    ds_context = None
    ds_compiled = None
    ds_usage_mode = ""
    if isinstance(req.designSystem, dict) and req.designSystem.get("systemId"):
        from design_system import resolver as ds_resolver, store as ds_store
        ds_doc, ds_error = ds_store.resolve_ref(req.designSystem)
        if ds_error:
            return err(422, f"Design System: {ds_error}")
        ds_usage_mode = str(req.designSystem.get("usageMode") or "strict")
        ds_context = ds_resolver.resolve_context(
            ds_doc, req.prompt, usage_mode=ds_usage_mode)
        ds_compiled = ds_resolver.compiled_context(
            ds_context, brief=req.prompt,
            archetype_id=str(req.designSystem.get("archetypeId") or ""),
            token_budget=int(req.designSystem.get("tokenBudget") or (24_000 if ds_usage_mode == "strict" else 1000)),
        )
        if ds_usage_mode == "strict" and not ds_compiled.get("strictReady"):
            return err(422, "Design System Strict: exact master не помещается в выбранный context budget. Переключите режим ДС на Extend/Style-only или отключите ДС для этой ноды (× в строке «ДС» на ноде)")
        user += "\n\n" + ds_compiled["promptBlock"]

    # codex/claude — консольные аккаунты (cli_llm); всё остальное — Sol по ключу
    # или первый доступный CLI, если ключа нет (см. llm_client.chat_envelope).
    provider = req.provider if getattr(req, "provider", None) in ("astra", "codex", "claude") else "openai"
    effort = req.effort if req.effort in ("medium", "high", "max") else "medium"
    reskin_messages = [
        {"role": "system", "content": llm.build_system_prompt("edit")},
        {"role": "user", "content": user},
    ]
    # Desktop executes the prepared prompt through the fixed Sol route.
    if req.prepareOnly:
        return {"prompts": [{"messages": reskin_messages}]}
    try:
        raw = req.rawOutput if req.rawOutput else llm.chat(
            provider, reskin_messages, 0.7, role="reskin", reasoning_effort=effort)
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
    current = ensure_current_ir(merged, source="reskin")
    design_system_report = None
    if ds_context is not None:
        from design_system import resolver as ds_resolver
        design_system_report = ds_resolver.validate_generation(current, ds_context)
        if ds_usage_mode == "strict" and design_system_report["errors"]:
            return err(
                422,
                "Design System Strict отклонил reskin: "
                + "; ".join(item["message"] for item in design_system_report["errors"][:4]),
            )
        current.setdefault("meta", {}).update({
            "designSystemRef": ds_context.get("systemRef"),
            "compiledContextHash": (ds_compiled or {}).get("compiledContextHash"),
            "archetypeId": (ds_compiled or {}).get("archetypeId"),
            "identityScore": (design_system_report.get("identity") or {}).get("score"),
            "identityReport": design_system_report.get("identity"),
        })
    return {"ir": current, "log": journal,
            **({"designSystem": design_system_report} if design_system_report else {})}


# ---------- Quality Gate / Constraints (решение владельца 12.2, бэклог §8) ----------

@app.post("/api/quality/certify")
def quality_certify(request: dict):
    """Create an auditable, fail-closed certificate from completed QA reports."""
    try:
        return certify_from_reports(request)
    except (TypeError, ValueError) as exc:
        return err(422, str(exc))


@app.post("/api/quality-gate")
def quality_gate(req: QualityGateReq):
    """Детерминированный Quality Gate: правила v1 + авто-доводка без LLM.

    passed/violations — по входному IR; fixed_ir/journal — результат solver'а
    (починено только то, что чинится детерминированно: сетка 8px, overflow).
    """
    violations = qualitygate.check(req.ir)
    if req.fix:
        fixed_ir, journal = qualitygate.autofix(req.ir, strict_tokens=req.strictTokens)
    else:
        fixed_ir, journal = copy.deepcopy(req.ir), []
    return {"passed": qualitygate.passed(violations), "violations": violations,
            "fixed_ir": fixed_ir, "journal": journal}


QUALITY_JUDGE_SYSTEM = """Ты — строгий арт-директор и pixel QA-судья DesignAI.
Главное доказательство — приложенный скриншот реально отрендеренного Design IR.
Design IR дан только как карта для адресных путей правок. Не хвали, не додумывай
невидимые свойства и не подменяй визуальную оценку чтением JSON.
Верни только JSON-объект:
{
  "score": 0,
  "verdict": "pass|needs_repair",
  "summary": "краткий вывод",
  "issues": [{"category": "hierarchy|rhythm|density|typography|color|slop|brief", "severity": "critical|major|minor", "path": "путь IR или (root)", "problem": "что не так", "instruction": "как исправить"}],
  "repair_instruction": "единая точная инструкция; пустая строка, если repair не нужен"
}
score — целое 0..100. Следуй приложенной рубрике и учитывай только наблюдаемое."""

COMPONENT_RUBRIC = """## Component mode
This IR is one component/source section, not a complete page. Do not apply page-level
requirements such as a single H1, hero hierarchy, page grid, section count or page density.
Score only readability, spacing/rhythm inside the component, clipping/overlap, and visual
correspondence to the supplied Source master. A pass requires score >= 80."""


def _component_quality_mode(ir: dict) -> bool:
    meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
    tree = ir.get("tree") if isinstance(ir.get("tree"), list) else []
    return bool(meta.get("strictRecovery") or
                (len(tree) == 1 and isinstance(tree[0], dict)
                 and tree[0].get("type") == "source-block"))


def _quality_violations(ir: dict) -> list[dict]:
    violations = qualitygate.check(ir)
    if not _component_quality_mode(ir):
        return violations
    page_rules = {"single-h1", "grid-8", "frame-overflow"}
    return [item for item in violations if item.get("rule") not in page_rules]


def _quality_judge_messages(ir: dict, brief: str, surface: str = "auto") -> list[dict]:
    mode = _component_quality_mode(ir)
    return [
        {"role": "system", "content": QUALITY_JUDGE_SYSTEM + generator_policy.judge_rules(brief, ir, surface)
         + ("\n\n" + COMPONENT_RUBRIC if mode else "")
         + "\nEvidence: Design IR only. Visual, keyboard and performance checks are unknown."},
        {"role": "user", "content": "## Бриф\n" + (brief.strip() or "(не указан)")
         + "\n\n## Design IR\n" + json.dumps(ir, ensure_ascii=False)},
    ]


def _quality_visual_key(ir: dict, brief: str) -> str:
    engine = APP_ROOT / "static" / "flow" / "engine.js"
    try:
        engine_stamp = llm._file_stamp(engine)
    except FileNotFoundError:
        engine_stamp = None  # A concurrent build must not crash cache lookup; render reports missing engine.
    return generator_policy.digest({"ir": ir, "brief": brief, "policy": generator_policy.fingerprint(),
        "engine": engine_stamp, "renderer": llm._file_stamp(APP_ROOT / "ir_render.py")})


def _quality_desktop_messages(ir: dict, brief: str, visual: bool, surface: str = "auto") -> list[dict]:
    if not visual:
        return _quality_judge_messages(ir, brief, surface)
    key = _quality_visual_key(ir, brief)
    evidence = cache_store.get("generator-visual", key)
    if not evidence:
        images = []
        for width in (1440, 390):
            images.extend(_judge_images(render_png(ir, width=width, webfonts=True, viewport="mobile" if width == 390 else "desktop")))
        evidence = {"images": images, "widths": [1440, 390]}
        cache_store.put("generator-visual", key, evidence)
    text = (generator_policy.judge_rules(brief, ir, surface) + "\nFirst group: desktop 1440px. Second group: mobile 390px. "
            "Only these viewports were rendered; keyboard and performance remain unknown.\nBrief: " + brief
            + "\nIR: " + json.dumps(ir, ensure_ascii=False))
    return [{"role": "system", "content": QUALITY_JUDGE_SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": text}]
             + [{"type": "image_url", "image_url": {"url": url}} for url in evidence["images"]]}]


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


def _quality_repair_messages(ir: dict, scorecard: dict, brief: str, surface: str = "auto") -> tuple[list[dict] | None, str | None]:
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
        "не добавляй неупомянутые секции и верни только полный валидный JSON.\n"
        "Ограничения починки: элементы image с imagePrompt — штатные заглушки, их не заменять "
        "«нарисованным интерфейсом» из примитивов и не удалять; во free-раскладке дети не должны "
        "перекрываться и выходить за границы родителя — при сомнении переводи группу в auto-layout "
        "(frame.layout row/column с gap), а не подбирай координаты.\n\n"
        f"## Бриф\n{brief.strip() or '(не указан)'}\n\n"
        f"## Инструкции\n{instructions}\n\n"
        f"## Входной Design IR\n{json.dumps(ir, ensure_ascii=False)}"
    )
    return [
            {"role": "system", "content": llm.build_system_prompt("edit", policy=generator_policy.judge_rules(brief, ir, surface)
             + "\nRepair must preserve all tokens, exact componentRefs, masters and their geometry/styles. "
               "A problem in a locked master is a DS gap; do not change the instance.")},
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


JUDGE_FIRST_SCREEN_H = 900
JUDGE_TILE_H = 1400
JUDGE_MAX_TILES = 4


def _judge_images(screenshot: bytes) -> list[str]:
    """Скриншот страницы → набор изображений для vision-судьи.

    Одна высокая картинка (1440×7000) при даунскейле выглядит как мобильный
    макет с нечитаемым текстом. Отдаём первый экран 1:1 и страницу по частям.
    """
    def data_url(png: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(screenshot))
        width, height = image.size
        out: list[str] = []
        first = image.crop((0, 0, width, min(height, JUDGE_FIRST_SCREEN_H)))
        buf = io.BytesIO(); first.save(buf, format="PNG", optimize=True); out.append(data_url(buf.getvalue()))
        if height > JUDGE_FIRST_SCREEN_H:
            tile_h = max(JUDGE_TILE_H, -(-height // JUDGE_MAX_TILES))  # не больше JUDGE_MAX_TILES плиток
            for top in range(0, height, tile_h):
                tile = image.crop((0, top, width, min(height, top + tile_h)))
                scale = min(1, 1024 / width)
                tile = tile.resize((min(width, 1024), max(1, round(tile.height * scale))))
                buf = io.BytesIO(); tile.save(buf, format="PNG", optimize=True); out.append(data_url(buf.getvalue()))
        return out
    except Exception:  # noqa: BLE001 — без PIL/на битом PNG отдаём как есть
        return [data_url(screenshot)]


def _quality_scorecard(ir: dict, brief: str, run_id: str | None = None, *, provider: str = "auto", effort: str = "medium", surface: str = "auto") -> dict:
    """Render IR and ask the standalone server's vision model for a scorecard."""
    run_registry.stage(run_id, "render", "Рендерю IR для визуальной проверки")
    screenshot = render_png(ir, width=1440, webfonts=True)
    image_data_url = _judge_images(screenshot)
    mobile_screenshot = render_png(ir, width=390, webfonts=True, viewport="mobile")
    image_data_url.extend(_judge_images(mobile_screenshot))
    rubric = (APP_ROOT / "prompts" / "RUBRIC.md").read_text(encoding="utf-8")
    component_mode = _component_quality_mode(ir)
    if component_mode:
        rubric = COMPONENT_RUBRIC
    rubric += generator_policy.judge_rules(brief, ir, surface)
    rules_block = project_rules.prompt_block("judge")
    if rules_block:
        rubric += "\n\n" + rules_block
    prompt = (
        rubric
        + "\n\n## Изображения\nПервое — первый экран 1440×900 в масштабе 1:1 (десктоп); "
          "следующие — вся страница по частям сверху вниз, уменьшены до 1024px по ширине. "
          "Последняя группа изображений — мобильный рендер шириной 390px. "
          "Оцени отдельно desktop и mobile; остальные viewport и интерактивное поведение не проверены."
        + "\n\n## Бриф\n" + (brief.strip() or "(не указан)")
        + "\n\n## Карта Design IR для адресных правок\n"
        + json.dumps(ir, ensure_ascii=False)
    )
    run_registry.stage(run_id, "judge", "Vision-судья оценивает скриншот")
    raw = llm.chat_vision(
        provider, image_data_url, prompt, QUALITY_JUDGE_SYSTEM, 0.2,
        role="quality_judge", reasoning_effort=effort,
    )
    scorecard = _parse_quality_scorecard(raw, "LLM vision / quality_judge")
    scorecard["mode"] = "component" if component_mode else "page"
    scorecard["evidence"] = {"visual": True, "widths": [1440, 390], "keyboard": "unknown", "performance": "unknown"}
    return scorecard


def _quality_finish(req, output_ir, initial, final, repair, *, visual=False):
    """Shared acceptance for server and desktop, independent of the judge's claims."""
    surface = generator_policy.surface_for(req.brief, req.surface, req.ir)
    before = generator_policy.lint(req.ir, surface)
    if repair["applied"]:
        failure = generator_policy.repair_guard(req.ir, output_ir, surface, req.designSystem, brief=req.brief)
        old_issues = {(i.get("category"), i.get("path"), i.get("problem")) for i in initial.get("issues", [])}
        new_issues = [i for i in final.get("issues", [])
                      if (i.get("category"), i.get("path"), i.get("problem")) not in old_issues]
        if not req.rejudge or final is initial:
            failure = failure or "Починка не прошла повторную оценку"
        if final.get("score", 0) < initial.get("score", 0) or new_issues:
            failure = failure or "Повторная оценка выявила регрессию; починка отменена"
        if failure:
            output_ir, final = copy.deepcopy(req.ir), initial
            repair.update(applied=False, error=failure)
    after = generator_policy.lint(output_ir, surface)
    ds_check = None
    if req.designSystem:
        from design_system import resolver, store
        document, error = store.resolve_ref(req.designSystem)
        if error:
            ds_check = {"errors": [{"message": str(error)}]}
        else:
            ds_check = resolver.validate_generation(output_ir, resolver.resolve_context(
                document, req.brief, usage_mode=req.designSystem.get("usageMode") or "strict"))
    important = any(i.get("severity") in {"critical", "major"} for i in final.get("issues", []))
    min_score = max(0, min(int(req.min_score), 100))
    passed = (final["score"] >= min_score and final["verdict"] == "pass" and not important
              and qualitygate.passed(after) and not (ds_check or {}).get("errors")
              and not repair.get("error"))
    return {"ir": output_ir, "passed": bool(passed), "min_score": min_score,
            "scorecard": final, "initial_scorecard": initial,
            "deterministic": {"before": before, "after": after}, "repair": repair,
            "designSystem": ds_check,
            "acceptance": generator_policy.report(passed=bool(passed), visual=visual,
                                                   surface=surface, ds_check=ds_check)}


def _quality_repair(ir: dict, scorecard: dict, brief: str, *, provider: str = "auto", effort: str = "medium", surface: str = "auto") -> tuple[dict | None, str | None]:
    """Серверный LLM-путь standalone веб-сервера (Sol по ключу или Codex/Claude CLI)."""
    messages, error = _quality_repair_messages(ir, scorecard, brief, surface)
    if messages is None:
        return None, error
    try:
        raw = llm.chat(provider, messages, 0.25, role="quality_repair", reasoning_effort=effort)
    except Exception as e:
        return None, str(e)
    return _parse_quality_repair(raw)


@app.post("/api/quality-pass")
def quality_pass(req: QualityPassReq):
    """Обёртка run_registry: стадии judge → repair → rejudge и кооперативная отмена."""
    run_id = run_registry.start(req.runId, "quality-pass")
    resp = None
    try:
        resp = _quality_pass(req, run_id)
        return resp
    finally:
        _finish_run(run_id, resp)


def _quality_pass(req: QualityPassReq, run_id: str | None):
    """Премиальный контур: детерминированные правила → независимый judge → repair → rejudge.

    API всегда возвращает исходный валидный IR, если repair не удался: результат
    контролируем и не подменяем граф битым ответом модели.
    """
    schema_errors = validate_ir(sanitize_font_face_weights(req.ir))
    if schema_errors:
        return err(422, "IR не проходит schema: " + "; ".join(schema_errors[:5]))
    deterministic_before = generator_policy.lint(req.ir, generator_policy.surface_for(req.brief, req.surface, req.ir))
    try:
        initial = _quality_scorecard(req.ir, req.brief, run_id, provider=req.provider, effort=req.effort, surface=req.surface)
    except Exception as e:
        return err(502, f"Quality Pass judge недоступен: {e}")
    if run_registry.is_cancelled(run_id):
        return err(CANCELLED_STATUS, "Quality Pass отменён")
    min_score = max(0, min(int(req.min_score), 100))
    important = any(i["severity"] in {"critical", "major"} for i in initial["issues"])
    needs_repair = bool(deterministic_before) or important or initial["score"] < min_score
    output_ir = copy.deepcopy(req.ir)
    repair = {"attempted": False, "applied": False, "error": None}
    final = initial
    if req.repair and needs_repair:
        repair["attempted"] = True
        run_registry.stage(run_id, "repair", "Починка по замечаниям судьи")
        repaired, repair_error = _quality_repair(req.ir, initial, req.brief, provider=req.provider, effort=req.effort, surface=req.surface)
        if repaired is None:
            repair["error"] = repair_error
        else:
            output_ir = repaired
            repair["applied"] = True
            if req.rejudge:
                if run_registry.is_cancelled(run_id):
                    return err(CANCELLED_STATUS, "Quality Pass отменён")
                run_registry.stage(run_id, "rejudge", "Повторная оценка")
                try:
                    final = _quality_scorecard(output_ir, req.brief, run_id, provider=req.provider, effort=req.effort, surface=req.surface)
                except Exception as e:
                    repair["error"] = f"rejudge недоступен: {e}"
    return _quality_finish(req, output_ir, initial, final, repair, visual=True)


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

    deterministic_before = generator_policy.lint(req.ir, generator_policy.surface_for(req.brief, req.surface, req.ir))
    if outputs.judge is None:
        return {"pending": {
            "stage": "judge",
            "profile": "quality_judge",
            "messages": _quality_desktop_messages(req.ir, req.brief, req.visualReview, req.surface),
        }}
    try:
        initial = _parse_quality_scorecard(outputs.judge, "Codex app-server / quality_judge")
        initial["mode"] = "component" if _component_quality_mode(req.ir) else "page"
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
        messages, message_error = _quality_repair_messages(req.ir, initial, req.brief, req.surface)
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
                            "messages": _quality_desktop_messages(output_ir, req.brief, req.visualReview, req.surface),
                        }}
                    try:
                        final = _parse_quality_scorecard(
                            outputs.rejudge, "Codex app-server / quality_judge"
                        )
                        final["mode"] = "component" if _component_quality_mode(output_ir) else "page"
                    except Exception as e:
                        return err(502, f"Quality Pass rejudge вернул неверный ответ: {e}")

    if outputs.rejudge is not None and not repair["applied"]:
        return err(422, "Quality Pass: rejudge без применённого repair — неконсистентное состояние Codex")
    visual = bool(req.visualReview and cache_store.get("generator-visual", _quality_visual_key(output_ir, req.brief)))
    return _quality_finish(req, output_ir, initial, final, repair, visual=visual)


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


@app.post("/api/reproduce")
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


@app.post("/api/reproduce/segment")
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
    import blockparse
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


@app.get("/api/cache/stats")
def cache_stats():
    """Наблюдаемость кэша: сколько LLM-вызовов сэкономлено повторами."""
    return cache_store.stats()


@app.post("/api/project/save")
def project_save(req: ProjectSaveReq):
    if req.expectedRevision:
        result = project_store.commit_project(
            req.project,
            req.expectedRevision,
            user_id=req.user_id,
            project_id=req.project_id,
        )
        if result.get("stale"):
            return JSONResponse(result, status_code=409)
        return result
    return project_store.save_project(req.project, req.user_id, req.project_id)


@app.post("/api/project/load")
def project_load(req: ProjectLoadReq):
    record = project_store.inspect_project(req.user_id, req.project_id)
    if record.get("status") == "corrupt":
        return {"project": None, "updated_at": None, "revision": None}
    if record.get("status") != "ok":
        # пустой проект — валидная CAS-цель: commit с EMPTY_REVISION создаст строку
        return {"project": None, "updated_at": None, "revision": project_store.EMPTY_REVISION}
    return {
        "project": record["payload"],
        "updated_at": record["updated_at"],
        "revision": record["revision"],
    }


@app.get("/api/runs/{run_id}")
def run_status(run_id: str):
    """Стадия длинного запуска (generate/quality-pass) — клиент поллит параллельно POST."""
    run = run_registry.get(run_id)
    if not run:
        return err(404, "Запуск не найден")
    return run


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    """Push run stage changes to browser clients; polling remains a client fallback."""
    async def events():
        revision = 0
        empty_waits = 0
        while True:
            run = await asyncio.to_thread(run_registry.wait_for_update, run_id, revision, 15.0)
            if run is None:
                empty_waits += 1
                yield ": keep-alive\n\n"
                if revision == 0 and empty_waits >= 2:
                    break
                continue
            empty_waits = 0
            revision = int(run.get("revision") or revision)
            payload = json.dumps(run, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {revision}\ndata: {payload}\n\n"
            if run.get("status") in {"complete", "error", "cancelled"}:
                break

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/cancel")
def run_cancel(run_id: str):
    """Кооперативная отмена: хендлер прервётся на следующей проверке между стадиями."""
    return {"cancelled": run_registry.cancel(run_id), "runId": run_id}


@app.get("/api/project/taste")
def project_taste():
    return project_store.load_taste_profile()


@app.post("/api/project/taste/outcome")
def project_taste_outcome(req: TasteOutcomeReq):
    try:
        return project_store.record_taste_outcome(
            req.kind, req.payload, user_id=req.user_id, project_id=req.project_id)
    except ValueError as exc:
        return err(422, str(exc))


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
        # Чем отвечает сервер без десктопа: ключ OpenAI или консольный аккаунт
        "providers": {
            "openaiKey": bool(os.environ.get("OPENAI_API_KEY")),
            "codexCli": cli_llm.available("codex"),
            "claudeCli": cli_llm.available("claude"),
            "default": "openai" if os.environ.get("OPENAI_API_KEY") else (cli_llm.default_provider() or None),
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
    version = str(req.motion.get("version") or "")
    errors = validate_motion_v2(req.motion) if version == "2.0" else ir.validate_motion(req.motion, req.interaction)
    return {"valid": not errors, "version": version or "1.0", "errors": errors}


@app.post("/api/motion/migrate-v2")
def motion_migrate_v2(req: MotionMigrateV2Req):
    """Explicit, fail-closed migration; source linkage may never be inferred."""
    try:
        motion = migrate_motion_v1_to_v2(req.motion, req.project_revision, req.source_mapping)
    except ValueError as exc:
        return err(422, str(exc))
    return {"motion": motion, "errors": []}


def _materialize_motion_scenes(base_ir: dict, interaction: dict, motion: dict) -> list[dict]:
    scene_irs = []
    for scene in motion["scenes"]:
        scene_ir = ir.replay_interaction(base_ir, interaction, scene["interactionSceneId"])
        replay_errors = validate_ir(scene_ir)
        if replay_errors:
            raise ValueError("Motion scene produced invalid IR: " + "; ".join(replay_errors[:5]))
        scene_irs.append({"sceneId": scene["id"], "ir": ensure_current_ir(scene_ir)})
    return scene_irs


def _run_motion_render(render_id: str, motion: dict, scene_irs: list[dict], output: Path, layers: list[dict] | None = None) -> None:
    def progress(done: int, total: int) -> None:
        with RENDER_JOBS_LOCK:
            job = RENDER_JOBS.get(render_id)
            if job:
                job.update(status="rendering", progress=round(done * 100 / total), framesDone=done)

    try:
        with RENDER_JOBS_LOCK:
            RENDER_JOBS[render_id].update(status="rendering", progress=0)
        result = render_video(motion, scene_irs, output, progress, composition_layers=layers) if layers is not None else render_video(motion, scene_irs, output, progress)
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
        layers = None
        if req.layers is not None:
            validate_composition_layers(req.layers, req.motion)
            layers = prepare_composition_layers(req.layers)
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
    RENDER_EXECUTOR.submit(_run_motion_render, render_id, copy.deepcopy(req.motion), scene_irs, output, layers)
    return {key: value for key, value in RENDER_JOBS[render_id].items() if key != "output"}


def _completed_render_on_disk(render_id: str) -> Path | None:
    """RENDER_JOBS живёт в памяти процесса, а артефакты — на диске. После
    рестарта сервера сохранённые в проекте downloadUrl не должны ломаться."""
    if not re.fullmatch(r"[0-9a-f]{32}", render_id):
        return None
    for suffix in (".mp4", ".webm"):
        candidate = RENDER_DIR / f"{render_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


@app.get("/api/motion/render/{render_id}")
def motion_render_status(render_id: str):
    with RENDER_JOBS_LOCK:
        job = RENDER_JOBS.get(render_id)
        if job:
            return {key: value for key, value in job.items() if key != "output"}
    output = _completed_render_on_disk(render_id)
    if output is None:
        return err(404, "Render job not found.")
    return {
        "id": render_id,
        "status": "complete",
        "progress": 100,
        "format": output.suffix.lstrip("."),
        "filename": f"designai-motion-{render_id[:8]}{output.suffix}",
        "downloadUrl": f"/api/motion/render/{render_id}/download",
    }


@app.get("/api/motion/render/{render_id}/download")
def motion_render_download(render_id: str):
    output: Path | None = None
    filename = ""
    with RENDER_JOBS_LOCK:
        job = RENDER_JOBS.get(render_id)
        if job:
            if job["status"] != "complete":
                return err(409, "Render is not complete.")
            output = Path(job["output"])
            filename = job["filename"]
    if output is None:
        output = _completed_render_on_disk(render_id)
        if output is None:
            return err(404, "Render job not found.")
        filename = f"designai-motion-{render_id[:8]}{output.suffix}"
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
