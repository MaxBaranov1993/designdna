from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_client as llm


def test_sol_efforts_are_the_only_valid_choices():
    for effort in ("medium", "high", "max"):
        assert llm.ChatRequest(messages=[{"role": "user", "content": "hi"}], reasoning_effort=effort).validate() == []
    assert "reasoning_effort" in " ".join(
        llm.ChatRequest(messages=[{"role": "user", "content": "hi"}], reasoning_effort="low").validate()
    )


def test_retired_selection_is_migrated_and_reported():
    request = llm.ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        provider="grok",
        model="grok/grok-4.6",
        temperature=0.7,
    )
    payload, dropped = request.to_responses_payload()
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["reasoning"] == {"effort": "medium"}
    assert {item["field"] for item in dropped} == {"provider", "model", "temperature"}


def test_function_tools_are_flattened_for_responses():
    request = llm.ChatRequest(
        messages=[{"role": "user", "content": "list"}],
        tools=[{"type": "function", "function": {
            "name": "list_files", "description": "List files",
            "parameters": {"type": "object", "properties": {}},
        }}],
        tool_choice={"name": "list_files"},
    )
    payload, _ = request.to_responses_payload()
    assert payload["tools"][0]["name"] == "list_files"
    assert "function" not in payload["tools"][0]
    assert payload["tool_choice"] == {"type": "function", "name": "list_files"}


def test_non_openai_transport_is_rejected_when_called_directly():
    request = llm.ChatRequest(messages=[{"role": "user", "content": "hi"}])
    try:
        request.assert_supported("kimi")
    except ValueError as error:
        assert "retired provider" in str(error)
    else:
        raise AssertionError("retired provider must be rejected")
