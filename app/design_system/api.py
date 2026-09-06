"""API дизайн-систем: build/publish/list/get/default (ТЗ §7, §14)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import builder, compiler, document as dsdoc, importer, mock, resolver, store
from .desktop_ai import router as desktop_ai_router

router = APIRouter()
router.include_router(desktop_ai_router)


class BuildRequest(BaseModel):
    systemId: str = ""
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
    provider: str = "openai"
    reasoningEffort: str = "high"


class StyleguideRequest(BaseModel):
    """Выгрузка живого UI kit одним самодостаточным HTML-файлом."""
    document: dict | None = None
    systemId: str = ""
    revision: int = 0
    includeProof: bool = True
    includeReviewComponents: bool = True
    viewport: str = "desktop"


class StyleReviewRequest(BaseModel):
    """AI-ревью стилистики. prepareOnly → промпт; rawOutput → применить ответ
    внешнего провайдера (desktop); без обоих — серверный вызов выбранной модели."""
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


class ImportRequest(BaseModel):
    """Загрузка ДС файлом: документ DesignDNA, W3C/Tokens Studio JSON, карта токенов."""
    payload: dict
    name: str = ""
    fileName: str = ""


class ComponentSectionRequest(BaseModel):
    """Секция с пиннутым мастером ДС для вставки в текущую страницу редактора."""
    systemId: str
    revision: int = 0
    componentKey: str
    variantKey: str = "default"


class VariantSaveRequest(BaseModel):
    """Сохранить IR из редактора как вариант существующего компонента ДС (не новый компонент)."""
    systemId: str
    componentKey: str
    variantKey: str = ""
    label: str = ""
    ir: dict


class PolishRequest(BaseModel):
    document: dict | None = None
    systemId: str = ""
    componentKey: str = ""
    headless: bool = True


def _err(status: int, error_message: str, **details):
    return JSONResponse({"error": error_message, "status": status, **details}, status_code=status)


@router.post("/api/design-system/build")
def build_design_system(req: BuildRequest):
    """Source-данные → draft (без публикации)."""
    if not any(isinstance(b, dict) and b.get("ir") for b in req.blocks):
        return _err(422, "Source не содержит валидных блоков — запустите импорт заново")
    existing = None
    if req.systemId:
        existing = store.get_revision(req.systemId, 0)
        if not isinstance(existing, dict) or existing.get("id") != req.systemId:
            return _err(404, "Design System draft for rebuild was not found",
                        stage="ds-build-target", component="", path="systemId", retryable=False)
    node_data = {"blocks": req.blocks, "tokens": req.tokens,
                 "sourceArtifact": req.sourceArtifact,
                 "mode": "url" if req.sourceUrl else "screenshot", "url": req.sourceUrl,
                 "capturedAt": req.capturedAt}
    from scraper import CanonicalRasterAssetError, canonicalize_source_blocks
    from fidelity_harness import FidelityRenderError
    try:
        node_data["blocks"] = canonicalize_source_blocks(
            req.blocks, stage="ds-build-assets", include_evidence=True)
        pack = builder.build_source_pack(node_data, source_node_id=req.sourceNodeId)
        # Raw blocks retain component evidence omitted from the compact pack,
        # but must never bypass canonicalization with the transport payload.
        pack["_raw_blocks"] = node_data["blocks"]
        document = builder.build_draft(
            pack, name=req.name or (existing or {}).get("name") or None, locale=req.locale,
            include_generated_states=req.includeGeneratedStates, create_mock=req.createMock)
    except CanonicalRasterAssetError as exc:
        return _err(503 if exc.detail["retryable"] else 422, str(exc), **exc.detail)
    except FidelityRenderError as exc:
        return _err(503, str(exc), **exc.detail)
    if existing:
        # save_draft writes revision 0 only. Published snapshots, registry
        # history and default pins remain attached to the existing system.
        document["id"] = existing["id"]
        document["projectId"] = existing.get("projectId") or "default"
    saved = store.save_draft(document)
    from .document import summary
    return {"document": saved.get("document") or document, "summary": summary(saved.get("document") or document)}


@router.post("/api/design-system/import")
def import_design_system(req: ImportRequest):
    """Файл → draft: та же форма документа, что у ДС из Source, генератор лочит её так же."""
    try:
        document = importer.import_design_system(req.payload, name=req.name, file_name=req.fileName)
        from .polish import polish_document
        imported_components = list((document.get("components") or {}).values()) + list((document.get("reviewComponents") or {}).values())
        has_fonts = any(isinstance(item, dict) and isinstance(item.get("masterIr"), dict)
                        and ((item["masterIr"].get("meta") or {}).get("fontFaces") or [])
                        for item in imported_components)
        document, _polish_results = polish_document(document, headless=has_fonts)
    except ValueError as exc:
        return _err(422, str(exc))
    errors = dsdoc.validate_document(document)
    # Кит из одних токенов — легитимная ДС (режим style-only / extend): отсутствие
    # мастеров не ошибка импорта, а свойство файла.
    hard = [e for e in errors if isinstance(e, dict) and e.get("code") != "no-components"]
    if hard:
        return _err(422, "Документ не прошёл проверку: " + "; ".join(str(e.get("message") or e.get("code")) for e in hard[:4]))
    saved = store.save_draft(document)
    from .document import summary
    document = saved.get("document") or document
    return {"document": document, "summary": summary(document),
            "format": (document.get("provenance") or {}).get("imported", {}).get("format")}


@router.post("/api/design-system/polish")
def polish_design_system(req: PolishRequest):
    """Lint and deterministically polish masters, using production headless rendering by default."""
    document = req.document or (store.get_revision(req.systemId, 0) if req.systemId else None)
    if not isinstance(document, dict) or not document.get("id"):
        return _err(422, "No Design System document")
    from . import polish
    try:
        updated, results = polish.polish_document(document, headless=req.headless)
        if req.componentKey:
            wanted = [item for item in results if item.get("componentKey") == req.componentKey]
            if not wanted:
                return _err(404, f"Component {req.componentKey} not found")
            # Do not alter unrelated components when polishing a single card.
            polished_all = updated
            updated = __import__("copy").deepcopy(document)
            for item in wanted:
                pool = item["pool"]
                updated[pool][req.componentKey] = polished_all[pool][req.componentKey]
            results = wanted
        saved = store.save_draft(updated)
    except Exception as exc:
        return _err(502, f"Layout polish failed: {exc}")
    from .document import summary
    result_doc = saved.get("document") or updated
    return {"document": result_doc, "results": results, "summary": summary(result_doc)}


@router.post("/api/design-system/polish/rollback")
def rollback_design_system_polish(req: PolishRequest):
    document = req.document or (store.get_revision(req.systemId, 0) if req.systemId else None)
    if not isinstance(document, dict) or not document.get("id") or not req.componentKey:
        return _err(422, "Design System document and componentKey are required")
    import copy
    from .polish import rollback_component
    updated = copy.deepcopy(document)
    component = None
    for pool in ("components", "reviewComponents"):
        candidate = (updated.get(pool) or {}).get(req.componentKey)
        if isinstance(candidate, dict):
            component = candidate
            break
    if component is None:
        return _err(404, f"Component {req.componentKey} not found")
    if not rollback_component(component):
        return _err(409, "Component has no polish snapshot")
    saved = store.save_draft(updated)
    from .document import summary
    result_doc = saved.get("document") or updated
    return {"document": result_doc, "rolledBack": True, "summary": summary(result_doc)}


def _master_root(ir: dict) -> dict | None:
    """Корень мастера из IR ноды Edit: обёртка component-master → её ребёнок, иначе первая секция."""
    tree = ir.get("tree") if isinstance(ir, dict) and isinstance(ir.get("tree"), list) else []
    if not tree or not isinstance(tree[0], dict):
        return None
    root = tree[0]
    if root.get("type") == "source-block" and root.get("variant") == "component-master":
        kids = root.get("children") or []
        return kids[0] if kids and isinstance(kids[0], dict) else None
    return root


@router.post("/api/design-system/component-section")
def component_section(req: ComponentSectionRequest):
    """Мастер ДС как секция страницы с sourceMeta.componentRef — strict принимает её как копию."""
    document = store.get_revision(req.systemId, req.revision) if req.revision else None
    if not document:
        # черновик (revision 0) или последняя опубликованная
        document = store.get_revision(req.systemId, 0)
    if not document:
        return _err(404, f"Дизайн-система {req.systemId} не найдена")
    comp = (document.get("components") or {}).get(req.componentKey) or (document.get("reviewComponents") or {}).get(req.componentKey)
    if not isinstance(comp, dict):
        return _err(404, f"Компонент {req.componentKey} не найден")
    master = comp.get("masterIr") if isinstance(comp.get("masterIr"), dict) else comp.get("templateIr")
    variants = comp.get("variants") if isinstance(comp.get("variants"), dict) else {}
    variant = variants.get(req.variantKey) if req.variantKey else None
    if isinstance(variant, dict) and variant.get("masterRef") != "self" and isinstance(variant.get("masterIr"), dict):
        master = variant["masterIr"]
    if not isinstance(master, dict):
        return _err(422, "У компонента нет masterIr")
    preview = dsdoc.preview_ir_for_master(master)
    section = (preview.get("tree") or [None])[0]
    if not isinstance(section, dict):
        return _err(422, "Не удалось собрать секцию из мастера")
    system_ref = {"systemId": document.get("id"), "revision": document.get("revision"), "contentHash": document.get("contentHash")}
    handle_component = comp
    if isinstance(variant, dict) and variant.get("masterRef") != "self" and isinstance(variant.get("masterIr"), dict):
        handle_component = {**comp, "masterIr": master}
    handle = compiler.component_handle(handle_component, system_ref)
    target = section
    if section.get("type") == "source-block" and section.get("variant") == "component-master":
        kids = section.get("children") or []
        if kids and isinstance(kids[0], dict):
            target = kids[0]
    meta = target.get("sourceMeta") if isinstance(target.get("sourceMeta"), dict) else {}
    target["sourceMeta"] = {**meta, "kind": meta.get("kind") or "dom", "componentRef": handle}
    section["id"] = f"ds-{req.componentKey}"
    return {"section": section, "tokens": preview.get("tokens") or {}, "meta": preview.get("meta") or {},
            "componentRef": handle, "name": comp.get("name") or req.componentKey}


@router.post("/api/design-system/variant/save")
def save_variant(req: VariantSaveRequest):
    """Вариант компонента вместо нового компонента: реестр не раздувается.

    Пишется в черновик (revision 0); в опубликованную ревизию вариант попадёт
    после Publish. Наблюдённые варианты Source не трогаем — добавляется
    пользовательский (origin: user)."""
    document = store.get_revision(req.systemId, 0)
    if not document:
        return _err(404, f"Черновик дизайн-системы {req.systemId} не найден — откройте ноду ДС")
    comp = (document.get("components") or {}).get(req.componentKey)
    if not isinstance(comp, dict):
        return _err(404, f"Компонент {req.componentKey} не найден в реестре")
    root = _master_root(req.ir)
    if not isinstance(root, dict):
        return _err(422, "В IR нет корня компонента")
    variants = comp.setdefault("variants", {})
    if not isinstance(variants, dict):
        variants = comp["variants"] = {}
    key = (req.variantKey or "").strip() or None
    if not key:
        base = "user"
        index = 1
        while f"{base}-{index}" in variants:
            index += 1
        key = f"{base}-{index}"
    key = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in key)[:48] or "user-1"
    master_ir = {"version": req.ir.get("version") or "1.1", "tokens": req.ir.get("tokens") or {},
                 **({"meta": req.ir["meta"]} if isinstance(req.ir.get("meta"), dict) else {}),
                 "tree": [root]}
    variants[key] = {
        "label": (req.label or "").strip() or key.replace("-", " ").title(),
        "semanticKey": key,
        "origin": "user",
        "confirmed": True,
        "masterRef": key,
        "masterIr": master_ir,
        "masterHash": dsdoc.content_hash(master_ir),
        "diff": {},
    }
    saved = store.save_draft(document)
    from .document import summary
    document = saved.get("document") or document
    return {"document": document, "summary": summary(document), "variantKey": key,
            "variants": list(((document.get("components") or {}).get(req.componentKey) or {}).get("variants") or {})}


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
    """Use the selected model to organize metadata without touching exact masters."""
    if not isinstance(req.document, dict) or not req.document.get("id"):
        return _err(422, "No Design System document")
    try:
        from .organizer import apply_catalog, organize_with_ai
        catalog = organize_with_ai(req.document, provider=req.provider, reasoning_effort=req.reasoningEffort)
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
                req.document, provider=req.provider, reasoning_effort=req.reasoningEffort)
        saved = store.save_draft(updated)
    except (ValueError, RuntimeError) as exc:
        return _err(422, str(exc))
    except Exception as exc:
        return _err(502, f"AI style review failed: {exc}")
    from .document import summary
    document = saved.get("document") or updated
    return {"document": document, "styleGuide": document.get("styleGuide") or {},
            "summary": summary(document)}


class MasterReviewRequest(BaseModel):
    """AI-ревью мастеров пула «на ревью»: агент сравнивает оригинал и рендер
    и сам одобряет/отклоняет — подтверждение пользователя не требуется."""
    document: dict | None = None
    systemId: str = ""
    revision: int = 0
    provider: str = "auto"
    viewport: str = "desktop"
    maxComponents: int = 8


@router.post("/api/design-system/master-review")
def master_review_design_system(req: MasterReviewRequest):
    document = req.document
    if not document and req.systemId:
        document = store.get_revision(req.systemId, req.revision)
    if not isinstance(document, dict) or not document.get("id"):
        return _err(422, "No Design System document")
    from . import master_review
    from .document import summary
    if not master_review.review_candidates(document):
        return {"document": document, "results": [], "summary": summary(document), "reviewed": 0}
    try:
        updated, results = master_review.run(
            document, provider=req.provider or "auto", viewport=req.viewport or "desktop",
            max_components=req.maxComponents)
        from .polish import polish_document
        updated, polish_results = polish_document(updated, headless=False)
        saved = store.save_draft(updated)
    except (ValueError, RuntimeError) as exc:
        return _err(422, str(exc))
    except Exception as exc:
        return _err(502, f"AI master review failed: {exc}")
    document = saved.get("document") or updated
    return {"document": document, "results": results, "polishResults": polish_results,
            "summary": summary(document),
            "reviewed": len(results), "approved": sum(1 for r in results if r.get("approved"))}


@router.post("/api/design-system/styleguide")
def export_styleguide(req: StyleguideRequest):
    """Документ дизайн-системы → живой UI kit одним HTML-файлом.

    Отдаём octet-stream, а не text/html: desktop-мост гонит любой text/* через
    JSON-заголовок с экранированием (app/desktop_worker.py), а бинарный кадр
    существует ровно для таких многомегабайтных ответов.
    """
    import datetime
    import re as _re

    from fastapi import Response

    from . import styleguide

    document = req.document
    if not document and req.systemId:
        document = store.get_revision(req.systemId, req.revision)
        if not document:
            return _err(404, f"Ревизия {req.systemId}@{req.revision} не найдена")
    if not isinstance(document, dict):
        return _err(422, "Нет документа дизайн-системы")
    if not (document.get("components") or document.get("reviewComponents")):
        return _err(422, "В системе нет мастеров — соберите UI Kit из Source")

    try:
        html_text, report = styleguide.render_styleguide(
            document,
            include_proof=req.includeProof,
            include_review_components=req.includeReviewComponents,
            viewport=req.viewport or "desktop",
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
    except (ValueError, RuntimeError) as exc:
        return _err(422, str(exc))
    except Exception as exc:
        return _err(502, f"Сборка UI Kit не удалась: {exc}")

    slug = _re.sub(r"[^A-Za-z0-9._-]+", "-", str(document.get("name") or "ui-kit")).strip("-") or "ui-kit"
    filename = f"{slug}-rev{int(document.get('revision') or 0)}.html"
    return Response(
        content=html_text.encode("utf-8"),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-DesignDNA-Filename": filename,
            "X-DesignDNA-Bytes": str(report["bytes"]),
            "X-DesignDNA-Components": str(report["componentCount"]),
            "X-DesignDNA-Warnings": str(len(report["warnings"])),
        },
    )


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
