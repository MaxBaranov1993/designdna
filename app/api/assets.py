"""Image planning and validated application. Model calls stay in the desktop provider bridge."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal

import asset_plan
import visual_reference
from api.common import err

router = APIRouter()


class AssetPlanReq(BaseModel):
    variants: list[dict] = Field(max_length=8)
    context: dict = Field(default_factory=dict)


class AssetApplyReq(BaseModel):
    ir: dict
    slot: dict
    image: str


class AssetReconcileReq(BaseModel):
    ir: dict
    slots: list[dict]


class ConceptPlanReq(BaseModel):
    brief: str = Field(min_length=1, max_length=12000)
    tokens: dict | None = None
    designSystem: dict | None = None
    referenceNotes: str = Field(default="", max_length=2000)
    referenceRole: Literal["style", "composition"] = "style"


class ConceptImageReq(BaseModel):
    image: str


@router.post("/api/generate/concept/prepare")
def concept_prepare(req: ConceptPlanReq):
    try:
        return {"prompt": visual_reference.concept_prompt(req.brief, req.tokens, req.designSystem, req.referenceNotes, req.referenceRole), "conceptOnly": True}
    except ValueError as exc:
        return err(422, str(exc))


@router.post("/api/generate/concept/store")
def concept_store(req: ConceptImageReq):
    try:
        return {"result": asset_plan.store_image(req.image), "conceptOnly": True}
    except ValueError as exc:
        return err(422, str(exc))


@router.post("/api/generate/assets/prepare")
def asset_prepare(req: AssetPlanReq):
    try:
        return asset_plan.prepare(req.variants, req.context)
    except ValueError as exc:
        return err(422, str(exc))


@router.post("/api/generate/assets/apply")
def asset_apply(req: AssetApplyReq):
    try:
        return asset_plan.apply(req.ir, req.slot, req.image)
    except ValueError as exc:
        return err(409 if "план ресурсов" in str(exc) else 422, str(exc))


@router.post("/api/generate/assets/reconcile")
def asset_reconcile(req: AssetReconcileReq):
    return asset_plan.reconcile(req.ir, req.slots)
