"""Seedance-only generative-video gateway contract checks without paid calls."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import video_client


RECORDED: list[tuple[str, str, dict | None]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECORDED.append(("POST", self.path, body))
        self._send({"id": "job_test_123", "polling_url": "/api/v1/videos/job_test_123", "status": "pending"}, 202)

    def do_GET(self):
        RECORDED.append(("GET", self.path, None))
        self._send({"id": "job_test_123", "status": "completed", "unsigned_urls": ["https://cdn.example/video.mp4"], "usage": {"cost": 0.25}})

    def _send(self, payload: dict, status: int = 200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def check(name: str, condition: bool, extra="") -> None:
    if not condition:
        raise AssertionError(f"{name}: {extra}")
    print(f"[OK] {name}")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original_url = video_client.VIDEO_API_URL
    video_client.VIDEO_API_URL = f"http://127.0.0.1:{server.server_address[1]}/api/v1/videos"
    os.environ["SEEDANCE_API_KEY"] = "test-key"
    try:
        check("Studio video route uses Seedance 2.0", video_client.model_for_tier("studio") == "bytedance/seedance-2.0")
        check("Draft video route uses Seedance 2.0 Fast", video_client.model_for_tier("draft") == "bytedance/seedance-2.0-fast")
        check("Cinematic route stays on Seedance", video_client.model_for_tier("cinematic") == "bytedance/seedance-2.0")
        job = video_client.submit(
            "A precise product insert",
            tier="studio",
            duration=5,
            aspect_ratio="9:16",
            references=["https://cdn.example/reference.png"],
            seed=42,
        )
        request = RECORDED[-1][2] or {}
        check("Submit uses dedicated Seedance videos endpoint", RECORDED[-1][1] == "/api/v1/videos")
        check("Submit sends normalized model and controls", request.get("model") == "bytedance/seedance-2.0" and request.get("duration") == 5 and request.get("seed") == 42, str(request))
        check("Reference image uses Seedance input_references", request.get("input_references", [])[0]["image_url"]["url"].startswith("https://"), str(request))
        check("Gateway returns model metadata", job.get("tier") == "studio" and job.get("model") == "bytedance/seedance-2.0", str(job))
        result = video_client.status(job["id"])
        check("Status polling is pinned to the Seedance job path", RECORDED[-1][1].endswith("/job_test_123") and result.get("status") == "completed", str(result))
        try:
            video_client.status("../models")
            raise AssertionError("unsafe job id accepted")
        except ValueError:
            print("[OK] unsafe video job ids are rejected")
    finally:
        video_client.VIDEO_API_URL = original_url
        server.shutdown()
    print("ALL VIDEO CLIENT CHECKS PASSED")


if __name__ == "__main__":
    main()
