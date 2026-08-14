"""Process-wide priority queue for outbound AI requests.

The web server is synchronous, so callers block on their own result while a
small fixed set of daemon workers protects the provider from request bursts.
"""
from __future__ import annotations

import concurrent.futures
import itertools
import os
import queue
import threading
import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


class AIRequestError(RuntimeError):
    """An operational AI failure with a stable, user-facing reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail or reason
        super().__init__(self.detail)


class AIRequestQueue:
    def __init__(self, concurrency: int | None = None) -> None:
        configured = concurrency if concurrency is not None else int(os.environ.get("AI_CONCURRENCY", "2"))
        self.concurrency = max(1, min(int(configured), 2))
        self._items: queue.PriorityQueue = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._closed = threading.Event()
        self._workers: list[threading.Thread] = []
        for index in range(self.concurrency):
            worker = threading.Thread(target=self._work, name=f"ai-queue-{index + 1}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def _work(self) -> None:
        while not self._closed.is_set():
            try:
                priority, _sequence, deadline, future, operation = self._items.get(timeout=0.2)
            except queue.Empty:
                continue
            del priority
            try:
                if not future.set_running_or_notify_cancel():
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AIRequestError("очередь", "deadline истёк в очереди")
                future.set_result(operation(remaining))
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._items.task_done()

    def run(self, operation: Callable[[float], T], *, timeout: float, priority: str = "normal") -> T:
        if self._closed.is_set():
            raise AIRequestError("очередь", "очередь AI-запросов остановлена")
        deadline = time.monotonic() + max(0.001, float(timeout))
        future: concurrent.futures.Future[T] = concurrent.futures.Future()
        rank = 0 if priority == "high" else 10
        self._items.put((rank, next(self._sequence), deadline, future, operation))
        try:
            return future.result(timeout=max(0.001, deadline - time.monotonic()))
        except concurrent.futures.TimeoutError as exc:
            if future.cancel():
                raise AIRequestError("очередь", "deadline истёк в очереди") from exc
            raise AIRequestError("таймаут", "deadline AI-запроса истёк") from exc

    def shutdown(self) -> None:
        self._closed.set()
        while True:
            try:
                _priority, _sequence, _deadline, future, _operation = self._items.get_nowait()
            except queue.Empty:
                break
            future.cancel()
            self._items.task_done()


GLOBAL_AI_QUEUE = AIRequestQueue()
