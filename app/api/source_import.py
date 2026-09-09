"""Source Import: детерминированный разбор сайта на блоки, фоновые задания, AI-уточнение и починка точности: /api/block-parse*."""
import copy
import threading
import traceback
import uuid
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from urlguard import validate_public_url
import cache_store
import blockparse
from fastapi import APIRouter
from api.common import (  # noqa: F401
    APP_ROOT, CANCELLED_STATUS, DATA_ROOT, ROOT, _finish_run, err, parse_ir_response,
    sanitize_font_face_weights, validate_ir,
)
import api.common as common

router = APIRouter()


SOURCE_IMPORT_JOBS: dict[str, dict] = {}


SOURCE_IMPORT_JOBS_LOCK = threading.Lock()


class BlockParseReq(BaseModel):
    url: str = ""
    blocks: list | None = None  # опционально: [{name, selector}] — клонировать только их
    viewports: list[dict] | None = None
    authCookies: list[dict] | None = None
    authSessionFallback: bool = False
    fullResolutionEvidence: bool = False
    asyncJob: bool = False


class BlockParseRefineReq(BaseModel):
    """AI-уточнение разбора: только подписи и роли блоков, IR неприкосновенен."""
    blocks: list
    operations: list = []
    source: dict | None = None


class FidelityRepairReq(BaseModel):
    """Цикл AI-починки захвата. prepareOnly отдаёт задания на диагностику
    (регион + узлы), rawOutputs — ответы провайдера; сервер применяет их только
    если пиксельное сходство выросло."""
    blocks: list
    viewport: str = "desktop"
    prepareOnly: bool = False
    rawOutputs: list = []
    maxRegions: int = 3


_SOURCE_STAGE_PROGRESS = {
    "prepare": (3, "Подготовка"),
    "cacheLookup": (7, "Проверка кэша"),
    "renderDom": (22, "Загрузка DOM"),
    "detectBlocks": (30, "Детекция блоков"),
    "semanticRefine": (34, "Разметка секций"),
    "captureCompile": (72, "Слои и responsive"),
    "assemble": (80, "Сборка Design IR"),
    "fidelity": (95, "Проверка fidelity"),
    "cacheWrite": (99, "Сохранение кэша"),
}


def _execute_block_parse(values: dict, on_stage=None) -> dict:
    result = blockparse.parse_blocks(
        values["url"],
        blocks=values.get("blocks"),
        viewports=values.get("viewports"),
        auth_cookies=values.get("authCookies"),
        full_resolution_evidence=bool(values.get("fullResolutionEvidence")),
        on_stage=on_stage,
    )
    if values.get("authSessionFallback"):
        result["authWarning"] = "В сессии нет cookie для этого URL — выполнен публичный импорт"
    return result


def _run_source_import_job(job_id: str, values: dict) -> None:
    def on_stage(stage: str, _duration: int, timings: dict[str, int]) -> None:
        progress, label = _SOURCE_STAGE_PROGRESS.get(stage, (1, stage))
        if stage.startswith("capture") and stage != "captureCompile":
            viewport_index = max(1, int(timings.get("captureViewportIndex", 1)))
            viewport_count = max(1, int(timings.get("captureViewportCount", 3)))
            progress = min(68, 30 + round(38 * viewport_index / viewport_count))
            label = stage.removeprefix("capture") + " layers"
        with SOURCE_IMPORT_JOBS_LOCK:
            job = SOURCE_IMPORT_JOBS.get(job_id)
            if job:
                job.update(status="running", progress=progress, stage=stage,
                           stageLabel=label, timingsMs=timings)

    try:
        result = _execute_block_parse(values, on_stage=on_stage)
        with SOURCE_IMPORT_JOBS_LOCK:
            job = SOURCE_IMPORT_JOBS.get(job_id)
            if job:
                job.update(status="complete", progress=100, stage="complete",
                           stageLabel="Готово", result=result,
                           timingsMs=(result.get("diagnostics") or {}).get("timingsMs", {}))
    except Exception as exc:
        traceback.print_exc()
        with SOURCE_IMPORT_JOBS_LOCK:
            job = SOURCE_IMPORT_JOBS.get(job_id)
            if job:
                job.update(status="error", stage="error", stageLabel="Ошибка",
                           error=str(exc)[:500])


@router.post("/api/block-parse")
def block_parse(req: BlockParseReq):
    """BlockParse: детекция блоков страницы + clone каждого в editable Design IR."""
    url = req.url.strip()
    if not url:
        return err(422, "Укажите URL сайта.")
    try:
        validate_public_url(url)  # SSRF-гард (422, а не 502)
    except ValueError as e:
        return err(422, str(e))

    values = {
        "url": url,
        "blocks": copy.deepcopy(req.blocks),
        "viewports": copy.deepcopy(req.viewports),
        "authCookies": copy.deepcopy(req.authCookies),
        "authSessionFallback": req.authSessionFallback,
        "fullResolutionEvidence": req.fullResolutionEvidence,
    }
    if req.asyncJob:
        job_id = uuid.uuid4().hex
        job = {
            "jobId": job_id,
            "status": "queued",
            "progress": 1,
            "stage": "queued",
            "stageLabel": "В очереди",
            "timingsMs": {},
        }
        with SOURCE_IMPORT_JOBS_LOCK:
            # Keep bounded diagnostics; completed payloads can be large.
            completed = [key for key, value in SOURCE_IMPORT_JOBS.items()
                         if value.get("status") in {"complete", "error"}]
            for stale_id in completed[:-9]:
                SOURCE_IMPORT_JOBS.pop(stale_id, None)
            SOURCE_IMPORT_JOBS[job_id] = job
        common.SOURCE_IMPORT_EXECUTOR.submit(_run_source_import_job, job_id, values)
        return job

    try:
        return _execute_block_parse(values)
    except ValueError as e:  # кривой список блоков
        return err(422, str(e))
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка block-parse: {e}")


@router.get("/api/block-parse/job/{job_id}")
def block_parse_job(job_id: str):
    with SOURCE_IMPORT_JOBS_LOCK:
        job = SOURCE_IMPORT_JOBS.get(job_id)
        if not job:
            return err(404, "Source Import job не найден.")
        # Завершённый job больше не мутирует, а его результат — мегабайты
        # артефакта: deepcopy под глобальным локом на каждом финальном полле
        # был заметной паузой. Копируем только живые (маленькие) записи.
        if job.get("status") in {"complete", "error"}:
            return job
        return copy.deepcopy(job)


@router.post("/api/block-parse/refine")
def block_parse_refine(req: BlockParseRefineReq):
    """Применить AI-уточнения к уже разобранным блокам.

    Разрешены только переименования и смена роли блока (см.
    blockparse.apply_refinements): геометрия и IR не меняются, поэтому
    fidelity-гейт нельзя обойти через этот маршрут. Артефакт пересобирается
    из обновлённых блоков, чтобы UI Kit увидел новые имена и роли.
    """
    if not isinstance(req.blocks, list) or not req.blocks:
        return err(422, "Нет блоков для уточнения.")
    import scraper
    try:
        blocks, applied = blockparse.apply_refinements(
            copy.deepcopy(req.blocks), req.operations)
        blocks = scraper.canonicalize_source_blocks(
            blocks, stage="source-refine-apply", include_evidence=True)
    except scraper.CanonicalRasterAssetError as exc:
        status = 503 if exc.detail["retryable"] else 422
        return JSONResponse({"error": str(exc), "status": status, **exc.detail}, status_code=status)
    except Exception as e:
        traceback.print_exc()
        return err(502, f"Ошибка уточнения: {e}")
    tokens = None
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("ir"), dict):
            tokens = block["ir"].get("tokens")
            if tokens:
                break
    source = req.source or {}
    final_url = next((b.get("finalUrl") for b in blocks
                      if isinstance(b, dict) and isinstance(b.get("finalUrl"), str)
                      and b["finalUrl"]), "")
    source_url = source.get("url") if isinstance(source.get("url"), str) else ""
    artifact = blockparse._build_source_artifact(
        source_url or final_url, blocks, tokens, source.get("authenticated") is True)
    # Refinement changes labels, not capture provenance or compiler identity.
    if isinstance(source.get("pipelineVersion"), str) and source["pipelineVersion"]:
        artifact["source"]["pipelineVersion"] = source["pipelineVersion"]
    return {"ok": True, "blocks": blocks, "sourceArtifact": artifact,
            "applied": applied, "appliedCount": len(applied)}


def _block_gate_passed(block: dict) -> bool:
    """Прошёл ли блок fidelity-гейт по последнему отчёту harness."""
    report = block.get("fidelityReport") if isinstance(block.get("fidelityReport"), dict) else {}
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    return gate.get("passed") is True


def _refresh_block_fidelity(block: dict, page) -> bool:
    """Перемерить блок тем же harness после принятой AI-починки.

    Собираем запись захвата обратно: публичный блок несёт IR, эталоны и
    размеры, а измеренные на живой странице листовые кадры и потери лежат в
    кэше улик (blockparse._stash_repair_evidence). Нет улик — перезамера не
    делаем: мерить bbox без листовых кадров значило бы ослабить гейт.
    """
    import blockparse
    import fidelity_harness

    evidence = cache_store.get("repair_evidence", str(block.get("evidenceKey") or ""))
    if not isinstance(evidence, dict) or not evidence.get("leafBoxesByViewport"):
        return False
    item = {
        "ir": block.get("ir"),
        "previews": block.get("previews") or {},
        "sizes": block.get("sizes") or {},
        "paint_coverage": evidence.get("paintCoverage") or {},
        "leaf_boxes_by_viewport": evidence.get("leafBoxesByViewport") or {},
        "dropped_by_viewport": evidence.get("droppedByViewport") or {},
        "extras_by_viewport": evidence.get("extrasByViewport") or {},
    }
    if evidence.get("provenance"):
        item["provenance"] = evidence["provenance"]
    try:
        report = fidelity_harness.evaluate_capture_item(item, page)
    except Exception:
        traceback.print_exc()
        return False
    block["fidelityReport"] = blockparse._public_fidelity_report(report)
    viewport_metrics = report.get("viewports") or {}
    for field, metric in (("fidelity", "pixel_similarity"),
                          ("paintCoverage", "paint_coverage"),
                          ("p95LayoutError", "bbox_p95")):
        block[field] = {
            name: metrics.get(metric)
            for name, metrics in viewport_metrics.items()
            if isinstance(metrics, dict) and metrics.get(metric) is not None
        }
    return True


@router.post("/api/block-parse/repair")
def block_parse_repair(req: FidelityRepairReq):
    """AI-починка расхождений захвата с детерминированным судьёй.

    prepareOnly → задания диагностики (худшие регионы + узлы в них) для
    выбранного пользователем провайдера. С rawOutputs сервер валидирует
    предложения, применяет каждое к копии IR, ПЕРЕМЕРЯЕТ сходство тем же
    harness и оставляет только те, что реально улучшили картинку.
    """
    import fidelity_repair
    import scraper

    blocks = [b for b in (req.blocks or [])
              if isinstance(b, dict) and isinstance(b.get("ir"), dict) and not b.get("error")]
    if not blocks:
        return err(422, "Нет разобранных блоков для починки.")
    try:
        # Repair requests may contain desktop-expanded assets. Canonical state
        # must be restored before measurement and before returning to Source.
        blocks = scraper.canonicalize_source_blocks(
            blocks, stage="source-repair-input", include_evidence=not req.prepareOnly)
    except scraper.CanonicalRasterAssetError as exc:
        status = 503 if exc.detail["retryable"] else 422
        return JSONResponse({"error": str(exc), "status": status, **exc.detail}, status_code=status)
    viewport = str(req.viewport or "desktop")

    def viewport_report(block: dict) -> dict:
        """Метрики viewport для починки: публичный отчёт + карта расхождений.

        region_diffs намеренно нет в ответе /api/block-parse (сетка 8×8 на
        каждый компонент раздувала полезную нагрузку), поэтому единственная
        нужная починке карта берётся из кэша улик по ключу блока.
        """

        report = block.get("fidelityReport") if isinstance(block.get("fidelityReport"), dict) else {}
        viewports = report.get("viewports") if isinstance(report.get("viewports"), dict) else {}
        metrics = viewports.get(viewport) if isinstance(viewports.get(viewport), dict) else {}
        if metrics.get("region_diffs"):
            return metrics
        evidence = cache_store.get("repair_evidence", str(block.get("evidenceKey") or ""))
        regions = ((evidence or {}).get("regionDiffsByViewport") or {}).get(viewport)
        return {**metrics, "region_diffs": regions} if regions else metrics

    if req.prepareOnly:
        tasks = []
        for index, block in enumerate(blocks):
            if _block_gate_passed(block):
                continue  # прошедший гейт блок чинить нечего
            metrics = viewport_report(block)
            for rect in fidelity_repair.region_rects(metrics, limit=max(1, min(6, req.maxRegions))):
                nodes = fidelity_repair.nodes_in_region(block["ir"], rect)
                if not nodes:
                    continue
                tasks.append({
                    "blockIndex": index,
                    "block": block.get("name"),
                    "region": rect,
                    "messages": fidelity_repair.build_repair_prompt(
                        str(block.get("name") or f"block-{index}"), viewport, rect, nodes, metrics),
                })
        return {"tasks": tasks, "viewport": viewport}

    try:
        import fidelity_harness
        import scraper
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - окружение без Playwright
        return err(502, f"Harness недоступен: {exc}")

    outputs: dict[int, list[str]] = {}
    for item in req.rawOutputs or []:
        if isinstance(item, dict) and isinstance(item.get("blockIndex"), int):
            outputs.setdefault(int(item["blockIndex"]), []).append(str(item.get("content") or ""))

    results = []
    try:
        with sync_playwright() as playwright:
            browser = scraper.launch_chromium(playwright)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900},
                                        device_scale_factor=1)
                # Тот же блок сетевых шрифтов, что в evaluate_captures: иначе
                # судья мерит текст в fallback-шрифте и врёт в обе стороны.
                page.route("https://fonts.googleapis.com/**",
                           lambda route: route.abort("blockedbyclient"))
                page.route("https://fonts.gstatic.com/**",
                           lambda route: route.abort("blockedbyclient"))
                for index, block in enumerate(blocks):
                    answers = list(outputs.get(index) or [])
                    if not answers:
                        continue
                    metrics = viewport_report(block)
                    render_block = scraper.source_block_render_copy(block)
                    reference = render_block.get("previews", {}).get(viewport) or render_block.get("preview")
                    size = (block.get("sizes") or {}).get(viewport) or block.get("size") or {}
                    width = int(size.get("width") or 1440)
                    height = int(size.get("height") or 900)
                    if not isinstance(reference, str) or not reference.startswith("data:"):
                        continue
                    reference_png = fidelity_harness._decode_data_url(reference)
                    render_measure = fidelity_repair.make_browser_measurer(
                        page, reference_png, viewport, width, height)
                    def measure(candidate):
                        return render_measure(scraper.source_block_render_copy(
                            {"ir": candidate, "name": block.get("name")})["ir"])
                    pending = iter(answers)
                    outcome = fidelity_repair.repair_block(
                        block["ir"], block_name=str(block.get("name") or index),
                        viewport=viewport, report_viewport=metrics,
                        measure=measure,
                        propose=lambda _messages: next(pending, ""),
                        max_regions=max(1, min(6, req.maxRegions)))
                    remeasured = False
                    if outcome.get("ir") and outcome.get("applied"):
                        block["ir"] = scraper.canonicalize_ir_raster_assets(
                            outcome["ir"], stage="source-repair-apply",
                            component=str(block.get("name") or index), path=f"blocks[{index}].ir")
                        # Статус обязан догнать IR: без перезамера правка живёт
                        # в дереве, а гейт продолжает судить по отчёту, снятому
                        # до починки, и компонент навсегда «нужна проверка».
                        # The harness itself resolves canonical IR; only its
                        # screenshot evidence needs expansion here.
                        evidence_block = scraper.source_block_render_copy(block)
                        evidence_block["ir"] = block["ir"]
                        remeasured = _refresh_block_fidelity(evidence_block, page)
                        for field in ("fidelityReport", "fidelity", "paintCoverage", "p95LayoutError"):
                            if field in evidence_block:
                                block[field] = evidence_block[field]
                    results.append({
                        "blockIndex": index, "block": block.get("name"),
                        "baseline": outcome.get("baseline"), "similarity": outcome.get("similarity"),
                        "gain": outcome.get("gain"),
                        "appliedCount": len(outcome.get("applied") or []),
                        "rejectedCount": len(outcome.get("rejected") or []),
                        "applied": outcome.get("applied") or [],
                        "remeasured": remeasured,
                        "gatePassed": _block_gate_passed(block),
                    })
            finally:
                browser.close()
        blocks = scraper.canonicalize_source_blocks(
            blocks, stage="source-repair-apply", include_evidence=True)
    except scraper.CanonicalRasterAssetError as exc:
        status = 503 if exc.detail["retryable"] else 422
        return JSONResponse({"error": str(exc), "status": status, **exc.detail}, status_code=status)
    except Exception as exc:
        traceback.print_exc()
        return err(502, f"Ошибка починки: {exc}")

    return {"ok": True, "viewport": viewport, "blocks": blocks, "results": results,
            "gatePassed": all(_block_gate_passed(block) for block in blocks),
            "totalGain": round(sum(float(r.get("gain") or 0) for r in results), 2)}
