"""API Timeline IR: сборка видео-таймлайна из Design IR и обратимые патчи.

Нода Video Editor работает через этот контракт: сборка детерминированного
таймлайна из входных компонентов, ручные и AI-правки через TimelineChangeSet
(каждый коммит получает автоматические инверсные операции — Undo одним
вызовом /revert). Интерполяция кейфреймов — на стороне движка рендера.
"""
from __future__ import annotations

import copy
import json
import os
import re
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from config import FEATURE_FLAGS
from ir.hash import content_hash
from ir.timeline import (
    PRESET_NAMES,
    apply_change_set,
    build,
    build_change_set,
    revert_change_set,
    validate,
)
from timeline_assets import materialize_render_assets
from timeline_render import (
    JOBS,
    JOBS_LOCK,
    evict_expired_jobs,
    export_css,
    export_waapi,
    register_job,
    request_cancel,
    submit_render,
    validate_timeline_render,
)

router = APIRouter()

_APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
_ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or _APP_ROOT.parent)
TIMELINE_RENDER_DIR = Path(os.environ.get("DESIGNDNA_DATA_DIR") or _ROOT / "data") / "renders"

PRESET_LABELS = {
    "fade-in": "Появление (прозрачность)",
    "fade-in-up": "Появление снизу",
    "zoom-in": "Появление с приближением",
    "zoom-spotlight": "Медленный наезд камеры",
    "pan-down": "Провлёт вниз",
    "cta-pulse": "Пульс акцента",
}


class TimelineBuildRequest(BaseModel):
    ir: dict
    settings: dict = Field(default_factory=dict)
    pages: list[dict] | None = None


class TimelineCommitRequest(BaseModel):
    timeline: dict
    operations: list = Field(default_factory=list)
    intent: str = ""
    actor: str = "timeline-editor"
    scope: list[str] | None = None


class TimelineChangeSetRequest(BaseModel):
    timeline: dict
    changeSet: dict


class TimelineDocumentRequest(BaseModel):
    timeline: dict


class TimelineConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=16000)


class TimelineAssistRequest(BaseModel):
    timeline: dict
    prompt: str
    provider: Literal["openai", "astra", "codex", "claude"] = "openai"
    effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "medium"
    model: str | None = Field(default=None, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    require_llm: bool = False
    conversation: list[TimelineConversationMessage] = Field(default_factory=list, max_length=24)


class TimelineRenderRequest(BaseModel):
    timeline: dict
    ir: dict
    format: str = "mp4"


class TimelineExportRequest(BaseModel):
    timeline: dict
    mode: str = "css"


def _err(status: int, message: str):
    return JSONResponse(status_code=status, content={"error": message, "status": status})


def _guard():
    if not FEATURE_FLAGS.is_enabled("videoEditor"):
        return _err(403, "Video Editor выключен флагом DESIGNAI_FLAG_VIDEOEDITOR")
    return None


@router.post("/api/timeline/build")
def timeline_build(req: TimelineBuildRequest):
    blocked = _guard()
    if blocked:
        return blocked
    if not isinstance(req.ir, dict) or not isinstance(req.ir.get("tree"), list) or not req.ir.get("tree"):
        return _err(422, "Нужен Design IR с непустым деревом")
    try:
        if req.pages:
            from video_story import build_pages
            document = build_pages(req.pages, req.settings)
        else:
            document = build(req.ir, req.settings)
    except ValueError as e:
        return _err(422, str(e))
    return {"timeline": document}


@router.post("/api/timeline/commit")
def timeline_commit(req: TimelineCommitRequest):
    """Собрать change-set по операциям (с авто-инверсиями) и атомарно применить."""
    blocked = _guard()
    if blocked:
        return blocked
    errors = validate(req.timeline)
    if errors:
        return _err(422, "Таймлайн невалиден до применения: " + "; ".join(errors[:3]))
    if not req.operations:
        return _err(422, "Нет операций для коммита")
    try:
        change_set = build_change_set(
            req.timeline, req.intent or "timeline edit", req.operations,
            actor=req.actor, scope=req.scope)
        applied = apply_change_set(req.timeline, change_set)
    except ValueError as e:
        return _err(422, str(e))
    return {"timeline": applied, "changeSet": change_set}


@router.post("/api/timeline/apply")
def timeline_apply(req: TimelineChangeSetRequest):
    blocked = _guard()
    if blocked:
        return blocked
    try:
        applied = apply_change_set(req.timeline, req.changeSet)
    except ValueError as e:
        return _err(422, str(e))
    return {"timeline": applied}


@router.post("/api/timeline/revert")
def timeline_revert(req: TimelineChangeSetRequest):
    blocked = _guard()
    if blocked:
        return blocked
    try:
        reverted = revert_change_set(req.timeline, req.changeSet)
    except ValueError as e:
        return _err(422, str(e))
    return {"timeline": reverted}


@router.get("/api/timeline/presets")
def timeline_presets():
    return {"presets": [
        {"id": name, "label": PRESET_LABELS.get(name, name)} for name in PRESET_NAMES
    ]}


@router.post("/api/timeline/validate")
def timeline_validate(req: TimelineDocumentRequest):
    return {"errors": validate(req.timeline)}


@router.get("/api/timeline/models")
def timeline_models():
    from video_models import catalogue
    return catalogue()


@router.post("/api/timeline/assist")
def timeline_assist(req: TimelineAssistRequest):
    """ИИ-режиссёр: промпт -> превью обратимого change-set.

    Ответ — это ПРЕВЬЮ (``preview: true``): ``timeline`` собран из копий входа,
    канонический таймлайн ноды не трогается до явного /api/timeline/apply
    пользователем. ``planSource``/``warning`` показывают, какой провайдер собрал
    план и был ли фолбэк с LLM на детерминированный разбор.
    """
    blocked = _guard()
    if blocked:
        return blocked
    errors = validate(req.timeline)
    if errors:
        return _err(422, "Таймлайн невалиден до применения: " + "; ".join(errors[:3]))
    from timeline_director import direct
    try:
        from video_models import validate_selection
        validate_selection(req.provider, req.model, req.effort)
        from video_context import prepare_context
        visual_context = prepare_context(req.timeline) if req.timeline.get("story") and req.require_llm else None
        preview_timeline, change_set, meta = direct(req.timeline, req.prompt, provider=req.provider, effort=req.effort, require_llm=req.require_llm,
            conversation=[message.model_dump() for message in req.conversation], model=req.model, visual_context=visual_context)
    except ValueError as e:
        return _err(422, str(e))
    return {
        "preview": True,
        "timeline": preview_timeline,
        "changeSet": change_set,
        "planSource": meta.get("planSource") or "deterministic",
        "warning": meta.get("warning"),
        "steps": meta.get("steps") or 0,
        "understanding": meta.get("understanding"),
    }


@router.post("/api/timeline/render")
def timeline_render(req: TimelineRenderRequest):
    """Очередь детерминированного локального рендера ролика."""
    blocked = _guard()
    if blocked:
        return blocked
    if not FEATURE_FLAGS.is_enabled("videoRender"):
        return _err(404, "Video render is disabled by feature flag.")
    errors = validate(req.timeline)
    if errors:
        return _err(422, "Таймлайн невалиден: " + "; ".join(errors[:3]))
    expected = ((req.timeline.get("source") or {}).get("designIrHash")) or ""
    if expected and expected != content_hash(req.ir):
        return _err(409, "Таймлайн не принадлежит переданному Design IR")
    # Fail closed на входе: политика + наличие/целостность локальных ассетов
    _assets, asset_errors = materialize_render_assets(req.ir)
    for page in (req.timeline.get("story") or {}).get("pages", []):
        _, page_errors = materialize_render_assets(page["ir"])
        asset_errors.extend(page_errors)
    if asset_errors:
        return _err(422, "Ассеты рендера не прошли проверку: " + "; ".join(asset_errors[:3]))
    try:
        total, _fps = validate_timeline_render(req.timeline, req.ir)
    except ValueError as e:
        return _err(422, str(e))
    output_format = "webm" if str(req.format) == "webm" else "mp4"
    render_id = uuid.uuid4().hex
    output = TIMELINE_RENDER_DIR / f"{render_id}.{output_format}"
    job = register_job(render_id, total, output_format, output)
    if job is None:
        return _err(429, "Очередь рендера заполнена — отмените лишние задачи или дождитесь завершения текущих")
    submit_render(render_id, copy.deepcopy(req.timeline), copy.deepcopy(req.ir), output)
    return {
        "renderId": render_id,
        "status": "queued",
        "framesTotal": total,
        "filename": job.get("filename"),
    }


_STATUS_MAP = {"queued": "queued", "running": "running", "complete": "done",
               "error": "error", "cancelled": "cancelled"}


def _completed_render_on_disk(render_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", render_id):
        return None
    for suffix in (".mp4", ".webm"):
        candidate = TIMELINE_RENDER_DIR / f"{render_id}{suffix}"
        if candidate.is_file() and candidate.resolve().parent == TIMELINE_RENDER_DIR.resolve():
            return candidate
    return None


def _disk_job(render_id: str) -> dict | None:
    output = _completed_render_on_disk(render_id)
    if output is None:
        return None
    return {"status": "complete", "progress": 100, "output": output,
            "filename": f"designdna-timeline-{render_id[:8]}{output.suffix}",
            "result": {"bytes": output.stat().st_size}}


@router.get("/api/timeline/render/{render_id}")
def timeline_render_status(render_id: str):
    evict_expired_jobs()
    with JOBS_LOCK:
        job = JOBS.get(render_id) or _disk_job(render_id)
        if not job:
            return _err(404, "Render job not found.")
        status = _STATUS_MAP.get(str(job.get("status")), "queued")
        response = {
            "renderId": render_id,
            "status": status,
            "progress": job.get("progress") or 0.0,
            "framesDone": job.get("framesDone") or 0,
            "framesTotal": job.get("framesTotal") or 0,
            "filename": job.get("filename"),
        }
        if status == "done":
            response["downloadUrl"] = f"/api/timeline/render/{render_id}/download"
            response["result"] = job.get("result") or {}
        if status in ("error", "cancelled"):
            response["error"] = job.get("error") or f"render {status}"
        return response


@router.post("/api/timeline/render/{render_id}/cancel")
def timeline_render_cancel(render_id: str):
    outcome = request_cancel(render_id)
    if outcome is None:
        return _err(404, "Render job not found.")
    if outcome.startswith("conflict:"):
        return _err(409, f"Render already finished: {outcome.split(':', 1)[1]}.")
    return {"status": outcome, "renderId": render_id}


@router.get("/api/timeline/render/{render_id}/download")
def timeline_render_download(render_id: str):
    evict_expired_jobs()
    with JOBS_LOCK:
        job = JOBS.get(render_id) or _disk_job(render_id)
        if not job:
            return _err(404, "Render job not found.")
        if job.get("status") != "complete":
            return _err(409, "Render is not complete.")
        output = Path(job["output"])
        filename = job["filename"]
    if not output.is_file() or output.parent.resolve() != TIMELINE_RENDER_DIR.resolve():
        return _err(404, "Rendered artifact not found.")
    media_type = "video/mp4" if output.suffix == ".mp4" else "video/webm"
    return FileResponse(output, media_type=media_type, filename=filename)


@router.post("/api/timeline/export")
def timeline_export(req: TimelineExportRequest):
    """Экспорт веб-анимации: CSS @keyframes или рецепт Web Animations API."""
    blocked = _guard()
    if blocked:
        return blocked
    errors = validate(req.timeline)
    if errors:
        return _err(422, "Таймлайн невалиден: " + "; ".join(errors[:3]))
    if (req.timeline.get("story") or {}).get("actions"):
        return _err(422, "Сценарий с действиями экспортируется в MP4 или WebM")
    if req.mode == "waapi":
        recipe = export_waapi(req.timeline)
        return {"files": {"timeline.waapi.json": json.dumps(recipe, ensure_ascii=False, indent=2)}}
    return {"files": {"timeline.css": export_css(req.timeline)}}
