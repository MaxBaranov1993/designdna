"""Сохранение проекта с CAS-ревизией и вкусовой профиль: /api/project/*."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import project_store
from api.common import err

router = APIRouter()


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


@router.post("/api/project/save")
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


@router.post("/api/project/load")
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


@router.get("/api/project/taste")
def project_taste():
    return project_store.load_taste_profile()


@router.post("/api/project/taste/outcome")
def project_taste_outcome(req: TasteOutcomeReq):
    try:
        return project_store.record_taste_outcome(
            req.kind, req.payload, user_id=req.user_id, project_id=req.project_id)
    except ValueError as exc:
        return err(422, str(exc))
