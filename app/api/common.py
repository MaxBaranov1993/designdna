"""Общие помощники роутеров: корни путей, ответ-ошибка, валидация IR.

`server.py` импортирует их обратно, поэтому прежние обращения `server.err`
и `server.validate_ir` в тестах и коде продолжают работать.
"""
from __future__ import annotations


from fastapi.responses import JSONResponse

import concurrent.futures
import json
import re

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


_FACE_WEIGHT_RE = re.compile(r"^(?:[1-9]00(?: [1-9]00)?|normal|bold)$")


def sanitize_font_face_weights(doc: dict) -> dict:
    """Bring meta.fontFaces weights to the schema form without losing a variable range.

    The schema accepts one weight or a range ("100 900"). Collapsing a range to its
    first value declared a variable font as weight 100 only, and the browser then
    clamped every heading of the page to the thinnest instance. Off-grid values
    ("350 850", "380") are rounded to hundreds. Mutates and returns the document.
    """
    meta = doc.get("meta") if isinstance(doc, dict) else None
    faces = meta.get("fontFaces") if isinstance(meta, dict) else None
    if isinstance(faces, list):
        for face in faces:
            weight = face.get("weight") if isinstance(face, dict) else None
            if not isinstance(weight, str) or _FACE_WEIGHT_RE.match(weight):
                continue
            numbers = []
            for part in weight.split()[:2]:
                try:
                    numbers.append(min(900, max(100, int(round(float(part) / 100.0)) * 100)))
                except ValueError:
                    break
            if numbers:
                face["weight"] = " ".join(str(n) for n in sorted(set(numbers)))
    return doc


def parse_ir_response(raw: str):
    """extract_json + json.loads -> (ir, error)."""
    try:
        return json.loads(llm.extract_json(raw)), None
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"invalid JSON from model: {e}"


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
