"""API дизайн-систем: build/publish/list/get/default (ТЗ §7, §14)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import builder, document as dsdoc, mock, resolver, store

router = APIRouter()


class BuildRequest(BaseModel):
    name: str = ""
    sourceNodeId: str | int = ""
    sourceUrl: str = ""
    capturedAt: str = ""
    blocks: list = Field(default_factory=list)
    tokens: dict = Field(default_factory=dict)
    sourceArtifact: dict | None = None
    locale: str = "ru"
    includeGeneratedStates: bool = True
    createMock: bool = True


class DocumentRequest(BaseModel):
    document: dict


class OrganizeRequest(BaseModel):
    document: dict
    reasoningEffort: str = "high"


class StyleReviewRequest(BaseModel):
    """AI-ревью стилистики. prepareOnly → промпт; rawOutput → применить ответ
    внешнего провайдера (desktop); без обоих — серверный вызов Sol."""
    document: dict
    prepareOnly: bool = False
    rawOutput: str = ""
    provider: str = "openai"
    reasoningEffort: str = "high"


class RefRequest(BaseModel):
    systemId: str
    revision: int = 0


class DefaultRequest(BaseModel):
    systemId: str | None = None


class PreviewRequest(BaseModel):
    document: dict | None = None
    systemId: str = ""
    revision: int = 0
    componentKey: str = ""
    variantKey: str = "default"
    fixtureProfile: str = "source"
    usageMode: str = "strict"


class IdentityValidateRequest(BaseModel):
    document: dict
    ir: dict


class CompileRequest(BaseModel):
    ref: dict
    brief: str = ""
    usageMode: str = "strict"
    fixtureProfile: str = "typical"
    archetypeId: str = ""
    tokenBudget: int = 1200


class PromoteRequest(BaseModel):
    name: str = ""
    sourceNodeId: str | int = ""
    ir: dict
    visualReferences: list = Field(default_factory=list)


class ReconstructionRequest(BaseModel):
    document: dict
    candidateIr: dict
    proof: str = "source"


def _err(status: int, message: str):
    return JSONResponse({"error": message, "status": status}, status_code=status)


@router.post("/api/design-system/build")
def build_design_system(req: BuildRequest):
    """Source-данные → draft (без публикации)."""
    if not any(isinstance(b, dict) and b.get("ir") for b in req.blocks):
        return _err(422, "Source не содержит валидных блоков — запустите импорт заново")
    node_data = {"blocks": req.blocks, "tokens": req.tokens,
                 "sourceArtifact": req.sourceArtifact,
                 "mode": "url" if req.sourceUrl else "screenshot", "url": req.sourceUrl,
                 "capturedAt": req.capturedAt}
    pack = builder.build_source_pack(node_data, source_node_id=req.sourceNodeId)
    pack["_raw_blocks"] = req.blocks
    document = builder.build_draft(
        pack, name=req.name or None, locale=req.locale,
        include_generated_states=req.includeGeneratedStates, create_mock=req.createMock)
    saved = store.save_draft(document)
    from .document import summary
    return {"document": saved.get("document") or document, "summary": summary(saved.get("document") or document)}


@router.post("/api/design-system/save-draft")
def save_design_system_draft(req: DocumentRequest):
    if not isinstance(req.document, dict) or not req.document.get("id"):
        return _err(422, "Нет документа дизайн-системы")
    saved = store.save_draft(req.document)
    from .document import summary
    document = saved.get("document") or req.document
    return {"document": document, "summary": summary(document)}


@router.post("/api/design-system/organize")
def organize_design_system(req: OrganizeRequest):
    """Use Sol to organize catalog metadata without touching exact masters."""
    if not isinstance(req.document, dict) or not req.document.get("id"):
        return _err(422, "No Design System document")
    try:
        from .organizer import apply_catalog, organize_with_ai
        catalog = organize_with_ai(req.document, reasoning_effort=req.reasoningEffort)
        updated = apply_catalog(req.document, catalog)
        saved = store.save_draft(updated)
    except (ValueError, RuntimeError) as exc:
        return _err(422, str(exc))
    except Exception as exc:
        return _err(502, f"AI catalog organizer failed: {exc}")
    from .document import summary
    document = saved.get("document") or updated
    return {"document": document, "catalog": document.get("catalog") or catalog,
            "summary": summary(document)}


@router.post("/api/design-system/style-review")
def style_review_design_system(req: StyleReviewRequest):
    """AI-ревью дизайн-языка сайта → styleGuide.review (мастера неприкосновенны)."""
    if not isinstance(req.document, dict) or not req.document.get("id"):
        return _err(422, "No Design System document")
    from . import style_review
    if req.prepareOnly:
        return {"prompts": [{"messages": style_review.build_style_review_prompt(req.document)}]}
    try:
        if req.rawOutput.strip():
            updated = style_review.apply_style_review(
                req.document, req.rawOutput, provider=req.provider)
        else:
            updated = style_review.review_with_ai(
                req.document, reasoning_effort=req.reasoningEffort)
        saved = store.save_draft(updated)
    except (ValueError, RuntimeError) as exc:
        return _err(422, str(exc))
    except Exception as exc:
        return _err(502, f"AI style review failed: {exc}")
    from .document import summary
    document = saved.get("document") or updated
    return {"document": document, "styleGuide": document.get("styleGuide") or {},
            "summary": summary(document)}


@router.post("/api/design-system/publish")
def publish_design_system(req: DocumentRequest):
    if not isinstance(req.document, dict) or not req.document.get("id"):
        return _err(422, "Нет документа для публикации")
    result = store.publish(req.document)
    if not result.get("ok"):
        return JSONResponse(
            {"errors": result.get("errors") or [{"message": "publication failed"}]},
            status_code=422,
        )
    return {"document": result["document"], "summary": result["summary"], "duplicate": result.get("duplicate", False)}


@router.post("/api/design-system/validate")
def validate_design_system(req: DocumentRequest):
    from .document import validate_document
    if not isinstance(req.document, dict):
        return _err(422, "Нет документа для проверки")
    return {"errors": validate_document(req.document)}


@router.post("/api/design-system/preview")
def preview_design_system(req: PreviewRequest):
    document = req.document
    if not document and req.systemId:
        document = store.get_revision(req.systemId, req.revision)
        if not document:
            return _err(404, f"Ревизия {req.systemId}@{req.revision} не найдена")
    if (not isinstance(document, dict)
            or not (document.get("components") or document.get("reviewComponents")
                    or document.get("suggestions"))):
        return _err(422, "Нет документа для предпросмотра")
    components = document.get("components") or {}
    review_components = document.get("reviewComponents") or {}
    suggestions = document.get("suggestions") or {}
    comp = None
    if req.componentKey:
        comp = (components.get(req.componentKey)
                or review_components.get(req.componentKey)
                or suggestions.get(req.componentKey))
        if not isinstance(comp, dict):
            return _err(404, f"Компонент {req.componentKey} не найден")
    elif isinstance(components, dict) and components:
        comp = next(iter(components.values()))
    variants = (comp or {}).get("variants") if isinstance((comp or {}).get("variants"), dict) else {}
    variant_key = req.variantKey or "default"
    variant = variants.get(variant_key) if isinstance(variants.get(variant_key), dict) else None
    if req.variantKey and req.variantKey != "default" and variant is None:
        return _err(404, f"Variant {req.variantKey} of component {req.componentKey} was not found")
    profile = req.fixtureProfile or "source"
    fixture = resolver.fixture_for_component(document, comp, profile)
    master = (comp or {}).get("masterIr") or (comp or {}).get("templateIr")
    if variant and variant.get("masterRef") != "self" and isinstance(variant.get("masterIr"), dict):
        master = variant["masterIr"]
    render_ir = (comp or {}).get("templateIr") or (dsdoc.preview_ir_for_master(master) if isinstance(master, dict) else None)
    materialized = mock.materialize_ir(render_ir, fixture) if isinstance(render_ir, dict) else None
    source_ref_value = (variant or {}).get("sourceRef") or (comp or {}).get("sourceRef")
    source_ref = dict(source_ref_value or {}) if isinstance(source_ref_value, dict) else {}
    evidence = ((document.get("referenceAssets") or {}).get(source_ref.get("evidenceKey"))
                if source_ref.get("evidenceKey") else None)
    if isinstance(evidence, dict):
        source_ref.setdefault("referencePreviews", evidence.get("referencePreviews") or {})
        source_ref.setdefault("blockSizes", evidence.get("blockSizes") or {})
    return {
        "component": comp,
        "variant": variant,
        "variantKey": variant_key,
        "templateIr": materialized,
        "masterIr": master,
        "foundations": document.get("foundations") or {},
        "fixture": fixture,
        "fidelity": ((variant or {}).get("fidelity") or (comp or {}).get("fidelity")) if isinstance(comp, dict) else None,
        "sourceRef": source_ref,
        "usageMode": req.usageMode or "strict",
        "systemRef": {"systemId": document.get("id"), "revision": document.get("revision"),
                      "contentHash": document.get("contentHash")},
    }


@router.get("/api/design-system/list")
def list_design_systems():
    return {"systems": store.list_systems(), "defaultSystemRef": store.get_default()}


@router.post("/api/design-system/get")
def get_design_system(req: RefRequest):
    # resolve_ref, а не голый get_revision: легаси-pin «v0» на систему без
    # rev0-снапшота должен резолвиться в последнюю опубликованную ревизию
    # (иначе restore сохранённых графов падает «Ревизия …@0 не найдена»).
    document, error = store.resolve_ref({"systemId": req.systemId, "revision": req.revision})
    if error:
        return _err(404, error)
    return {"document": document}


@router.post("/api/design-system/restore-published")
def restore_published_design_system(req: RefRequest):
    """Cancel/Escape: reload immutable published revision, discard draft working copy."""
    try:
        result = store.restore_published(req.systemId, req.revision or None)
    except ValueError as exc:
        return _err(404, str(exc))
    return {"document": result["document"], "summary": result["summary"]}


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
    compiled = resolver.compiled_context(
        context, brief=brief,
        archetype_id=str((req or {}).get("archetypeId") or ""),
        token_budget=int((req or {}).get("tokenBudget") or 1200),
    )
    return {"context": context, **compiled}


@router.post("/api/design-system/compile")
def compile_design_identity(req: CompileRequest):
    document, error = store.resolve_ref(req.ref)
    if error:
        return _err(422, error)
    context = resolver.resolve_context(
        document, req.brief, usage_mode=req.usageMode,
        fixture_profile=req.fixtureProfile)
    return resolver.compiled_context(
        context, brief=req.brief, archetype_id=req.archetypeId,
        token_budget=req.tokenBudget)


@router.post("/api/design-system/identity/validate")
def validate_design_identity(req: IdentityValidateRequest):
    from .identity import ensure_identity, evaluate_identity
    document = ensure_identity(req.document)
    return evaluate_identity(
        req.ir, document.get("identity") or {}, document.get("identityTests") or [],
        document.get("foundations") or {})


@router.post("/api/design-system/identity/promote")
def promote_design_identity(req: PromoteRequest):
    """Promote an accepted Generator result into the existing DS workflow."""
    from .document import content_hash, new_document, summary
    from .identity import extract_identity
    if not isinstance(req.ir, dict) or not isinstance(req.ir.get("tree"), list) or not req.ir.get("tree"):
        return _err(422, "Для закрепления нужен непустой Design IR")
    name = req.name.strip() or "Закреплённый стиль"
    source_id = str(req.sourceNodeId or "generator")
    document = new_document(
        name,
        source_refs=[{"sourceNodeId": f"promoted:{source_id}", "url": "", "capturedAt": ""}],
    )
    tokens = req.ir.get("tokens") if isinstance(req.ir.get("tokens"), dict) else {}
    document["foundations"] = builder._foundations_from_tokens(tokens, ["desktop", "tablet", "mobile"])
    block = {"name": "promoted-master", "kind": "master", "ir": req.ir}
    identity, tests, measurements = extract_identity([block], document["foundations"])
    # Reference assets remain local metadata by default; no provider receives
    # them unless a later explicit transmission policy is approved.
    identity["visualReferences"] = [
        {**item, "transmissionPolicy": "local-only"}
        for item in req.visualReferences if isinstance(item, dict)
    ]
    document["identity"] = identity
    document["identityTests"] = tests
    document["identityMeasurements"] = measurements
    component_key = "promoted-master"
    document["components"] = {
        component_key: {
            "componentKey": component_key, "name": "Promoted Master", "category": "surfaces",
            "description": "Принятый пользователем результат генерации — мастер для переноса identity",
            "origin": "user", "status": "verified", "confidence": 1.0, "confirmed": True,
            "masterIr": req.ir, "propsSchema": {}, "slots": [],
            "variants": {"default": {"label": "Default", "origin": "user", "confirmed": True,
                                      "masterRef": "self", "diff": {}}},
            "states": {}, "dependencies": [], "tokenBindings": {}, "mockBindings": [],
            "accessibility": {"role": "group", "focusable": False},
            "provenance": {"sourceBlock": "promoted-master", "sourceKeys": [], "sourceRevisionHash": ""},
        }
    }
    document["patterns"] = {
        "promoted-page": {"name": "Promoted Page", "componentKeys": [component_key], "origin": "user", "confirmed": True}
    }
    document["quality"] = {"score": 70, "stateCoverage": 100, "issues": [], "observedCoverage": 100}
    document["contentHash"] = content_hash(document)
    saved = store.save_draft(document)
    result = saved.get("document") or document
    return {"document": result, "summary": summary(result)}


@router.post("/api/design-system/reconstruction/proof")
def run_reconstruction_proof(req: ReconstructionRequest):
    from datetime import datetime, timezone
    from .document import summary
    from .identity import ensure_identity, reconstruction_report
    document = ensure_identity(req.document)
    report = reconstruction_report(document, req.candidateIr, proof=req.proof)
    reconstruction = document.setdefault("reconstruction", {})
    key = "transferProof" if req.proof == "transfer" else "sourceProof"
    reconstruction[key] = report
    reconstruction["updatedAt"] = datetime.now(timezone.utc).isoformat()
    proofs = [reconstruction.get("sourceProof"), reconstruction.get("transferProof")]
    present = [proof for proof in proofs if isinstance(proof, dict)]
    reconstruction["status"] = "passed" if present and all(proof.get("status") == "passed" for proof in present) else "failed"
    saved = store.save_draft(document)
    result = saved.get("document") or document
    return {"document": result, "summary": summary(result), "report": report}
