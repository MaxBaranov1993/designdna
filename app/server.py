#!/usr/bin/env python3
"""DesignAI Web — локальный dev-сервер генерации веб-дизайна (Design IR).

Запуск:  .venv/Scripts/python app/server.py   (порт 8420)
"""
import contextlib
import mimetypes
import os
import sys
import traceback
import webbrowser
from pathlib import Path

# Windows: реестр может не знать MIME для .js/.css/woff — без корректного
# content-type браузер отказывается выполнять module-скрипты сборки /flow
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or APP_ROOT.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")
sys.path.insert(0, str(APP_ROOT))

from editor_assist import router as editor_assist_router

# Общие помощники роутеров и состояние рендера видео живут в пакете api/;
# server.err / validate_ir / RENDER_* остаются доступны прежним именем.
from config import FEATURE_FLAGS  # noqa: F401 — тесты подменяют server.FEATURE_FLAGS.is_enabled
# Модули, к которым тесты и внешний код обращаются через server.<имя>
# (server.llm.chat подменяется в тестах): сам сервер их больше не вызывает.
import cache_store  # noqa: F401
import llm_client as llm  # noqa: F401
import project_store  # noqa: F401
import qualitygate  # noqa: F401
import rules as project_rules  # noqa: F401
import run_registry  # noqa: F401
import api.common as common
from api.common import (  # noqa: F401
    CANCELLED_STATUS, EXECUTOR, SOURCE_IMPORT_EXECUTOR, _finish_run, err, parse_ir_response,
    sanitize_font_face_weights, validate_ir,
)
from api.motion import RENDER_DIR, RENDER_EXECUTOR, RENDER_JOBS, RENDER_JOBS_LOCK  # noqa: F401


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    common.ensure_executors()
    yield
    common.shutdown_executors()


app = FastAPI(title="DesignAI Web", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"],
)
app.include_router(editor_assist_router)

from design_system.api import router as design_system_router  # noqa: E402
app.include_router(design_system_router)

from timeline_api import router as timeline_router  # noqa: E402
app.include_router(timeline_router)

from video_api import router as video_router  # noqa: E402
app.include_router(video_router)

# Самостоятельные группы маршрутов вынесены в app/api/* (см. docs/BACKEND-REVIEW-2026-09-08.md).
from api.image import router as image_router  # noqa: E402
from api.rules import router as rules_router  # noqa: E402
from api.project import router as project_router  # noqa: E402
from api.system import router as system_router  # noqa: E402
from api.runs import router as runs_router  # noqa: E402
from api.style import router as style_router  # noqa: E402
from api.interaction import router as interaction_router  # noqa: E402
from api.motion import router as motion_router  # noqa: E402
from api.pages import router as pages_router  # noqa: E402
from api.reproduce import router as reproduce_router  # noqa: E402
from api.quality import router as quality_router  # noqa: E402
from api.source_import import router as source_import_router  # noqa: E402
from api.generate import router as generate_router  # noqa: E402
for _router in (generate_router, source_import_router, quality_router, reproduce_router,
                image_router, rules_router, project_router, system_router, runs_router,
                style_router, interaction_router, motion_router, pages_router):
    app.include_router(_router)

# Реэкспорт: тесты и внешние вызовы обращаются к хендлерам и моделям как server.<имя>.
from api.image import (  # noqa: E402,F401
    ImageConvertReq, ImageGenReq, ImageMaskReq, _IMAGE_STYLE_HINTS, _extract_svg, _sanitize_svg,
    image_convert, image_generate, image_remove_background,
)
from api.rules import ConstraintsCheckReq, ProjectRulesReq, constraints_check, get_rules, save_rules  # noqa: E402,F401
from api.project import (  # noqa: E402,F401
    ProjectLoadReq, ProjectSaveReq, TasteOutcomeReq, project_load, project_save, project_taste, project_taste_outcome,
)
from api.system import agent_trace, app_config, cache_stats  # noqa: E402,F401
from api.runs import run_cancel, run_events, run_status  # noqa: E402,F401
from api.style import (  # noqa: E402,F401
    StyleDnaApplyReq, StyleDnaReq, StyleNormalizeReq, TailwindProjectionReq,
    export_tailwind, style_dna_apply, style_dna_extract, style_normalize_preview,
)
from api.interaction import (  # noqa: E402,F401
    InteractionBuildReq, InteractionCaptureReq, InteractionReplayReq, InteractionValidateReq,
    interaction_build, interaction_capture, interaction_replay, interaction_validate,
)
from api.motion import (  # noqa: E402,F401
    MotionBuildReq, MotionMigrateV2Req, MotionRenderReq, MotionValidateReq, _completed_render_on_disk,
    _materialize_motion_scenes, _run_motion_render, motion_build, motion_migrate_v2, motion_render,
    motion_render_download, motion_render_status, motion_validate,
)
from api.pages import FONTS_DIR, flow_page, nodes_page, root_page, serve_font  # noqa: E402,F401
from api.reproduce import (  # noqa: E402,F401
    ReproduceReq, ScrapeReq, SegmentReq, _with_reproduce_parser_contract, reproduce, reproduce_segment,
    scrape,
)
from api.quality import (  # noqa: E402,F401
    COMPONENT_RUBRIC, JUDGE_FIRST_SCREEN_H, JUDGE_MAX_TILES, JUDGE_TILE_H, QUALITY_JUDGE_SYSTEM,
    QualityGateReq, QualityPassCodexOutputs, QualityPassCodexReq, QualityPassReq, _component_quality_mode,
    _judge_images, _parse_quality_repair, _parse_quality_scorecard, _quality_desktop_messages,
    _quality_finish, _quality_judge_messages, _quality_pass, _quality_repair, _quality_repair_messages,
    _quality_scorecard, _quality_violations, _quality_visual_key, quality_certify, quality_gate, quality_pass,
    quality_pass_codex_step,
)
from api.source_import import (  # noqa: E402,F401
    BlockParseRefineReq, BlockParseReq, FidelityRepairReq, SOURCE_IMPORT_JOBS, SOURCE_IMPORT_JOBS_LOCK,
    _SOURCE_STAGE_PROGRESS, _block_gate_passed, _execute_block_parse, _refresh_block_fidelity,
    _run_source_import_job, block_parse, block_parse_job, block_parse_refine, block_parse_repair,
)
from api.generate import (  # noqa: E402,F401
    COLOR_TOKEN_KEYS, CloneReq, GenerateReq, MAX_CLONE_HTML_BYTES, MixReq, ReskinReq, _CONTENT_SLOT_KEYS,
    _CONTENT_SLOT_LIMIT, _MASK_LABELS, _TYPE_ROLE_RULE, _apply_content_answer, _content_rewrite_messages,
    _content_slots, _embed_mode_block, _generate, _locked_generation_dna, _materialize_exact_master,
    _reference_pinned_component_keys, _reference_screens_block, _walk_ir_elements, call_llm_ir, clone,
    generate, mix, reskin,
)


# роли вызовов для роутинга LLM — см. таблицу llm_client.ROUTING
# (generate/edit/repair/clone/reference/...)


# ---------- helpers ----------


# Поле provider в запросах сохранено для совместимости со старыми сейвами;
# продукт маршрутизирует вызовы по цепочке ROUTING подключённых аккаунтов,
# поэтому вход намеренно игнорируется (всегда "auto").


# ---------- models ----------


# ---------- Source Import / Reskin (см. docs/ARCHITECTURE.md и docs/NODES.md) ----------


# ---------- Quality Gate / Constraints (решение владельца 12.2, бэклог §8) ----------


app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")

@app.exception_handler(Exception)
async def unhandled(request, exc):
    traceback.print_exc()
    return JSONResponse({"detail": f"Внутренняя ошибка: {exc}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    url = "http://127.0.0.1:8420/flow"
    print(f"DesignAI Web: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="warning")
