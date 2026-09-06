import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app
from video_models import catalogue
from video_story import build_pages
from video_story_fixtures import pages_fixture, plan_fixture
import llm_client


def test_catalog_uses_visible_account_models_and_supported_efforts(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "test-model", "display_name": "Test", "visibility": "list", "supported_reasoning_levels": [{"effort": "high"}, {"effort": "ultra"}], "default_reasoning_level": "high"},
        {"slug": "hidden", "visibility": "hide", "supported_reasoning_levels": [{"effort": "high"}]},
    ]}))
    result = catalogue()
    assert result["source"] == "codex-cache"
    assert result["models"][0]["efforts"] == ["high", "ultra"]
    assert [m["id"] for m in result["models"]] == ["test-model", "opus"]


def test_selected_model_and_effort_reach_account_transport():
    with patch("llm_client.cli_llm.chat", return_value="ok") as cli:
        assert llm_client.chat("codex", [{"role": "user", "content": "synthetic"}], 0.2, model="gpt-6-astra", reasoning_effort="ultra") == "ok"
    assert cli.call_args.kwargs["model"] == "gpt-6-astra"
    assert cli.call_args.kwargs["effort"] == "ultra"


def test_video_api_preserves_explicit_selection_and_rejects_cross_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    timeline = build_pages(pages_fixture(), {"duration": 8000})
    with TestClient(app) as client, patch("video_context.prepare_context", return_value=[]), patch("video_story.llm.chat", return_value=json.dumps(plan_fixture())) as chat:
        response = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "Сценарий", "provider": "codex", "model": "gpt-6-astra", "effort": "high", "require_llm": True})
        assert response.status_code == 200, response.text
        assert chat.call_args.kwargs["model"] == "gpt-6-astra"
        assert chat.call_args.kwargs["reasoning_effort"] == "high"
        chat.reset_mock()
        response = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "Сценарий", "provider": "claude", "model": "gpt-6-astra", "effort": "high"})
        assert response.status_code == 422
        chat.assert_not_called()


def test_missing_catalog_has_harness_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert [m["id"] for m in catalogue()["models"]] == ["gpt-5.6-sol", "gpt-6-astra", "opus"]

