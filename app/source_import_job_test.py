from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import server  # noqa: E402


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

    monkeypatch.setattr(server, "_execute_block_parse", fake_execute)
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
