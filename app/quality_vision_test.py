"""Vision-backed Quality Pass contracts."""
from __future__ import annotations

import copy
import base64
import io
import json

import pytest
from PIL import Image

import server
import api.quality as quality_api

from quality_test_fixtures import QUALITY_IR as BASE_IR


@pytest.fixture(autouse=True)
def isolated_evidence_cache(monkeypatch):
    cache = {}
    monkeypatch.setattr(server.cache_store, "get", lambda kind, key: copy.deepcopy(cache.get((kind, key))))
    monkeypatch.setattr(server.cache_store, "put", lambda kind, key, value: cache.__setitem__((kind, key), copy.deepcopy(value)))
    return cache


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
    monkeypatch.setattr(quality_api, "render_png", lambda ir, width=1440, **_kw: b"\x89PNG\r\n")

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
    assert "Task and information architecture: 25" in calls[0]["prompt"]
    assert "Justified visual decisions: 10" in calls[0]["prompt"]
    assert "Лендинг кофейни" in calls[0]["prompt"]
    assert "Главное доказательство" in calls[0]["system"]


def test_quality_pass_repair_rejudges_a_fresh_screenshot(monkeypatch):
    render_calls = []
    monkeypatch.setattr(
        quality_api, "render_png", lambda ir, width=1440, **_kw: render_calls.append(copy.deepcopy(ir)) or b"png",
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
    monkeypatch.setattr(server.qualitygate, "check", lambda ir, **kwargs: [])
    stages = []
    monkeypatch.setattr(server.run_registry, "stage", lambda run_id, stage, message, **kw: stages.append(stage))

    result = server._quality_pass(
        server.QualityPassReq(ir=copy.deepcopy(BASE_IR), brief="brief"), "vision-2")

    assert result["passed"] is True
    assert result["min_score"] == 80
    assert result["initial_scorecard"]["score"] == 61
    assert result["scorecard"]["score"] == 91
    assert len(render_calls) == 4
    assert stages == ["render", "judge", "repair", "rejudge", "render", "judge"]


def test_quality_pass_default_threshold_is_80():
    assert server.QualityPassReq(ir=copy.deepcopy(BASE_IR)).min_score == 80


def test_component_mode_uses_component_rubric_and_skips_page_rules(monkeypatch):
    component = copy.deepcopy(BASE_IR)
    component["tree"] = [{"type": "source-block", "children": [{"type": "text", "text": "Readable"}]}]
    monkeypatch.setattr(quality_api, "render_png", lambda *args, **kwargs: b"png")
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


@pytest.mark.parametrize("transport", ["desktop", "server"])
def test_repair_uses_first_screens_from_the_judged_long_page(monkeypatch, transport):
    render_calls = []

    def render(ir, width, **kwargs):
        render_calls.append((width, kwargs["viewport"]))
        screenshot = Image.new("RGB", (width, 3200 if width == 1440 else 4800), "blue")
        screenshot.paste("red" if width == 1440 else "lime", (0, 0, width, 900))
        out = io.BytesIO()
        screenshot.save(out, "PNG")
        return out.getvalue()

    monkeypatch.setattr(quality_api, "render_png", render)
    judged_images = []
    if transport == "desktop":
        step = quality_api.quality_pass_codex_step(quality_api.QualityPassCodexReq(ir=copy.deepcopy(BASE_IR), visualReview=True))
        judged_images = [part["image_url"]["url"] for part in step["pending"]["messages"][1]["content"] if part["type"] == "image_url"]
    else:
        def judge(provider, images, *args, **kwargs):
            judged_images.extend(images)
            return _score(70, "needs_repair")
        monkeypatch.setattr(server.llm, "chat_vision", judge)
        quality_api._quality_scorecard(copy.deepcopy(BASE_IR), "")

    selected = quality_api._repair_images(BASE_IR, "")
    assert len(judged_images) > 4 and len(selected) == 2
    assert all(image in judged_images for image in selected)
    for url, width, color in zip(selected, (1440, 390), ((255, 0, 0), (0, 255, 0)), strict=True):
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as screenshot:
            assert screenshot.size == (width, 900)
            assert screenshot.getpixel((10, 10)) == color
    messages, error = quality_api._quality_repair_messages(
        BASE_IR, {"score": 70, "repair_instruction": "repair"}, "", images=selected)
    assert error is None
    assert [part["image_url"]["url"] for part in messages[1]["content"] if part["type"] == "image_url"] == selected
    assert render_calls == [(1440, "desktop"), (390, "mobile")]


def test_legacy_flat_visual_cache_is_refreshed_without_guessing_mobile_index(monkeypatch, isolated_evidence_cache):
    key = quality_api._quality_visual_key(BASE_IR, "")
    isolated_evidence_cache[("generator-visual", key)] = {"images": ["old-first", "old-bottom"], "widths": [1440, 390]}
    assert quality_api._repair_images(BASE_IR, "") == []
    monkeypatch.setattr(quality_api, "render_png", lambda ir, width, **kw: str(width).encode())
    monkeypatch.setattr(quality_api, "_judge_images", lambda screenshot: [screenshot.decode() + "-first", screenshot.decode() + "-bottom"])
    quality_api._quality_desktop_messages(BASE_IR, "", True)
    assert quality_api._repair_images(BASE_IR, "") == ["1440-first", "390-first"]
