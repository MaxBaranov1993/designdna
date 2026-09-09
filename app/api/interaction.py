"""Interaction Recorder: сборка, проверка, воспроизведение и захват Interaction IR."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

import ir
from ir import ensure_current as ensure_current_ir
from config import FEATURE_FLAGS
from interaction_capture import capture_live_flow
from api.common import err, validate_ir

router = APIRouter()


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


@router.post("/api/interaction/build")
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


@router.post("/api/interaction/validate")
def interaction_validate(req: InteractionValidateReq):
    errors = ir.validate_interaction(req.interaction)
    return {"valid": not errors, "errors": errors}


@router.post("/api/interaction/replay")
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


@router.post("/api/interaction/capture")
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
