"""Account-selected video editing must never substitute keyword presets for AI."""
from unittest.mock import patch

from fastapi.testclient import TestClient
from ir.timeline import build
from server import app


def document():
    return build({"version": "1.1", "frame": {"width": 1440}, "tree": [
        {"id": "hero", "type": "hero", "props": {"heading": "Разместить объявление"}},
    ]}, {"duration": 8000})


def test_account_failure_is_visible_and_does_not_fallback():
    with TestClient(app) as client, patch("timeline_director.plan_from_llm", side_effect=RuntimeError("account disconnected")), patch("timeline_director.plan_from_prompt") as fallback:
        response = client.post("/api/timeline/assist", json={
            "timeline": document(), "prompt": "Приблизь страницу", "provider": "codex", "require_llm": True,
        })
    assert response.status_code == 422
    assert "Connections" in response.json()["error"]
    fallback.assert_not_called()


def test_explicit_account_request_calls_chosen_provider_even_with_default_flag_off():
    with TestClient(app) as client, patch("timeline_director.plan_from_llm", return_value=[
        {"preset": "zoom-in", "layers": "*", "start": 0, "duration": 0.5},
    ]) as planner:
        response = client.post("/api/timeline/assist", json={
            "timeline": document(), "prompt": "Приблизь страницу", "provider": "claude", "effort": "high", "require_llm": True,
        })
    assert response.status_code == 200, response.text
    assert response.json()["planSource"] == "llm"
    assert planner.call_args.kwargs == {"provider": "claude", "effort": "high"}


def test_empty_account_plan_does_not_fallback():
    with TestClient(app) as client, patch("timeline_director.plan_from_llm", return_value=[]), patch("timeline_director.plan_from_prompt") as fallback:
        response = client.post("/api/timeline/assist", json={
            "timeline": document(), "prompt": "Приблизь страницу", "provider": "codex", "require_llm": True,
        })
    assert response.status_code == 422
    fallback.assert_not_called()
