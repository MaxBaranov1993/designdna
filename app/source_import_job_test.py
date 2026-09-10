from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import server  # noqa: E402
import api.source_import as source_import_api  # noqa: E402
import cancel_token  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
import threading  # noqa: E402



def test_source_import_job_publishes_real_stage_and_result(monkeypatch):
    job_id = "job-test"
    result = {
        "url": "https://example.com",
        "blocks": [],
        "tokens": {},
        "cached": False,
        "diagnostics": {"timingsMs": {"captureCompile": 12, "total": 20}},
    }

    def fake_execute(_values, on_stage=None):
        on_stage("captureCompile", 12, {"captureCompile": 12})
        return result

    monkeypatch.setattr(source_import_api, "_execute_block_parse", fake_execute)
    with server.SOURCE_IMPORT_JOBS_LOCK:
        server.SOURCE_IMPORT_JOBS[job_id] = {
            "jobId": job_id,
            "status": "queued",
            "progress": 1,
            "stage": "queued",
            "stageLabel": "В очереди",
        }

    server._run_source_import_job(job_id, {"url": "https://example.com"})

    with server.SOURCE_IMPORT_JOBS_LOCK:
        job = server.SOURCE_IMPORT_JOBS.pop(job_id)
    assert job["status"] == "complete"
    assert job["progress"] == 100
    assert job["result"] == result
    assert job["timingsMs"]["total"] == 20


def test_concurrent_import_cancel_is_local_and_late_result_cannot_win(monkeypatch):
    entered = {key: threading.Event() for key in ("a", "b")}
    release = threading.Event()

    def execute(values, on_stage):
        entered[values["url"]].set()
        assert release.wait(5)
        # Some stages cannot stop immediately; the final guard must also check.
        return {"blocks": [{"name": values["url"]}]}

    monkeypatch.setattr(source_import_api, "_execute_block_parse", execute)
    monkeypatch.setattr(source_import_api, "SOURCE_IMPORT_JOBS", {
        key: {"jobId": key, "status": "queued"} for key in entered
    })
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(source_import_api._run_source_import_job, key, {"url": key}) for key in entered]
        try:
            assert all(event.wait(5) for event in entered.values())
            assert source_import_api.block_parse_job("b")["status"] == "running"
            assert source_import_api.cancel_block_parse_job("a")["status"] == "cancelled"
            assert source_import_api.block_parse_job("b")["status"] == "running"
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)
    assert source_import_api.block_parse_job("a")["status"] == "cancelled"
    assert "result" not in source_import_api.block_parse_job("a")
    assert source_import_api.block_parse_job("b")["result"]["blocks"][0]["name"] == "b"


def test_cancel_before_job_starts_prevents_capture(monkeypatch):
    monkeypatch.setattr(source_import_api, "SOURCE_IMPORT_JOBS", {"queued": {"status": "queued"}})
    called = []
    monkeypatch.setattr(source_import_api, "_execute_block_parse", lambda *args, **kwargs: called.append(True))
    source_import_api.cancel_block_parse_job("queued")
    source_import_api._run_source_import_job("queued", {"url": "unused"})
    assert called == []
    assert source_import_api.block_parse_job("queued")["status"] == "cancelled"
    assert not cancel_token.is_cancelled("source-import:queued")


def test_cancel_can_arrive_before_async_start_is_dispatched(monkeypatch):
    monkeypatch.setattr(source_import_api, "SOURCE_IMPORT_JOBS", {})
    source_import_api.cancel_block_parse_job("before-dispatch")
    source_import_api.SOURCE_IMPORT_JOBS["before-dispatch"] = {"status": "queued"}
    monkeypatch.setattr(source_import_api, "_execute_block_parse", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("capture started")))
    source_import_api._run_source_import_job("before-dispatch", {"url": "unused"})
    assert source_import_api.block_parse_job("before-dispatch")["status"] == "cancelled"
