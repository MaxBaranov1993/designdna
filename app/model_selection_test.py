"""Chosen models must reach the wire; no network or credentials required."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_client as llm


@pytest.mark.parametrize("provider,model,expected", [
    ("openai", None, "gpt-5.6-sol"),
    ("astra", None, "gpt-6-astra"),
    ("openai", "gpt-6-astra", "gpt-6-astra"),
    ("openai", "openai/gpt-6-astra", "gpt-6-astra"),
])
def test_model_reaches_responses_and_diagnostics(monkeypatch, provider, model, expected):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    seen = {}

    def post(_url, payload, _key, _timeout):
        seen.update(payload)
        return {"status": "completed", "output_text": "ok"}

    monkeypatch.setattr(llm, "_post_json", post)
    result = llm.chat_envelope(llm.ChatRequest(
        provider=provider, model=model, messages=[{"role": "user", "content": "review"}],
        reasoning_effort="max",
    ))
    assert seen["model"] == expected
    assert seen["reasoning"] == {"effort": "max"}
    assert result["transport"]["model"] == expected
    assert result["transport"]["dropped"] == []


@pytest.mark.parametrize("provider,model", [("openai", None), ("astra", None), ("auto", "gpt-6-astra")])
def test_explicit_gpt_without_key_does_not_switch_to_cli(monkeypatch, provider, model):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm.cli_llm, "default_provider", lambda: pytest.fail("must not choose another model"))
    with pytest.raises(RuntimeError, match="OpenAI API key"):
        llm.chat(provider, [{"role": "user", "content": "review"}], 0.2, model=model)


def test_claude_keeps_explicit_choice_and_effort(monkeypatch):
    seen = {}

    def cli(provider, messages, **options):
        seen.update(provider=provider, **options)
        return "ok"

    monkeypatch.setattr(llm.cli_llm, "chat", cli)
    assert llm.chat("claude", [{"role": "user", "content": "review"}], 0.2, model="sonnet", reasoning_effort="high") == "ok"
    assert seen["provider"] == "claude"
    assert seen["model"] == "sonnet"
    assert seen["effort"] == "high"


def test_incomplete_result_is_rejected():
    with pytest.raises(RuntimeError, match="max_output_tokens"):
        llm._extract_response({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output_text": "partial"})


@pytest.mark.parametrize("provider", ["openai", "astra", "claude"])
def test_screenshot_fallback_preserves_provider_and_separates_cache(monkeypatch, provider):
    import server
    seen = {}
    monkeypatch.setattr(server.cache_store, "get", lambda namespace, key: seen.update(cache_key=key))
    monkeypatch.setattr(server.cache_store, "key_image", lambda image: "image-hash")

    def pipeline(**options):
        seen.update(options)
        raise RuntimeError("stop before image processing")

    monkeypatch.setattr(server, "reproduce_pipeline", pipeline)
    response = server.reproduce(server.ReproduceReq(image="test-image", provider=provider))
    assert response.status_code == 502
    assert seen["provider"] == provider
    assert seen["cache_key"] == f"image-hash:{provider}"
