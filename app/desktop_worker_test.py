"""Worker concurrency regression: a long request must not freeze other API calls.

The desktop worker used to process JSONL frames strictly serially, so a
multi-minute /api/block-parse (Playwright × viewports) blocked every other
request — the UI appeared frozen. Now non-service frames run on a bounded
thread pool: a slow call must not delay an unrelated fast call.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[OK] " if ok else "[FAIL] ") + name + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class Worker:
    def __init__(self) -> None:
        env = os.environ.copy()
        env["DESIGNDNA_DATA_DIR"] = tempfile.mkdtemp(prefix="worker-conc-")
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "desktop_worker.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, cwd=str(ROOT),
        )
        self.next_id = 0
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.responses: dict[str, dict] = {}
        self.response_times: dict[str, float] = {}
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            try:
                frame = json.loads(line)
            except Exception:
                continue
            body = frame.get("params") or {}
            body_len = body.pop("bodyLen", 0)
            if body_len:
                body["bodyBytes"] = self.proc.stdout.read(body_len)
            with self.lock:
                response_id = str(frame.get("id"))
                self.responses[response_id] = frame
                self.response_times[response_id] = time.monotonic()

    def send_batch(self, calls: list[tuple[str, dict]]) -> list[str]:
        frames: list[str] = []
        request_ids: list[str] = []
        with self.lock:
            for method, params in calls:
                self.next_id += 1
                request_id = f"t-{self.next_id}"
                request_ids.append(request_id)
                frames.append(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        with self.write_lock:
            self.proc.stdin.write("".join(frames).encode("utf-8"))
            self.proc.stdin.flush()
        return request_ids

    def wait_response(self, request_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if request_id in self.responses:
                    return self.responses.pop(request_id)
            time.sleep(0.01)
        raise TimeoutError(f"worker request {request_id} timed out")

    def response_time(self, request_id: str) -> float:
        with self.lock:
            return self.response_times.get(request_id, -1.0)

    def request(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        [request_id] = self.send_batch([(method, params)])
        return self.wait_response(request_id, timeout)

    def close(self) -> None:
        try:
            self.request("shutdown", {}, timeout=10)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main() -> None:
    worker = Worker()
    try:
        health = worker.request("health", {})
        check("worker boots and answers health", health.get("result", {}).get("ok") is True, json.dumps(health))

        # длинный вызов (2с) уходит в пул; параллельный быстрый http.request
        # обязан вернуться ДО его завершения — раньше серийная обработка
        # замораживала UI на минуты
        results: dict[str, float] = {}

        def slow() -> None:
            t0 = time.time()
            worker.request("debug.sleep", {"seconds": 2.0}, timeout=30)
            results["slow"] = time.time() - t0

        thread = threading.Thread(target=slow)
        thread.start()
        time.sleep(0.3)  # длинный вызов гарантированно в полёте
        t0 = time.time()
        fast = worker.request("http.request", {"path": "/api/design-system/list", "method": "GET"})
        results["fast"] = time.time() - t0
        thread.join(timeout=30)

        check("fast http.request answered during slow call", bool(fast.get("result")), json.dumps(fast)[:120])
        check("fast call returned before the 2s slow call finished", results.get("fast", 99) < 1.5,
              f"fast={results.get('fast'):.2f}s slow={results.get('slow'):.2f}s")
        check("slow call completed", 1.5 <= results.get("slow", 0) <= 10, f"{results.get('slow'):.2f}s")

        conf = worker.request("runtime.configure", {"kimiApiKey": ""})
        check("runtime.configure stays inline and serial", conf.get("result", {}).get("ok") is True, json.dumps(conf))

        # Оба frame попадают в stdin одним write без паузы. configure обязан
        # видеть уже submitted slow job, даже если pool thread ещё не успел
        # начать его и увеличить какой-либо running-counter.
        batch_slow_id, batch_configure_id = worker.send_batch([
            ("debug.sleep", {"seconds": 0.4}),
            ("runtime.configure", {"kimiApiKey": "batch-rotated"}),
        ])
        batch_slow = worker.wait_response(batch_slow_id, timeout=30)
        batch_configure = worker.wait_response(batch_configure_id, timeout=30)
        check("back-to-back slow request completed", batch_slow.get("result", {}).get("ok") is True,
              json.dumps(batch_slow))
        check("back-to-back configure completed", batch_configure.get("result", {}).get("ok") is True,
              json.dumps(batch_configure))
        check("runtime.configure waits for a submitted job before its thread starts",
              worker.response_time(batch_configure_id) >= worker.response_time(batch_slow_id),
              f"configure@{worker.response_time(batch_configure_id):.6f} "
              f"slow@{worker.response_time(batch_slow_id):.6f}")

        # configure обязан дождаться активных задач: env-мутация не должна
        # гоняться с http.request, читающим credentials из os.environ.
        # Инвариант: ответ configure приходит не раньше ответа медленного
        # вызова (допуск — джиттер потоков клиента при чтении канала).
        done_times: dict[str, float] = {}
        configure_done = threading.Event()

        def reconfigure() -> None:
            worker.request("runtime.configure", {"kimiApiKey": "rotated"}, timeout=30)
            done_times["configure"] = time.time()
            configure_done.set()

        slow_done = threading.Event()

        def slow2() -> None:
            worker.request("debug.sleep", {"seconds": 1.0}, timeout=30)
            done_times["slow"] = time.time()
            slow_done.set()

        threading.Thread(target=slow2).start()
        time.sleep(0.3)  # вызов гарантированно в полёте
        threading.Thread(target=reconfigure).start()
        slow_done.wait(timeout=30)
        check("runtime.configure waits for in-flight pool tasks",
              slow_done.is_set() and configure_done.wait(timeout=30)
              and done_times.get("configure", 0.0) >= done_times.get("slow", 0.0) - 0.25,
              f"configure@{done_times.get('configure', -1):.2f}s slow@{done_times.get('slow', -1):.2f}s")

        # три одновременных вызова: пул обязан держать параллельность
        threads = [threading.Thread(target=lambda i=i: worker.request("debug.sleep", {"seconds": 0.5}, timeout=30))
                   for i in range(3)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        parallel_wall = time.time() - t0
        check("three concurrent calls finish near-parallel", parallel_wall < 1.4, f"{parallel_wall:.2f}s")
    finally:
        worker.close()

    if FAILS:
        print("FAILURES:", len(FAILS), "-", ", ".join(FAILS))
        sys.exit(1)
    print("ALL WORKER CONCURRENCY CHECKS PASSED")


if __name__ == "__main__":
    main()
