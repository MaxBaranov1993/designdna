"""Cancellation-token для длинных запросов: отмена без убийства процесса.

Запрос (JSONL-фрейм воркера или HTTP-вызов server.py) привязывается к
текущему контексту через set_current(request_id); транспорт, получив отмену,
вызывает cancel(request_id). Серверная логика проверяет is_cancelled() /
check() между стадиями (между LLM-вызовами, вариантами, шагами импорта) —
текущий сетевой вызов не прерывается, но следующий не начнётся.

Привязка — contextvar: anyio.to_thread копирует контекст в поток
sync-эндпоинта FastAPI, поэтому id доходит до серверного кода без явной
передачи. В чужие потоки (ThreadPoolExecutor без copy_context) контекст не
попадает — там is_cancelled() честно вернёт False.
"""
from __future__ import annotations

import contextvars
import threading
import time

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("cancel_token_request", default=None)
_LOCK = threading.Lock()
# request_id -> {"cancelled": bool, "at": float}. Отмена может прийти раньше,
# чем хендлер вызовет set_current (фрейм ещё в очереди пула) — запись
# создаётся и при cancel(), поэтому флаг не теряется.
_TOKENS: dict[str, dict] = {}
_STALE_AFTER_S = 3600.0
_MAX_TOKENS = 2000


class Cancelled(RuntimeError):
    """Запрос отменён пользователем; хендлер прерывает работу между стадиями."""

    cancelled = True

    def __init__(self, request_id: str | None = None):
        super().__init__("cancelled")
        self.request_id = request_id


def _prune_locked(now: float) -> None:
    if len(_TOKENS) < _MAX_TOKENS:
        return
    stale = [key for key, value in _TOKENS.items() if now - value["at"] > _STALE_AFTER_S]
    for key in stale:
        _TOKENS.pop(key, None)


def set_current(request_id: str | None) -> contextvars.Token:
    """Привязать текущий контекст к request_id (None — снять привязку).

    Возвращает token contextvar'а: при желании можно восстановить прежнее
    значение через contextvars.ContextVar.reset, обычно достаточно clear().
    """
    key = str(request_id) if request_id is not None else None
    if key is not None:
        with _LOCK:
            _prune_locked(time.time())
            _TOKENS.setdefault(key, {"cancelled": False, "at": time.time()})
    return _current.set(key)


def current() -> str | None:
    return _current.get()


def is_cancelled(request_id: str | None = None) -> bool:
    key = str(request_id) if request_id is not None else _current.get()
    if key is None:
        return False
    with _LOCK:
        token = _TOKENS.get(key)
        return bool(token and token["cancelled"])


def cancel(request_id: str) -> bool:
    """Выставить флаг. True — запрос был известен (уже шёл или ждал в очереди)."""
    key = str(request_id)
    with _LOCK:
        known = key in _TOKENS
        _prune_locked(time.time())
        token = _TOKENS.setdefault(key, {"cancelled": False, "at": time.time()})
        token["cancelled"] = True
        token["at"] = time.time()
        return known


def clear(request_id: str | None) -> None:
    """Снять запись по завершении запроса; текущая привязка тоже сбрасывается."""
    key = str(request_id) if request_id is not None else _current.get()
    if key is not None:
        with _LOCK:
            _TOKENS.pop(key, None)
    if _current.get() == key:
        _current.set(None)


def check() -> None:
    """Точка кооперативной отмены: бросает Cancelled, если текущий запрос отменён."""
    key = _current.get()
    if key is not None and is_cancelled(key):
        raise Cancelled(key)


def reset() -> None:
    """Для тестов."""
    with _LOCK:
        _TOKENS.clear()
