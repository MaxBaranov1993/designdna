"""API Timeline IR: сборка видео-таймлайна из Design IR и обратимые патчи.

Нода Video Editor работает через этот контракт: сборка детерминированного
таймлайна из входных компонентов, ручные и AI-правки через TimelineChangeSet
(каждый коммит получает автоматические инверсные операции — Undo одним
вызовом /revert). Интерполяция кейфреймов — на стороне движка рендера.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import FEATURE_FLAGS
from ir.timeline import (
    PRESET_NAMES,
    apply_change_set,
    build,
    build_change_set,
    revert_change_set,
    validate,
)

router = APIRouter()

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


class TimelineAssistRequest(BaseModel):
    timeline: dict
    prompt: str


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


@router.post("/api/timeline/assist")
def timeline_assist(req: TimelineAssistRequest):
    """ИИ-режиссёр: промпт -> обратимый change-set -> применённый таймлайн."""
    blocked = _guard()
    if blocked:
        return blocked
    errors = validate(req.timeline)
    if errors:
        return _err(422, "Таймлайн невалиден до применения: " + "; ".join(errors[:3]))
    from timeline_director import direct
    try:
        applied, change_set = direct(req.timeline, req.prompt)
    except ValueError as e:
        return _err(422, str(e))
    return {"timeline": applied, "changeSet": change_set}
