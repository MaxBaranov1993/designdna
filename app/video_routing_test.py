"""Public model routing and no-spend API boundary checks."""
from __future__ import annotations

from fastapi.testclient import TestClient

import llm_client
from server import app


def check(name: str, condition: bool, extra="") -> None:
    if not condition:
        raise AssertionError(f"{name}: {extra}")
    print(f"[OK] {name}")


def main() -> None:
    with TestClient(app) as client:
        config = client.get("/api/config").json()
        models = config.get("models", {})
        check("Generator primary is Claude Opus 5", models.get("generator") == "anthropic/claude-opus-5", str(models))
        check("Motion Director route reserves Claude Opus 5", models.get("motionDirector") == "anthropic/claude-opus-5", str(models))
        check("Studio generative video uses Seedance 2.0", models.get("video", {}).get("studio") == "bytedance/seedance-2.0", str(models))
        check("Generator routing agrees with public config", llm_client.routing_models("generator")[0] == models.get("generator"))

        unconfirmed = client.post("/api/ai-video/generate", json={"prompt": "A product insert"})
        check("Paid video generation requires confirmation", unconfirmed.status_code == 409, unconfirmed.text)
        bad_tier = client.post("/api/ai-video/generate", json={
            "prompt": "A product insert", "tier": "unknown", "confirmed": True,
        })
        check("Unknown video tiers fail before any paid call", bad_tier.status_code == 422, bad_tier.text)
        unsafe_job = client.get("/api/ai-video/..%2Fmodels")
        check("Unsafe polling IDs are rejected", unsafe_job.status_code in {404, 422}, unsafe_job.text)
    print("ALL VIDEO ROUTING CHECKS PASSED")


if __name__ == "__main__":
    main()
