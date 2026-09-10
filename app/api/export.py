"""Local editable presentation export. Source blobs stay content-addressed."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from presentation_export import export_presentation

router = APIRouter()


class PresentationRequest(BaseModel):
    ir: dict
    width: int = Field(default=1280, ge=320, le=4096)
    viewport: str = "desktop"


@router.post("/api/export/pptx")
def presentation_export(req: PresentationRequest):
    try:
        return export_presentation(req.ir, width=req.width, viewport=req.viewport)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
