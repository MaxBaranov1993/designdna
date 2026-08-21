import json
from copy import deepcopy
from pathlib import Path

import server


ROOT = Path(__file__).resolve().parent.parent


def test_generate_can_prepare_prompts_without_server_llm() -> None:
    response = server.generate(server.GenerateReq(brief="hero for a marketplace", count=2, prepareOnly=True))
    assert len(response["prompts"]) == 2
    assert response["prompts"][0]["messages"][0]["role"] == "system"
    assert "hero for a marketplace" in response["prompts"][0]["messages"][1]["content"]


def test_generate_finalizes_external_provider_outputs_without_server_llm(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))

    def fail_chat(*_args, **_kwargs):
        raise AssertionError("server-side LLM must not be called for external provider outputs")

    monkeypatch.setattr(server.llm, "chat", fail_chat)
    response = server.generate(server.GenerateReq(
        brief="hero for a marketplace",
        count=1,
        provider="codex",
        rawOutputs=[json.dumps(fixture)],
    ))
    assert len(response["variants"]) == 1
    assert response["variants"][0]["version"] == "1.1"
    assert server.validate_ir(response["variants"][0]) == []


def test_browser_generate_honors_direct_api_provider_and_maps_codex_to_auto(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    seen: list[str] = []

    def fake_call(provider, *_args, **_kwargs):
        seen.append(provider)
        return deepcopy(fixture), None

    monkeypatch.setattr(server, "call_llm_ir", fake_call)
    for requested, expected in (
        ("kimi", "kimi"),
        ("openai", "openai"),
        ("glm", "glm"),
        ("codex", "auto"),
        ("openrouter", "auto"),
        ("auto", "auto"),
    ):
        response = server.generate(server.GenerateReq(brief="marketplace hero", count=1, provider=requested))
        assert len(response["variants"]) == 1
        assert seen.pop() == expected


def test_generate_applies_locked_dna_to_model_inline_styles(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    button = fixture["tree"][0]["children"][0]["children"][4]["children"][1]
    assert button["type"] == "button"
    button["style"] = {"background": "#111111", "color": "#ffffff", "borderRadius": 2}
    tokens = {
        "mode": "light",
        "color": {
            "primary": "#f97316", "secondary": "#7c3aed", "accent": "#f59e0b",
            "background": "#ffffff", "surface": "#fff7ed", "text": "#17201d",
            "textMuted": "#64748b", "border": "#fed7aa",
        },
        "font": {
            "display": {"family": "Manrope", "weight": 800},
            "body": {"family": "Inter", "weight": 400}, "scale": "default",
        },
        "radius": {"card": "lg", "button": "full", "input": "md"},
        "spacing": {"section": "lg", "container": "default"},
        "shadow": "sm",
    }
    _, expanded = server._locked_generation_dna(tokens)
    tokens["semantic"] = expanded["semantic"]
    tokens["semantic"]["buttonRadius"] = 9999  # DOM-capture pill sentinel

    monkeypatch.setattr(server.llm, "chat", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("server-side LLM must not be called for external provider outputs")
    ))
    response = server.generate(server.GenerateReq(
        brief="marketplace card", count=1, provider="codex",
        tokens=tokens, rawOutputs=[json.dumps(fixture)],
    ))

    result = response["variants"][0]
    styled_button = result["tree"][0]["children"][0]["children"][4]["children"][1]
    assert result["tokens"]["color"]["primary"] == "#f97316"
    assert styled_button["style"]["background"] == "#f97316"
    assert styled_button["style"]["borderRadius"] == 1000
    assert styled_button["styleBindings"]["background"]["token"] == "semantic.primary"
    assert server.validate_ir(result) == []
