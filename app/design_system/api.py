"""API дизайн-систем: build/publish/list/get/default (ТЗ §7, §14)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import builder, resolver, store

router = APIRouter()


class BuildRequest(BaseModel):
    name: str = ""
    sourceNodeId: str | int = ""
    sourceUrl: str = ""
    blocks: list = Field(default_factory=list)
    tokens: dict = Field(default_factory=dict)
    locale: str = "ru"
    includeGeneratedStates: bool = True
    createMock: bool = True


class DocumentRequest(BaseModel):
    document: dict


class RefRequest(BaseModel):
    systemId: str
    revision: int = 0


class DefaultRequest(BaseModel):
    systemId: str | None = None


def _err(status: int, message: str):
    return {"error": message, "status": status}


@router.post("/api/design-system/build")
def build_design_system(req: BuildRequest):
    """Source-данные → draft (без публикации)."""
    if not any(isinstance(b, dict) and b.get("ir") for b in req.blocks):
        return _err(422, "Source не содержит валидных блоков — запустите импорт заново")
    node_data = {"blocks": req.blocks, "tokens": req.tokens,
                 "mode": "url" if req.sourceUrl else "screenshot", "url": req.sourceUrl}
    pack = builder.build_source_pack(node_data, source_node_id=req.sourceNodeId)
    pack["_raw_blocks"] = req.blocks
    document = builder.build_draft(
        pack, name=req.name or None, locale=req.locale,
        include_generated_states=req.includeGeneratedStates, create_mock=req.createMock)
    store.save_draft(document)
    from .document import summary
    return {"document": document, "summary": summary(document)}


@router.post("/api/design-system/publish")
def publish_design_system(req: DocumentRequest):
    result = store.publish(req.document)
    if not result.get("ok"):
        return {"errors": result.get("errors") or [{"message": "publication failed"}]}
    return {"document": result["document"], "summary": result["summary"], "duplicate": result.get("duplicate", False)}


@router.post("/api/design-system/validate")
def validate_design_system(req: DocumentRequest):
    from .document import validate_document
    return {"errors": validate_document(req.document)}


@router.get("/api/design-system/list")
def list_design_systems():
    return {"systems": store.list_systems(), "defaultSystemRef": store.get_default()}


@router.post("/api/design-system/get")
def get_design_system(req: RefRequest):
    document = store.get_revision(req.systemId, req.revision)
    if not document:
        return _err(404, f"Ревизия {req.systemId}@{req.revision} не найдена")
    return {"document": document}


@router.post("/api/design-system/default")
def set_default_design_system(req: DefaultRequest):
    try:
        return store.set_default(req.systemId)
    except ValueError as exc:
        return _err(404, str(exc))


@router.post("/api/design-system/resolve-context")
def resolve_design_context(req: dict):
    """Диагностический endpoint резолвера (используется также тестами)."""
    ref = (req or {}).get("ref") or {}
    brief = str((req or {}).get("brief") or "")
    usage = str((req or {}).get("usageMode") or "strict")
    document, error = store.resolve_ref(ref)
    if error:
        return _err(422, error)
    context = resolver.resolve_context(document, brief, usage_mode=usage)
    return {"context": context, "promptBlock": resolver.compact_prompt_block(context)}
