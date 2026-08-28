"""Paid confirmation and API mapping tests for Motion Design video jobs."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import video_api


def client() -> TestClient:
    app = FastAPI()
    app.include_router(video_api.router)
    return TestClient(app)


def test_unconfirmed_submit_never_reaches_paid_transport(monkeypatch) -> None:
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("paid transport reached")

    monkeypatch.setattr(video_api.video_client, "submit", forbidden)
    with client() as api:
        response = api.post("/api/video/seedance/submit", json={"prompt": "A product shot"})
    assert response.status_code == 409
    assert called is False


def test_confirmed_submit_maps_all_seedance_controls(monkeypatch) -> None:
    captured = {}

    def submit(prompt: str, **kwargs):
        captured.update(prompt=prompt, **kwargs)
        return {"id": "job_safe", "status": "pending", "model": "bytedance/seedance-2.5"}

    monkeypatch.setattr(video_api.video_client, "submit", submit)
    with client() as api:
        response = api.post("/api/video/seedance/submit", json={
            "prompt": "Extend the supplied motion clip",
            "duration": 10,
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "generate_audio": True,
            "seed": 9,
            "confirmed_paid": True,
            "input_references": [{
                "type": "video_url",
                "video_url": {"url": "https://cdn.example/ready.mp4"},
            }],
        })
    assert response.status_code == 200
    assert captured["duration"] == 10
    assert captured["generate_audio"] is True
    assert captured["input_references"][0]["type"] == "video_url"


def test_status_and_content_are_resume_only(monkeypatch) -> None:
    monkeypatch.setattr(video_api.video_client, "status", lambda job_id: {
        "id": job_id, "status": "completed", "usage": {"cost": 0.5},
    })
    monkeypatch.setattr(video_api.video_client, "content", lambda _job_id: (b"video", "video/mp4"))
    with client() as api:
        status = api.get("/api/video/seedance/job_safe")
        content = api.get("/api/video/seedance/job_safe/content")
    assert status.json()["usage"]["cost"] == 0.5
    assert content.content == b"video"
    assert content.headers["content-type"].startswith("video/mp4")
