"""Протокол отмены desktop-воркера: cancel-фрейм гасит запрос, не убивая процесс.

Служебный фрейм ``{"type":"cancel","requestId":<id>[,"id":<ackId>]}`` читается
отдельным stdin-потоком и выставляет флаг в cancel_token; отменённый запрос
отвечает ``{"error":{"code":"cancelled",...},"cancelled":true}``; соседние
запросы и сам процесс продолжают жить.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from desktop_worker_test import Worker


class CancelWorker(Worker):
    def send_raw(self, frame: dict) -> None:
        with self.write_lock:
            self.proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
            self.proc.stdin.flush()

    def send_cancel(self, request_id: str, ack_id: str | None = None) -> None:
        frame: dict = {"type": "cancel", "requestId": request_id}
        if ack_id is not None:
            frame["id"] = ack_id
        self.send_raw(frame)


@pytest.fixture(scope="module")
def worker():
    instance = CancelWorker()
    health = instance.request("health", {}, timeout=60)
    assert health.get("result", {}).get("ok") is True, health
    yield instance
    instance.close()


def _is_cancelled(frame: dict) -> bool:
    error = frame.get("error") or {}
    return frame.get("cancelled") is True and error.get("code") == "cancelled" and error.get("cancelled") is True


def test_cancel_frame_aborts_in_flight_request_and_keeps_worker_alive(worker: CancelWorker):
    [slow_id] = worker.send_batch([("debug.sleep", {"seconds": 8.0})])
    time.sleep(0.3)  # запрос гарантированно в полёте
    t0 = time.monotonic()
    worker.send_cancel(slow_id, ack_id="ack-1")
    ack = worker.wait_response("ack-1", timeout=5)
    assert ack.get("result", {}).get("cancel") is True and ack["result"].get("known") is True, ack
    response = worker.wait_response(slow_id, timeout=5)
    assert _is_cancelled(response), response
    assert time.monotonic() - t0 < 2.0  # не ждали окончания 8-секундного сна
    # процесс жив и отвечает на следующий запрос
    health = worker.request("health", {}, timeout=10)
    assert health.get("result", {}).get("ok") is True


def test_cancel_does_not_touch_other_requests(worker: CancelWorker):
    victim_id, bystander_id = worker.send_batch([
        ("debug.sleep", {"seconds": 6.0}),
        ("debug.sleep", {"seconds": 0.8}),
    ])
    time.sleep(0.2)
    worker.send_cancel(victim_id)
    victim = worker.wait_response(victim_id, timeout=5)
    bystander = worker.wait_response(bystander_id, timeout=10)
    assert _is_cancelled(victim), victim
    assert bystander.get("result", {}).get("ok") is True, bystander


def test_cancel_before_request_starts_is_honoured(worker: CancelWorker):
    # три потока пула заняты — четвёртый запрос ждёт в очереди; отмена
    # обязана дойти до него ещё до старта хендлера
    blockers = worker.send_batch([("debug.sleep", {"seconds": 1.0})] * 3)
    [queued_id] = worker.send_batch([("debug.sleep", {"seconds": 5.0})])
    time.sleep(0.1)
    worker.send_cancel(queued_id)
    queued = worker.wait_response(queued_id, timeout=10)
    assert _is_cancelled(queued), queued
    for blocker in blockers:
        assert worker.wait_response(blocker, timeout=10).get("result", {}).get("ok") is True


def test_cancel_unknown_request_acknowledged_as_unknown(worker: CancelWorker):
    worker.send_cancel("no-such-request", ack_id="ack-unknown")
    ack = worker.wait_response("ack-unknown", timeout=5)
    assert ack.get("result", {}).get("known") is False, ack
    # воркер не пострадал
    assert worker.request("health", {}, timeout=10).get("result", {}).get("ok") is True


def test_cancel_is_read_while_configure_drains(worker: CancelWorker):
    # runtime.configure ждёт drain пула; раньше stdin не читался в этом окне
    # и cancel доезжал только после окончания длинного запроса
    slow_id, configure_id = worker.send_batch([
        ("debug.sleep", {"seconds": 6.0}),
        ("runtime.configure", {"openaiApiKey": ""}),
    ])
    time.sleep(0.3)
    t0 = time.monotonic()
    worker.send_cancel(slow_id)
    slow = worker.wait_response(slow_id, timeout=5)
    configure = worker.wait_response(configure_id, timeout=10)
    assert _is_cancelled(slow), slow
    assert configure.get("result", {}).get("ok") is True, configure
    assert time.monotonic() - t0 < 2.5


def test_http_request_to_cancelled_id_reports_cancelled(worker: CancelWorker):
    # cancel_token.check() внутри серверного кода: отменяем ДО старта запроса —
    # ответом обязан быть cancelled, а не HTTP-результат
    request_id = "http-cancel-1"
    worker.send_cancel(request_id)
    worker.send_raw({"id": request_id, "method": "http.request",
                     "params": {"path": "/api/design-system/list", "method": "GET"}})
    response = worker.wait_response(request_id, timeout=30)
    assert _is_cancelled(response), response


def test_concurrent_cancels_are_thread_safe(worker: CancelWorker):
    ids = worker.send_batch([("debug.sleep", {"seconds": 5.0})] * 3)
    time.sleep(0.2)
    threads = [threading.Thread(target=worker.send_cancel, args=(request_id,)) for request_id in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for request_id in ids:
        assert _is_cancelled(worker.wait_response(request_id, timeout=5))
