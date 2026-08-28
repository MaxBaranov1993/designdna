from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_client


def test_every_role_is_fixed_to_sol(monkeypatch):
    monkeypatch.setenv("LLM_MODELS_GENERATOR", "kimi/k3")
    assert llm_client.PROVIDERS == {
        "openai": {"url": "https://api.openai.com/v1/responses", "env": "OPENAI_API_KEY"},
    }
    assert all(models == ["openai/gpt-5.6-sol"] for models in llm_client.ROUTING.values())
    assert llm_client.routing_models("generator") == ["openai/gpt-5.6-sol"]


def test_chat_posts_responses_payload_and_returns_text(monkeypatch):
    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    def fake_post(url, payload, key, timeout, extra_headers=None):
        seen.update(url=url, payload=payload, key=key, timeout=timeout)
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    monkeypatch.setattr(llm_client, "_post_json", fake_post)
    result = llm_client.chat("kimi", [{"role": "user", "content": "hi"}], 0.8, reasoning_effort="high")
    assert result == "ok"
    assert seen["url"].endswith("/v1/responses")
    assert seen["payload"]["model"] == "gpt-5.6-sol"
    assert seen["payload"]["reasoning"] == {"effort": "high"}
    assert "temperature" not in seen["payload"]


def test_vision_uses_responses_input_image(monkeypatch):
    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    def fake_post(_url, payload, _key, _timeout, extra_headers=None):
        seen.update(payload)
        return {"output_text": "described", "output": []}

    monkeypatch.setattr(llm_client, "_post_json", fake_post)
    result = llm_client.chat_vision("auto", "data:image/png;base64,AAAA", "describe", "system")
    assert result == "described"
    assert seen["instructions"] == "system"
    assert seen["input"][0]["content"][1]["type"] == "input_image"


def test_extract_json_handles_fences_and_prose():
    assert json.loads(llm_client.extract_json("```json\n{\"a\":1}\n```")) == {"a": 1}
    assert json.loads(llm_client.extract_json("answer: [1,2] done")) == [1, 2]
