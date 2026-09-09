"""Служебные маршруты: конфигурация для фронтенда, статистика кэша, трасса вызовов моделей."""
from __future__ import annotations

import os

from fastapi import APIRouter

import agent_contract
import cache_store
import cli_llm
import ir
import llm_client as llm
import llm_trace
from storage import db as storage_db
from config import FEATURE_FLAGS, settings
from api.common import err

router = APIRouter()


@router.get("/api/cache/stats")
def cache_stats():
    """Наблюдаемость кэша: сколько LLM-вызовов сэкономлено повторами."""
    return cache_store.stats()


@router.get("/api/agent/trace")
def agent_trace(limit: int = 50, source: str | None = None):
    """Последние вызовы моделей из Electron и Python: метаданные без текста промптов."""
    if source not in (None, "", "python", "electron"):
        return err(422, "source: python | electron")
    return {"calls": llm_trace.recent(limit=limit, source=source or None), "directory": str(llm_trace.trace_dir())}


@router.get("/api/storage/status")
def storage_status(countRows: bool = True):
    """Базы SQLite приложения: пути, размеры, режим журнала, версии схем, число строк."""
    return {**storage_db.status(count_rows=countRows), "paths": settings.describe()}


@router.get("/api/config")
def app_config():
    """Runtime configuration and feature flags for the frontend."""
    return {
        "schemaVersion": ir.CURRENT_SCHEMA_VERSION,
        "agentContract": agent_contract.load().summary(),
        "flags": FEATURE_FLAGS.all(),
        "models": {
            "generator": llm.routing_models("generator")[0],
            "motionDirector": llm.routing_models("motion_director")[0],
        },
        # Чем отвечает сервер без десктопа: ключ OpenAI или консольный аккаунт
        "providers": {
            "openaiKey": bool(os.environ.get("OPENAI_API_KEY")),
            "codexCli": cli_llm.available("codex"),
            "claudeCli": cli_llm.available("claude"),
            "default": "openai" if os.environ.get("OPENAI_API_KEY") else (cli_llm.default_provider() or None),
        },
    }
