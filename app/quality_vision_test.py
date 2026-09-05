"""Vision-backed Quality Pass contracts."""
from __future__ import annotations

import copy
import json

import run_registry
import server
from test_qualitygate import BASE_IR


def _score(score: int, verdict: str, issues: list | None = None) -> str:
    return json.dumps({
        "score": score,
        "verdict": verdict,
        "summary": "visual result",
        "issues": issues or [],
        "repair_instruction": "increase hero contrast" if issues else "",
    })


def test_quality_scorecard_sends_rendered_png_and_rubric_to_vision(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "render_png", lambda ir, width=1440, **_kw: b"\x89PNG\r\n")

    def fake_vision(provider, image_data_url, text_prompt, system_prompt="", temperature=0.2,
                    timeout=None, role="vision", reasoning_effort=None):
        calls.append({
            "provider": provider, "image": image_data_url, "prompt": text_prompt,
            "system": system_prompt, "temperature": temperature, "role": role,
        })
        return _score(88, "pass")

    monkeypatch.setattr(server.llm, "chat_vision", fake_vision)
    stages = []
    monkeypatch.setattr(server.run_registry, "stage", lambda run_id, stage, message, **kw: stages.append(stage))

    result = server._quality_scorecard(copy.deepcopy(BASE_IR), "Лендинг кофейни", "vision-1")

    assert result["score"] == 88
    assert result["model_route"] == "LLM vision / quality_judge"
    assert stages == ["render", "judge"]
    assert calls[0]["image"][0].startswith("data:image/png;base64,iVBORw0K")
    assert calls[0]["role"] == "quality_judge"
    assert "Иерархия" in calls[0]["prompt"]
    assert "slop-тропов" in calls[0]["prompt"]
    assert "Лендинг кофейни" in calls[0]["prompt"]
    assert "Главное доказательство" in calls[0]["system"]


def test_quality_pass_repair_rejudges_a_fresh_screenshot(monkeypatch):
    render_calls = []
    monkeypatch.setattr(
        server, "render_png", lambda ir, width=1440, **_kw: render_calls.append(copy.deepcopy(ir)) or b"png",
    )
    answers = iter([
        _score(61, "needs_repair", [{
            "category": "hierarchy", "severity": "major", "path": "tree.0",
            "problem": "weak hero", "instruction": "increase hero contrast",
        }]),
        _score(91, "pass"),
    ])
    monkeypatch.setattr(server.llm, "chat_vision", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(
        server.llm, "chat",
        lambda *args, **kwargs: json.dumps(BASE_IR, ensure_ascii=False),
    )
    monkeypatch.setattr(server.qualitygate, "check", lambda ir: [])
    stages = []
    monkeypatch.setattr(server.run_registry, "stage", lambda run_id, stage, message, **kw: stages.append(stage))

    result = server._quality_pass(
        server.QualityPassReq(ir=copy.deepcopy(BASE_IR), brief="brief"), "vision-2")

    assert result["passed"] is True
    assert result["min_score"] == 80
    assert result["initial_scorecard"]["score"] == 61
    assert result["scorecard"]["score"] == 91
    assert len(render_calls) == 2
    assert stages == ["render", "judge", "repair", "rejudge", "render", "judge"]


def test_quality_pass_default_threshold_is_80():
    assert server.QualityPassReq(ir=copy.deepcopy(BASE_IR)).min_score == 80


def test_component_mode_uses_component_rubric_and_skips_page_rules(monkeypatch):
    component = copy.deepcopy(BASE_IR)
    component["tree"] = [{"type": "source-block", "children": [{"type": "text", "text": "Readable"}]}]
    monkeypatch.setattr(server, "render_png", lambda *args, **kwargs: b"png")
    calls = []
    monkeypatch.setattr(server.llm, "chat_vision", lambda provider, images, prompt, system, *args, **kwargs:
                        calls.append((prompt, system)) or _score(80, "pass"))
    monkeypatch.setattr(server.qualitygate, "check", lambda ir: [
        {"rule": "single-h1", "severity": "error"},
        {"rule": "free-overlap", "severity": "error"},
    ])
    scorecard = server._quality_scorecard(component, "component")
    assert scorecard["mode"] == "component"
    assert "not a complete page" in calls[0][0]
    violations = server._quality_violations(component)
    assert [item["rule"] for item in violations] == ["free-overlap"]
