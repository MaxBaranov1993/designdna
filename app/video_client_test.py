"""OpenRouter Seedance 2.5 transport tests; no paid/network calls."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import video_client


RECORDED: list[tuple[str, str, dict | None]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECORDED.append(("POST", self.path, body))
        self._json({"id": "video_job_123", "status": "pending"}, 202)

    def do_GET(self):
        RECORDED.append(("GET", self.path, None))
        if self.path.endswith("/content"):
            body = b"fake-mp4"
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({
            "id": "video_job_123",
            "status": "completed",
            "usage": {"cost": 0.25},
        })

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def local_openrouter(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    RECORDED.clear()
    monkeypatch.setattr(
        video_client,
        "OPENROUTER_VIDEO_URL",
        f"http://127.0.0.1:{server.server_address[1]}/api/v1/videos",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    try:
        yield
    finally:
        server.shutdown()


def test_submit_pins_seedance_25_and_video_reference(local_openrouter) -> None:
    reference = "data:video/mp4;base64,ZmFrZS12aWRlbw=="
    job = video_client.submit(
        "Keep the product UI legible while adding a slow cinematic camera move.",
        duration=12,
        aspect_ratio="9:16",
        resolution="720p",
        generate_audio=True,
        input_references=[{"type": "video_url", "video_url": {"url": reference}}],
        seed=42,
    )
    request = RECORDED[-1][2] or {}
    assert RECORDED[-1][:2] == ("POST", "/api/v1/videos")
    assert request["model"] == "bytedance/seedance-2.5"
    assert request["duration"] == 12
    assert request["input_references"][0]["video_url"]["url"] == reference
    assert job["id"] == "video_job_123"
    assert job["model"] == "bytedance/seedance-2.5"


def test_status_and_content_resume_the_same_job(local_openrouter) -> None:
    result = video_client.status("video_job_123")
    body, media_type = video_client.content("video_job_123")
    assert result["status"] == "completed"
    assert result["usage"]["cost"] == 0.25
    assert RECORDED[-2][1] == "/api/v1/videos/video_job_123"
    assert RECORDED[-1][1] == "/api/v1/videos/video_job_123/content"
    assert body == b"fake-mp4"
    assert media_type == "video/mp4"


@pytest.mark.parametrize("duration", [3, 31])
def test_duration_is_rejected_before_transport(monkeypatch, duration: int) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with pytest.raises(ValueError, match="duration"):
        video_client.submit("A valid prompt", duration=duration)


def test_reference_contract_rejects_private_and_malformed_urls() -> None:
    with pytest.raises(ValueError, match="public HTTPS"):
        video_client.validate_references([
            {"type": "video_url", "video_url": {"url": "http://127.0.0.1/private.mp4"}},
        ])
    with pytest.raises(ValueError, match="shape"):
        video_client.validate_references([
            {"type": "video_url", "image_url": {"url": "https://cdn.example/a.png"}},
        ])


def test_public_config_exposes_no_secret(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret")
    config = video_client.public_config()
    assert config["model"] == "bytedance/seedance-2.5"
    assert config["configured"] is True
    assert config["privacy"]["zeroDataRetention"] is False
    assert "super-secret" not in json.dumps(config)
