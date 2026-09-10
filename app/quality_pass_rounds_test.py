"""Quality Pass в несколько раундов: чинит по всем замечаниям, пока не пройдёт порог, отдаёт лучший IR."""
import copy
import json

import server
from api import quality
from test_qualitygate import BASE_IR


def _judge(score: int, severity: str | None = "major", verdict: str | None = None) -> str:
    issues = [] if severity is None else [{
        "category": "hierarchy", "severity": severity, "path": "tree.0",
        "problem": f"проблема при {score}", "instruction": f"почини до {score}",
    }]
    return json.dumps({"score": score, "verdict": verdict or ("pass" if score >= 80 and not issues else "needs_repair"),
                       "summary": "x", "issues": issues, "repair_instruction": "почини"})


def _repaired(tag: str) -> str:
    ir = copy.deepcopy(BASE_IR)
    ir.setdefault("meta", {})["name"] = tag
    return json.dumps(ir, ensure_ascii=False)


def _forbid_server_llm(monkeypatch):
    monkeypatch.setattr(server.llm, "chat", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("server LLM called")))


def _step(outputs, **extra):
    return server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=copy.deepcopy(BASE_IR), brief="Лендинг", outputs=outputs, **extra))


def test_codex_step_runs_a_second_round_when_the_first_repair_is_not_enough(monkeypatch):
    _forbid_server_llm(monkeypatch)
    low, mid, high = _judge(50), _judge(70), _judge(90, None)
    step = _step({"judge": low, "repairs": [_repaired("r1")], "rejudges": [mid]})
    assert step["pending"]["stage"] == "repair" and step["pending"]["round"] == 2
    prompt = step["pending"]["messages"][1]["content"]
    assert "раунд 2" in prompt and "Прошлые раунды: раунд 1: 70/100" in prompt
    assert "[major] tree.0: проблема при 70 → почини до 70" in prompt
    step = _step({"judge": low, "repairs": [_repaired("r1"), _repaired("r2")], "rejudges": [mid]})
    assert step["pending"]["stage"] == "rejudge" and step["pending"]["round"] == 2
    final = _step({"judge": low, "repairs": [_repaired("r1"), _repaired("r2")], "rejudges": [mid, high]})
    assert "pending" not in final and final["passed"] is True
    assert final["ir"]["meta"]["name"] == "r2"
    assert [item["score"] for item in final["repair"]["rounds"]] == [70, 90]
    assert final["scorecard"]["score"] == 90 and final["initial_scorecard"]["score"] == 50


def test_codex_step_keeps_the_best_round_and_stops_without_progress(monkeypatch):
    _forbid_server_llm(monkeypatch)
    low, better, worse = _judge(50), _judge(72), _judge(60)
    final = _step({"judge": low, "repairs": [_repaired("r1"), _repaired("r2")], "rejudges": [better, worse]})
    assert "pending" not in final  # второй раунд не улучшил — стоп, третьего не просим
    assert final["ir"]["meta"]["name"] == "r1" and final["scorecard"]["score"] == 72
    assert final["passed"] is False and final["repair"]["applied"] is True
    assert [item["score"] for item in final["repair"]["rounds"]] == [72, 60]


def test_codex_step_respects_max_rounds_and_legacy_single_round_fields(monkeypatch):
    _forbid_server_llm(monkeypatch)
    low, mid = _judge(50), _judge(70)
    final = _step({"judge": low, "repair": _repaired("r1"), "rejudge": mid}, max_rounds=1)
    assert "pending" not in final and final["ir"]["meta"]["name"] == "r1" and final["scorecard"]["score"] == 70
    assert final["repair"]["rounds"][0]["round"] == 1
    assert _step({"judge": low, "repairs": [_repaired("r1")], "rejudges": [mid, mid]}).status_code == 422


def test_repair_prompt_lists_every_issue_and_the_design_system(monkeypatch):
    scorecard = {"score": 45, "verdict": "needs_repair", "issues": [
        {"category": "content", "severity": "minor", "path": "tree.2", "problem": "мелкое", "instruction": "поправь"},
        {"category": "layout", "severity": "critical", "path": "tree.0", "problem": "наезд", "instruction": "раздвинь"},
    ], "repair_instruction": "общая"}
    document = {"id": "ds-x", "revision": 1, "contentHash": "h", "components": {}, "styleGuide": {},
                "foundations": {"colors": {"semantic": {"primary": "#5b6cff", "text": "#f2f0ea", "background": "#0a0a0e"}},
                                "typography": {"families": ["Hanken Grotesk"]}}}
    from design_system import store
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (copy.deepcopy(document), None))
    messages, error = quality._quality_repair_messages(
        copy.deepcopy(BASE_IR), scorecard, "Лендинг", "landing", round_index=1, min_score=80,
        design_system={"systemId": "ds-x", "revision": 1, "usageMode": "extend"},
        images=["data:image/jpeg;base64,AAAA"])
    assert error is None
    parts = messages[1]["content"]
    assert isinstance(parts, list) and parts[1]["type"] == "image_url"
    text = parts[0]["text"]
    assert text.index("[critical] tree.0: наезд → раздвинь") < text.index("[minor] tree.2: мелкое → поправь")
    assert "Общая инструкция судьи: общая" in text and "Текущая оценка 45/100, порог 80" in text
    assert "DESIGN SYSTEM COMPILED PROFILE" in text and "Скриншоты текущего состояния" in text
    empty, empty_error = quality._quality_repair_messages(copy.deepcopy(BASE_IR), {"score": 90, "issues": []}, "x")
    assert empty is None and "не дал инструкций" in empty_error


def test_server_quality_pass_loops_rounds(monkeypatch):
    calls: list[str] = []
    judge_scores = iter([55, 68, 88])

    def fake_chat(provider, messages, temperature, **kwargs):
        role = kwargs.get("role")
        calls.append(role)
        if role == "quality_judge":
            score = next(judge_scores)
            return _judge(score, None if score >= 80 else "major")
        if role == "quality_repair":
            return _repaired(f"round-{calls.count('quality_repair')}")
        raise AssertionError(role)

    monkeypatch.setattr(server.llm, "chat", fake_chat)
    monkeypatch.setattr(server.llm, "chat_vision", lambda provider, images, prompt, system, temperature, **kwargs: fake_chat(provider, [], temperature, role="quality_judge"))
    monkeypatch.setattr(quality, "render_png", lambda *args, **kwargs: b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(quality, "_judge_images", lambda screenshot: ["data:image/png;base64,AA=="])
    result = server.quality_pass(server.QualityPassReq(ir=copy.deepcopy(BASE_IR), brief="Лендинг", min_score=80))
    assert calls == ["quality_judge", "quality_repair", "quality_judge", "quality_repair", "quality_judge"]
    assert result["passed"] is True and result["ir"]["meta"]["name"] == "round-2"
    assert [item["score"] for item in result["repair"]["rounds"]] == [68, 88]
