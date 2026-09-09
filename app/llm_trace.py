"""Трасса вызовов моделей: JSONL без текста промптов и ответов.

Python-путь (ревью мастеров ДС, timeline director, понимание страницы) пишет
``<data>/traces/llm-calls.python.jsonl``; Electron пишет соседний
``llm-calls.electron.jsonl`` (desktop/services/llm-trace.mjs). ``recent()``
читает оба файла, чтобы сервер и MCP могли показать агенту, какой провайдер,
модель, усилие и версия контракта стояли за результатом ноды.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from config import settings

ROOT = settings.runtime_root()
DATA_ROOT = settings.data_dir()
TRACE_DIR_NAME = "traces"
PYTHON_FILE = "llm-calls.python.jsonl"
ELECTRON_FILE = "llm-calls.electron.jsonl"
MAX_BYTES = 8 * 1024 * 1024
MAX_ERROR_CHARS = 300
_LOCK = threading.Lock()


def trace_dir(data_root: Path | None = None) -> Path:
    return Path(data_root or DATA_ROOT) / TRACE_DIR_NAME


def message_chars(messages: list | None, system: str = "") -> int:
    total = len(system or "")
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(str(part.get("text") or "")) for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return total


def record(*, request_id: str | None, role: str, provider: str | None, model: str | None, effort: str | None,
           contract_version: str | None, duration_ms: float, prompt_chars: int, output_chars: int,
           error: str | None = None, structured_output: bool | None = None, dropped: list | None = None,
           streamed: bool = False) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "python",
        "requestId": request_id,
        "profile": role,
        "provider": provider,
        "model": model,
        "effort": effort,
        "contractVersion": contract_version,
        "structuredOutput": structured_output,
        "dropped": [str(item.get("field")) for item in (dropped or []) if isinstance(item, dict) and item.get("field")],
        "durationMs": max(0, int(round(duration_ms))),
        "ok": error is None,
        "error": (error or "")[:MAX_ERROR_CHARS] or None,
        "streamed": bool(streamed),
        "promptChars": int(prompt_chars),
        "outputChars": int(output_chars),
    }


def write(entry: dict[str, Any], data_root: Path | None = None) -> bool:
    """Никогда не ломает вызов модели: ошибка записи трассы только глотается."""
    try:
        directory = trace_dir(data_root)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / PYTHON_FILE
        with _LOCK:
            try:
                if target.stat().st_size >= MAX_BYTES:
                    target.replace(target.with_name(PYTHON_FILE + ".1"))
            except FileNotFoundError:
                pass
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


class timed:
    """Контекст для замера вызова: ``with timed() as clock: ...; clock.ms``."""

    def __enter__(self):
        self.started = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.started) * 1000.0
        return False


def _tail_lines(path: Path, limit: int) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            chunk = min(size, max(65_536, limit * 1_024))
            handle.seek(size - chunk)
            data = handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return []
    lines = data.splitlines()
    if len(lines) and size > chunk:
        lines = lines[1:]  # первая строка могла быть обрезана
    return lines[-limit:]


def recent(limit: int = 50, data_root: Path | None = None, source: str | None = None) -> list[dict[str, Any]]:
    """Последние записи обоих источников, новые первыми. Только метаданные."""
    limit = max(1, min(int(limit), 500))
    directory = trace_dir(data_root)
    files = {"python": directory / PYTHON_FILE, "electron": directory / ELECTRON_FILE}
    entries: list[dict[str, Any]] = []
    for name, path in files.items():
        if source and name != source:
            continue
        for line in _tail_lines(path, limit):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                item.setdefault("source", name)
                entries.append(item)
    entries.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return entries[:limit]
