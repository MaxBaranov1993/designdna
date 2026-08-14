"""Focused checks for queue ordering, retries and partial batch results."""
from __future__ import annotations

import copy
import io
import pathlib
import sys
import threading
import time
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import ai_scheduler
import llm_client
import server
from test_qualitygate import BASE_IR


def check(name: str, condition: bool, extra: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name}: {extra}")
    print(f"[OK ] {name}")


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("https://provider.test", code, "temporary", headers, io.BytesIO(b"{}"))


def main() -> None:
    # A high-priority assist overtakes an already queued normal batch item.
    request_queue = ai_scheduler.AIRequestQueue(concurrency=1)
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    order: list[str] = []

    def blocker(_remaining: float) -> str:
        blocker_started.set()
        release_blocker.wait(1)
        return "blocker"

    first = threading.Thread(target=lambda: request_queue.run(blocker, timeout=2), daemon=True)
    first.start()
    blocker_started.wait(1)
    normal = threading.Thread(
        target=lambda: request_queue.run(lambda _r: order.append("normal"), timeout=2), daemon=True
    )
    high = threading.Thread(
        target=lambda: request_queue.run(lambda _r: order.append("high"), timeout=2, priority="high"), daemon=True
    )
    normal.start()
    time.sleep(0.02)
    high.start()
    time.sleep(0.02)
    release_blocker.set()
    first.join(1)
    normal.join(1)
    high.join(1)
    check("AI-assist обгоняет batch в очереди", order == ["high", "normal"], str(order))
    request_queue.shutdown()

    # Even when many callers arrive together, the process-wide policy never
    # allows more than two provider operations at once.
    limited_queue = ai_scheduler.AIRequestQueue(concurrency=2)
    active = 0
    peak = 0
    activity_lock = threading.Lock()

    def measured(_remaining: float) -> None:
        nonlocal active, peak
        with activity_lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with activity_lock:
            active -= 1

    callers = [
        threading.Thread(target=lambda: limited_queue.run(measured, timeout=1), daemon=True)
        for _ in range(6)
    ]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(1)
    check("глобальная concurrency не выше двух", peak == 2, str(peak))
    limited_queue.shutdown()

    # Retry-After is honored and transient 429 succeeds on the next attempt.
    attempts = 0

    def throttled(_timeout: int) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise http_error(429, "0")
        return "ok"

    original_base = llm_client.RETRY_BASE_S
    original_attempts = llm_client.RETRY_ATTEMPTS
    llm_client.RETRY_BASE_S = 0.01
    llm_client.RETRY_ATTEMPTS = 3
    try:
        check("429 повторяется и затем проходит", llm_client._with_transient_retry(throttled, 1) == "ok")
        check("429 сделал две попытки", attempts == 2, str(attempts))
        for transient_code in (502, 503):
            code_attempts = 0

            def temporarily_unavailable(_timeout: int, code=transient_code) -> str:
                nonlocal code_attempts
                code_attempts += 1
                if code_attempts == 1:
                    raise http_error(code, "0")
                return "ok"

            check(
                f"{transient_code} повторяется с backoff",
                llm_client._with_transient_retry(temporarily_unavailable, 1) == "ok" and code_attempts == 2,
            )
    finally:
        llm_client.RETRY_BASE_S = original_base
        llm_client.RETRY_ATTEMPTS = original_attempts

    # The batch returns completed variants at its deadline instead of waiting
    # for the final slow provider call.
    original_call = server.call_llm_ir
    original_acceptance = server._run_generation_acceptance
    calls = 0
    lock = threading.Lock()

    def fake_call(_provider, _user, _temperature=0.8, _mode="generate", timeout=None):
        nonlocal calls
        with lock:
            calls += 1
            number = calls
        if number == 3:
            time.sleep(1.4)
        return copy.deepcopy(BASE_IR), None

    server.call_llm_ir = fake_call
    server._run_generation_acceptance = lambda candidate, brief, index, deadline: (
        candidate, {"index": index, "score": 100, "verdict": "pass", "issues": [], "fixed": 0}
    )
    started = time.monotonic()
    try:
        result = server.generate(server.GenerateReq(
            brief="лендинг для теста deadline",
            count=3,
            deadlineSeconds=1,
        ))
    finally:
        server.call_llm_ir = original_call
        server._run_generation_acceptance = original_acceptance
    elapsed = time.monotonic() - started
    check("batch вернул два готовых варианта", len(result["variants"]) == 2, str(result))
    check("batch помечен как частичный результат", result["reason"] == "частичный результат", str(result))
    check("оставшийся вариант помечен как таймаут", result["errors"][0]["reason"] == "таймаут", str(result))
    check("batch не ждал зависший вариант", elapsed < 1.25, f"{elapsed:.3f}s")

    print("ALL AI SCHEDULER CHECKS PASSED")


if __name__ == "__main__":
    main()
