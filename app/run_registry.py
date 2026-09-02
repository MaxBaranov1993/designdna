"""Реестр длинных запусков (generate, quality-pass): стадии, SSE и отмена.

Browser передаёт ``runId`` и слушает ``/api/runs/{runId}/events``; polling
остаётся запасным каналом. Desktop использует собственные IPC-события.
Генератор также публикует агрегированный объём Responses-stream. Отмена
кооперативная и закрывает upstream-stream при получении следующей дельты.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_CHANGED = threading.Condition(_LOCK)
_RUNS: dict[str, dict[str, Any]] = {}
_KEEP_FINISHED = 50
_FINISHED = {"complete", "error", "cancelled"}


def _now() -> float:
    return time.time()


def start(run_id: str | None, kind: str) -> str | None:
    """Зарегистрировать запуск. Без runId (старые клиенты) — no-op, вернёт None."""
    if not run_id:
        return None
    run_id = str(run_id)[:64]
    with _LOCK:
        finished = [key for key, value in _RUNS.items() if value["status"] in _FINISHED]
        for stale in finished[:-_KEEP_FINISHED]:
            _RUNS.pop(stale, None)
        # Отмена могла прийти раньше, чем POST дошёл до хендлера (гонка на
        # клиенте) — флаг незавершённой записи с тем же id сохраняем.
        previous = _RUNS.get(run_id)
        cancelled = bool(previous and previous["cancelled"] and previous["status"] == "running")
        _RUNS[run_id] = {
            "runId": run_id,
            "kind": kind,
            "status": "running",
            "stage": "start",
            "stageLabel": "",
            "percent": None,
            "receivedChars": 0,
            "cancelled": cancelled,
            "error": None,
            "startedAt": _now(),
            "updatedAt": _now(),
            "revision": 1,
        }
        _CHANGED.notify_all()
    return run_id


def add_received_chars(run_id: str | None, count: int) -> None:
    """Publish aggregated streamed-output progress without exposing partial IR."""
    if not run_id or count <= 0:
        return
    with _LOCK:
        run = _RUNS.get(run_id)
        if not run or run["status"] != "running":
            return
        run["receivedChars"] = int(run.get("receivedChars") or 0) + int(count)
        run["updatedAt"] = _now()
        run["revision"] = int(run.get("revision") or 0) + 1
        _CHANGED.notify_all()


def stage(run_id: str | None, stage_id: str, label: str = "", percent: float | None = None) -> None:
    if not run_id:
        return
    with _LOCK:
        run = _RUNS.get(run_id)
        if not run or run["status"] != "running":
            return
        run["stage"] = stage_id
        run["stageLabel"] = label or stage_id
        run["percent"] = None if percent is None else max(0.0, min(100.0, float(percent)))
        run["updatedAt"] = _now()
        run["revision"] = int(run.get("revision") or 0) + 1
        _CHANGED.notify_all()


def _worker_cancelled() -> bool:
    """Десктоп: адресная отмена IPC-запроса живёт в cancel_token (contextvar)."""
    try:
        import cancel_token  # noqa: WPS433 — необязательный модуль воркера
    except ImportError:
        return False
    try:
        return bool(cancel_token.is_cancelled())
    except Exception:
        return False


def is_cancelled(run_id: str | None) -> bool:
    if _worker_cancelled():
        return True
    if not run_id:
        return False
    with _LOCK:
        run = _RUNS.get(run_id)
        return bool(run and run["cancelled"])


def cancel(run_id: str) -> bool:
    """True — запуск найден и ещё шёл; отмена доедет до следующей проверки."""
    with _LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return False
        run["cancelled"] = True
        run["updatedAt"] = _now()
        run["revision"] = int(run.get("revision") or 0) + 1
        _CHANGED.notify_all()
        return run["status"] == "running"


def finish(run_id: str | None, status: str = "complete", error: str | None = None) -> None:
    if not run_id:
        return
    with _LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return
        run["status"] = status if status in _FINISHED else "complete"
        run["error"] = error
        run["updatedAt"] = _now()
        run["revision"] = int(run.get("revision") or 0) + 1
        _CHANGED.notify_all()


def get(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        run = _RUNS.get(run_id)
        return dict(run) if run else None


def wait_for_update(run_id: str, after_revision: int = 0, timeout: float = 15.0) -> dict[str, Any] | None:
    """Block without polling until a run appears or its revision advances."""
    deadline = time.monotonic() + max(0.0, timeout)
    with _CHANGED:
        while True:
            run = _RUNS.get(run_id)
            if run and int(run.get("revision") or 0) > after_revision:
                return dict(run)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            _CHANGED.wait(remaining)


def reset() -> None:
    """Для тестов."""
    with _LOCK:
        _RUNS.clear()
        _CHANGED.notify_all()
