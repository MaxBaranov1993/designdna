"""Общие помощники роутеров: корни путей, ответ-ошибка, валидация IR.

`server.py` импортирует их обратно, поэтому прежние обращения `server.err`
и `server.validate_ir` в тестах и коде продолжают работать.
"""
from __future__ import annotations


from fastapi.responses import JSONResponse

import concurrent.futures
import json

import ir
import llm_client as llm
import run_registry
from config import settings

APP_ROOT = settings.app_dir()
ROOT = settings.runtime_root()
DATA_ROOT = settings.data_dir()


def validate_ir(doc: dict) -> list[str]:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return ir.format_errors(ir.validate_ir(doc))


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


# ---------- пулы фоновых задач ----------
# Генерация вариантов и Source Import работают в общих пулах. После остановки
# приложения (lifespan) пулы создаются заново, поэтому TestClient с lifespan и
# прямые вызовы хендлеров в одной сессии не зависят от порядка. Модули
# обращаются к пулам через common.EXECUTOR, а не через импорт имени.
EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
SOURCE_IMPORT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def fresh_executors() -> None:
    global EXECUTOR, SOURCE_IMPORT_EXECUTOR
    EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    SOURCE_IMPORT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def ensure_executors() -> None:
    if getattr(EXECUTOR, "_shutdown", False) or getattr(SOURCE_IMPORT_EXECUTOR, "_shutdown", False):
        fresh_executors()


def shutdown_executors() -> None:
    EXECUTOR.shutdown(wait=True)
    SOURCE_IMPORT_EXECUTOR.shutdown(wait=True)
    fresh_executors()


def sanitize_font_face_weights(doc: dict) -> dict:
    """Variable-шрифты отдают диапазон весов («400 800»), а схема принимает один
    вес. IR, захваченные до нормализации на захвате (scraper._resolve_font_faces),
    чиним на входе: диапазон → базовый вес. Мутирует и возвращает документ."""
    meta = doc.get("meta") if isinstance(doc, dict) else None
    faces = meta.get("fontFaces") if isinstance(meta, dict) else None
    if isinstance(faces, list):
        for face in faces:
            weight = face.get("weight") if isinstance(face, dict) else None
            if isinstance(weight, str) and len(weight.split()) > 1:
                face["weight"] = weight.split()[0]
    return doc


def parse_ir_response(raw: str):
    """extract_json + json.loads -> (ir, error)."""
    try:
        return json.loads(llm.extract_json(raw)), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"невалидный JSON от модели: {e}"


# 499 — клиент отменил запуск (кооперативная отмена через run_registry)
CANCELLED_STATUS = 499


def _finish_run(run_id: str | None, resp) -> None:
    """Закрыть запись реестра по итогу хендлера: отмена > ошибка > успех."""
    if not run_id:
        return
    if run_registry.is_cancelled(run_id):
        status = "cancelled"
    elif isinstance(resp, JSONResponse) and resp.status_code >= 400:
        status = "error"
    else:
        status = "complete"
    run_registry.finish(run_id, status)
