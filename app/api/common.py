"""Общие помощники роутеров: корни путей, ответ-ошибка, валидация IR.

`server.py` импортирует их обратно, поэтому прежние обращения `server.err`
и `server.validate_ir` в тестах и коде продолжают работать.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import JSONResponse

import ir

APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent.parent)
ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or APP_ROOT.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")


def validate_ir(doc: dict) -> list[str]:
    """Список ошибок валидации IR по схеме (пустой = ок)."""
    return ir.format_errors(ir.validate_ir(doc))


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)
