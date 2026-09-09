"""Motion IR: сборка сцен, проверка, миграция v2 и детерминированный рендер видео.

Задания рендера живут в памяти процесса (RENDER_JOBS), артефакты — на диске
в <data>/renders, поэтому сохранённые в проекте downloadUrl переживают рестарт.
"""
from __future__ import annotations

import concurrent.futures
import copy
import re
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import ir
from ir import ensure_current as ensure_current_ir
from ir.motion_v2 import migrate_motion_v1_to_v2, validate_motion_v2
from config import FEATURE_FLAGS
from motion_render import prepare_composition_layers, render_video, validate_composition_layers, validate_render_input
from api.common import DATA_ROOT, err, validate_ir

router = APIRouter()

RENDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
RENDER_JOBS: dict[str, dict] = {}
RENDER_JOBS_LOCK = threading.Lock()
RENDER_DIR = DATA_ROOT / "renders"


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


@router.post("/api/motion/build")
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


@router.post("/api/motion/validate")
def motion_validate(req: MotionValidateReq):
    version = str(req.motion.get("version") or "")
    errors = validate_motion_v2(req.motion) if version == "2.0" else ir.validate_motion(req.motion, req.interaction)
    return {"valid": not errors, "version": version or "1.0", "errors": errors}


@router.post("/api/motion/migrate-v2")
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


@router.post("/api/motion/render")
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


@router.get("/api/motion/render/{render_id}")
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


@router.get("/api/motion/render/{render_id}/download")
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
