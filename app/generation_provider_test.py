import json
from copy import deepcopy
from pathlib import Path

import pytest

import art_direction
import server


ROOT = Path(__file__).resolve().parent.parent


def design_brief(tone: str) -> dict:
    return {
        "schemaVersion": "design-brief/1.0",
        "audience": {"primary": "Product teams", "task": "Choose the right product"},
        "tone": tone,
        "typePair": "russo-golos",
        "palette": {
            "background": {"lightness": 0.97, "chroma": 0.01, "hue": 250},
            "accent": {"lightness": 0.58, "chroma": 0.16, "hues": [250]},
        },
        "rhythm": {
            "sections": [
                {"purpose": "promise", "density": "airy"},
                {"purpose": "evidence", "density": "dense"},
                {"purpose": "action", "density": "balanced"},
            ],
            "risk": f"Use one {tone} compositional gesture",
        },
        "copyDeck": {"hero": "A specific product promise", "cta": "Start now", "proofs": ["Proof"]},
    }


def art_directions() -> list[dict]:
    return [
        {
            "id": direction_id,
            "label": label,
            "motivation": f"{label} fits the product task",
            "tradeoff": f"{label} reduces secondary emphasis",
            "designBrief": design_brief(tone),
        }
        for direction_id, label, tone in (
            ("editorial", "Editorial Focus", "editorial"),
            ("soft", "Soft Product", "soft-pastel"),
            ("industrial", "Industrial Grid", "industrial"),
        )
    ]


@pytest.fixture(autouse=True)
def _mock_art_direction(monkeypatch):
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: art_directions())


def test_generate_can_prepare_prompts_without_server_llm() -> None:
    response = server.generate(server.GenerateReq(brief="hero for a marketplace", count=2, prepareOnly=True))
    assert len(response["prompts"]) == 2
    assert response["prompts"][0]["messages"][0]["role"] == "system"
    assert "hero for a marketplace" in response["prompts"][0]["messages"][1]["content"]
    assert response["directions"] == [
        {key: item[key] for key in ("id", "label", "motivation", "tradeoff")}
        for item in art_directions()
    ]
    assert response["variantDirections"] == ["Editorial Focus", "Soft Product"]
    assert response["designBrief"]["tone"] == "editorial"
    assert '"tone": "editorial"' in response["prompts"][0]["messages"][0]["content"]
    assert "### exemplar: marketplace" in response["prompts"][0]["messages"][0]["content"]


def test_strict_prepare_prompt_identifies_reference_master(monkeypatch) -> None:
    from design_system import store

    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    document = {
        "id": "ds-prompt", "name": "Prompt kit", "revision": 1, "contentHash": "hash",
        "foundations": {}, "styleGuide": {},
        "components": {"list-item": {
            "componentKey": "list-item", "name": "List item", "category": "content",
            "origin": "user", "confirmed": True, "masterIr": fixture,
        }},
    }
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    reference = deepcopy(fixture)
    reference.setdefault("meta", {})["_dsMaster"] = {"systemId": "ds-prompt", "componentKey": "list-item"}

    response = server.generate(server.GenerateReq(
        brief="Карточка тарифа", count=1, prepareOnly=True, referenceIrs=[reference],
        designSystem={"systemId": "ds-prompt", "revision": 1, "usageMode": "strict"},
    ))
    prompt = response["prompts"][0]["messages"][1]["content"]
    assert "Референс — это мастер list-item" in prompt
    assert "результат обязан быть копией этого мастера с componentRef" in prompt


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


def test_generate_sanitizes_provider_meta_and_typography_aliases(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    fixture["meta"] = {"name": "Provider result", "pageType": "invented-runtime-field"}
    fixture["tree"][0]["children"][0]["children"][3]["size"] = "h1"

    monkeypatch.setattr(server.llm, "chat", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("server-side LLM must not be called for external provider outputs")
    ))
    response = server.generate(server.GenerateReq(
        brief="marketplace page", count=1, provider="codex", rawOutputs=[json.dumps(fixture)],
    ))

    result = response["variants"][0]
    assert result["meta"]["name"] == "Provider result"
    assert "pageType" not in result["meta"]
    assert result["meta"]["direction"]["name"] == "Editorial Focus"
    assert result["tree"][0]["children"][0]["children"][3]["size"] == "display"
    assert server.validate_ir(result) == []


def test_browser_generate_migrates_every_saved_provider_to_openai(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    seen: list[str] = []

    def fake_call(provider, *_args, **_kwargs):
        seen.append(provider)
        return json.dumps(deepcopy(fixture))

    monkeypatch.setattr(server.llm, "chat", fake_call)
    # Ретро-провайдеры (kimi/glm/zai/grok/openrouter/auto) схлопываются в Sol;
    # codex и claude — консольные аккаунты (cli_llm) и проходят как есть.
    for requested in ("kimi", "openai", "glm", "zai", "grok", "openrouter", "auto"):
        response = server.generate(server.GenerateReq(brief="marketplace hero", count=1, provider=requested))
        assert len(response["variants"]) == 1
        assert seen.pop() == "openai"
    for requested in ("codex", "claude"):
        response = server.generate(server.GenerateReq(brief="marketplace hero", count=1, provider=requested))
        assert len(response["variants"]) == 1
        assert seen.pop() == requested


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


def test_retired_provider_options_are_rejected() -> None:
    import llm_client as llm
    for provider in ("kimi", "zai", "grok"):
        request = llm.ChatRequest(
            messages=[{"role": "user", "content": "hi"}],
            provider=provider,
            provider_options={provider: {"model": "hijack", "temperature": 0}},
        )
        issues = " ".join(request.validate())
        assert "retired providers" in issues, provider


def test_generate_assigns_distinct_or_selected_direction(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    raw = json.dumps(fixture)

    all_response = server.generate(server.GenerateReq(
        brief="marketplace page", count=2, rawOutputs=[raw, raw], selectedDirection="all",
    ))
    assert all_response["variantDirections"] == ["Editorial Focus", "Soft Product"]
    assert all_response["generationLog"]["direction"]["selected"] == "all"
    assert all_response["variants"][0]["meta"]["direction"]["name"] == "Editorial Focus"
    assert all_response["variants"][1]["meta"]["direction"]["name"] == "Soft Product"

    selected_response = server.generate(server.GenerateReq(
        brief="marketplace page", count=2, rawOutputs=[raw, raw], selectedDirection="industrial",
    ))
    assert selected_response["variantDirections"] == ["Industrial Grid", "Industrial Grid"]
    assert selected_response["generationLog"]["direction"]["selected"] == "industrial"


def test_two_phase_generate_only_creates_art_direction_during_prepare(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    generate_flags = []

    def fake_direction(*_args, **kwargs):
        generate_flags.append(kwargs["generate_if_missing"])
        return art_directions()

    monkeypatch.setattr(art_direction, "create_design_brief", fake_direction)
    prepared = server.generate(server.GenerateReq(
        brief="marketplace page", count=2, prepareOnly=True, selectedDirection="industrial",
    ))
    applied = server.generate(server.GenerateReq(
        brief="marketplace page", count=2, rawOutputs=[json.dumps(fixture), json.dumps(fixture)],
        selectedDirection="industrial",
    ))

    assert generate_flags == [True, False]
    assert prepared["variantDirections"] == ["Industrial Grid", "Industrial Grid"]
    assert [item["meta"]["direction"]["name"] for item in applied["variants"]] == [
        "Industrial Grid", "Industrial Grid",
    ]


def test_generate_degrades_when_fast_art_direction_fails(monkeypatch) -> None:
    fixture = json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    stages = []
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: (
        _ for _ in ()).throw(RuntimeError("fast model unavailable")))
    monkeypatch.setattr(server.run_registry, "stage", lambda _run_id, stage, *_args, **_kwargs: stages.append(stage))

    response = server.generate(server.GenerateReq(
        brief="marketplace page", count=1, rawOutputs=[json.dumps(fixture)], runId="art-test",
    ))

    assert response["variants"]
    assert response["directions"] == []
    assert response["variantDirections"] == [""]
    assert response["generationLog"]["direction"]["degraded"] is True
    assert "fast model unavailable" in response["generationLog"]["direction"]["error"]
    assert "art-direction" in stages
