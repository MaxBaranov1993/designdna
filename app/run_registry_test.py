"""run_registry: стадии, кооперативная отмена, эндпоинты /api/runs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_registry


def setup_function(_):
    run_registry.reset()


def test_without_run_id_everything_is_noop():
    assert run_registry.start(None, "generate") is None
    run_registry.stage(None, "llm", "x")
    assert run_registry.is_cancelled(None) is False
    run_registry.finish(None)


def test_stage_and_finish_lifecycle():
    rid = run_registry.start("r1", "generate")
    assert rid == "r1"
    run_registry.stage(rid, "llm", "Модель генерирует IR", percent=140)
    run = run_registry.get(rid)
    assert run["status"] == "running"
    assert run["stage"] == "llm"
    assert run["stageLabel"] == "Модель генерирует IR"
    assert run["percent"] == 100.0
    run_registry.finish(rid, "complete")
    assert run_registry.get(rid)["status"] == "complete"
    # стадии после завершения игнорируются
    run_registry.stage(rid, "late", "late")
    assert run_registry.get(rid)["stage"] == "llm"


def test_wait_for_update_tracks_revisions():
    rid = run_registry.start("events-1", "generate")
    first = run_registry.wait_for_update(rid, 0, timeout=0)
    assert first and first["revision"] == 1
    assert run_registry.wait_for_update(rid, first["revision"], timeout=0) is None
    run_registry.stage(rid, "validate", "Проверка")
    changed = run_registry.wait_for_update(rid, first["revision"], timeout=0)
    assert changed and changed["revision"] == 2 and changed["stage"] == "validate"


def test_streamed_character_progress_is_aggregated():
    rid = run_registry.start("stream-1", "generate")
    run_registry.add_received_chars(rid, 512)
    run_registry.add_received_chars(rid, 37)
    run = run_registry.get(rid)
    assert run["receivedChars"] == 549
    assert run["revision"] == 3


def test_generator_stream_progress_does_not_expose_partial_ir(monkeypatch):
    import server

    rid = run_registry.start("stream-2", "generate")

    def fake_chat(*_args, on_delta=None, **_kwargs):
        on_delta("x" * 600)
        on_delta("tail")
        return '{"ok":true}'

    monkeypatch.setattr(server.llm, "chat", fake_chat)
    ir, error = server.call_llm_ir("openai", "brief", run_id=rid)
    assert error is None
    assert ir == {"ok": True}
    run = run_registry.get(rid)
    assert run["receivedChars"] == 604
    assert "partial" not in run


def test_generator_cancel_closes_stream_on_next_delta(monkeypatch):
    import server

    rid = run_registry.start("stream-cancel", "generate")

    def fake_chat(*_args, on_delta=None, **_kwargs):
        run_registry.cancel(rid)
        on_delta("must not be accepted")
        raise AssertionError("cancelled delta callback must interrupt the stream")

    monkeypatch.setattr(server.llm, "chat", fake_chat)
    ir, error = server.call_llm_ir("openai", "brief", run_id=rid)
    assert ir is None
    assert error == "cancelled"
    assert run_registry.get(rid)["receivedChars"] == 0


def test_cancel_is_cooperative_flag():
    rid = run_registry.start("r2", "quality-pass")
    assert run_registry.is_cancelled(rid) is False
    assert run_registry.cancel(rid) is True
    assert run_registry.is_cancelled(rid) is True
    run_registry.finish(rid, "cancelled")
    # повторная отмена завершённого — False (уже не идёт), но не падает
    assert run_registry.cancel(rid) is False
    assert run_registry.cancel("missing") is False


def test_finished_runs_are_pruned():
    for i in range(80):
        rid = run_registry.start(f"old-{i}", "generate")
        run_registry.finish(rid)
    run_registry.start("fresh", "generate")
    assert run_registry.get("old-0") is None
    assert run_registry.get("old-79") is not None
    assert run_registry.get("fresh")["status"] == "running"


def test_endpoints_and_cancelled_generate():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    assert client.get("/api/runs/nope").status_code == 404
    rid = run_registry.start("ep-1", "generate")
    run_registry.stage(rid, "llm", "Модель генерирует IR")
    body = client.get("/api/runs/ep-1").json()
    assert body["stageLabel"] == "Модель генерирует IR"
    assert client.post("/api/runs/ep-1/cancel").json()["cancelled"] is True
    assert run_registry.is_cancelled(rid)

    run_registry.finish(rid, "cancelled")
    with client.stream("GET", "/api/runs/ep-1/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = "".join(stream.iter_text())
    assert '"status":"cancelled"' in body

    # Отменённый заранее запуск генерации не зовёт модель и отвечает 499
    calls = []

    def fake_llm(*args, **kwargs):
        calls.append(args)
        return None, "should not be called"

    original = server.call_llm_ir
    server.call_llm_ir = fake_llm
    try:
        run_registry.reset()
        run_registry.start("gen-1", "generate")
        run_registry.cancel("gen-1")
        resp = client.post("/api/generate", json={"brief": "лендинг кофейни", "count": 1, "runId": "gen-1"})
    finally:
        server.call_llm_ir = original
    assert resp.status_code == server.CANCELLED_STATUS
    assert calls == []
    assert run_registry.get("gen-1")["status"] == "cancelled"
