"""Контрактные проверки Quality Pass без сети и без расхода токенов.

Запуск: .venv/Scripts/python app/quality_pass_test.py
"""
import copy
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server
from test_qualitygate import BASE_IR

FAILS = []


def check(name, condition, extra=""):
    print(f"[{'OK ' if condition else 'FAIL'}] {name}" + (f" — {extra}" if extra and not condition else ""))
    if not condition:
        FAILS.append(name)


def main():
    original_chat = server.llm.chat
    calls = []

    def fake_chat(provider, messages, temperature, **kwargs):
        calls.append(kwargs.get("role"))
        role = kwargs.get("role")
        if role == "quality_judge":
            # До repair — низкий балл, после — проходной.
            score = 60 if calls.count("quality_judge") == 1 else 93
            return json.dumps({
                "score": score,
                "verdict": "needs_repair" if score < 85 else "pass",
                "summary": "нужна более ясная иерархия" if score < 85 else "проверка пройдена",
                "issues": ([] if score >= 85 else [{
                    "category": "hierarchy", "severity": "major", "path": "tree.0",
                    "problem": "слабая иерархия", "instruction": "усиль главный заголовок",
                }]),
                "repair_instruction": "усиль главный заголовок" if score < 85 else "",
            })
        if role == "quality_repair":
            return json.dumps(BASE_IR, ensure_ascii=False)
        raise AssertionError("неожиданная роль: " + str(role))

    server.llm.chat = fake_chat
    try:
        source = copy.deepcopy(BASE_IR)
        result = server.quality_pass(server.QualityPassReq(ir=source, brief="Лендинг", min_score=85))
        check("repair применён", result["repair"]["applied"] is True, str(result["repair"]))
        check("rejudge выполнен", calls == ["quality_judge", "quality_repair", "quality_judge"], str(calls))
        check("финальный scorecard", result["passed"] is True and result["scorecard"]["score"] == 93, str(result))
        check("входной IR не мутирован", source == BASE_IR)

        calls.clear()
        result = server.quality_pass(server.QualityPassReq(ir=copy.deepcopy(BASE_IR), repair=False, min_score=85))
        check("без repair IR сохранён", result["ir"] == BASE_IR and result["repair"]["attempted"] is False)
        check("без repair один judge", calls == ["quality_judge"], str(calls))

        invalid = server.quality_pass(server.QualityPassReq(ir={"tree": []}))
        check("битый IR не отправляется в LLM", invalid.status_code == 422 and calls == ["quality_judge"], str(invalid))

        # Desktop Codex state machine prepares prompts and validates outputs,
        # but must never fall back to a server-side LLM call.
        server.llm.chat = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Codex step called server-side LLM")
        )
        low = json.dumps({
            "score": 60, "verdict": "needs_repair", "summary": "repair",
            "issues": [{"category": "hierarchy", "severity": "major", "path": "tree.0",
                        "problem": "weak", "instruction": "strengthen"}],
            "repair_instruction": "strengthen",
        })
        high = json.dumps({
            "score": 93, "verdict": "pass", "summary": "ok", "issues": [],
            "repair_instruction": "",
        })
        step = server.quality_pass_codex_step(server.QualityPassCodexReq(ir=copy.deepcopy(BASE_IR)))
        check("Codex step начинает с judge", step["pending"]["stage"] == "judge", str(step))
        step = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": low}
        ))
        check("Codex step продолжает repair", step["pending"]["stage"] == "repair", str(step))
        step = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": low, "repair": json.dumps(BASE_IR)}
        ))
        check("Codex step продолжает rejudge", step["pending"]["stage"] == "rejudge", str(step))
        step = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR),
            outputs={"judge": low, "repair": json.dumps(BASE_IR), "rejudge": high},
        ))
        check("Codex step завершает без серверного LLM", step["passed"] is True, str(step))
        check("scorecard сообщает Codex route",
              step["scorecard"]["model_route"] == "Codex app-server / quality_judge", str(step))

        # Битые, слишком большие и неконсистентные ответы Codex отклоняются
        # читаемо; при битом repair исходный граф не подменяется.
        bad = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": "не json"}))
        check("битый judge отклонён читаемо", getattr(bad, "status_code", None) == 502, str(bad))

        huge = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": "x" * (2 * 1024 * 1024 + 1)}))
        check("слишком большой ответ отклонён", getattr(huge, "status_code", None) == 413, str(huge))

        source = copy.deepcopy(BASE_IR)
        broken = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=source, outputs={"judge": low, "repair": "не json"}))
        check("битый repair сохраняет граф",
              broken["ir"] == BASE_IR and bool(broken["repair"]["error"])
              and broken["repair"]["applied"] is False and source == BASE_IR,
              str(broken.get("repair")))

        no_judge = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"repair": json.dumps(BASE_IR)}))
        check("repair без judge отклонён", getattr(no_judge, "status_code", None) == 422, str(no_judge))

        no_repair = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": low, "rejudge": high}))
        check("rejudge без repair отклонён", getattr(no_repair, "status_code", None) == 422, str(no_repair))

        unneeded = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": high, "repair": json.dumps(BASE_IR)}))
        check("repair без необходимости отклонён",
              getattr(unneeded, "status_code", None) == 422, str(unneeded))

        orphaned = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR),
            outputs={"judge": low, "repair": "не json", "rejudge": high}))
        check("rejudge без применённого repair отклонён",
              getattr(orphaned, "status_code", None) == 422, str(orphaned))

        direct = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs={"judge": high}))
        check("высокий score завершает без repair",
              direct["passed"] is True and direct["repair"]["attempted"] is False
              and direct["ir"] == BASE_IR, str(direct))
    finally:
        server.llm.chat = original_chat

    if FAILS:
        print("FAILURES:", ", ".join(FAILS))
        return 1
    print("ALL QUALITY PASS CHECKS PASSED")
    return 0



# --- pytest: focused tests тех же контрактов Codex-контура ---
LOW_JUDGE = json.dumps({
    "score": 60, "verdict": "needs_repair", "summary": "repair",
    "issues": [{"category": "hierarchy", "severity": "major", "path": "tree.0",
                "problem": "weak", "instruction": "strengthen"}],
    "repair_instruction": "strengthen",
})
HIGH_JUDGE = json.dumps({
    "score": 93, "verdict": "pass", "summary": "ok", "issues": [],
    "repair_instruction": "",
})


def _forbid_server_llm(monkeypatch):
    def fail_chat(*args, **kwargs):
        raise AssertionError("Codex step called server-side LLM")
    monkeypatch.setattr(server.llm, "chat", fail_chat)


def test_codex_step_pass_repair_rejudge_without_server_llm(monkeypatch):
    _forbid_server_llm(monkeypatch)
    step = server.quality_pass_codex_step(server.QualityPassCodexReq(ir=copy.deepcopy(BASE_IR)))
    assert step["pending"]["stage"] == "judge"
    assert step["pending"]["profile"] == "quality_judge"
    step = server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=copy.deepcopy(BASE_IR), outputs={"judge": LOW_JUDGE}))
    assert step["pending"]["stage"] == "repair"
    assert step["pending"]["profile"] == "quality_repair"
    step = server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=copy.deepcopy(BASE_IR), outputs={"judge": LOW_JUDGE, "repair": json.dumps(BASE_IR)}))
    assert step["pending"]["stage"] == "rejudge"
    step = server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=copy.deepcopy(BASE_IR),
        outputs={"judge": LOW_JUDGE, "repair": json.dumps(BASE_IR), "rejudge": HIGH_JUDGE}))
    assert step["passed"] is True
    assert step["repair"]["attempted"] is True and step["repair"]["applied"] is True and step["repair"]["error"] is None
    assert [round_["score"] for round_ in step["repair"]["rounds"]] == [93]
    assert step["scorecard"]["model_route"] == "Codex app-server / quality_judge"


def test_codex_step_rejects_malformed_and_oversized_outputs(monkeypatch):
    _forbid_server_llm(monkeypatch)
    bad = server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=copy.deepcopy(BASE_IR), outputs={"judge": "not json"}))
    assert bad.status_code == 502
    huge = server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=copy.deepcopy(BASE_IR), outputs={"judge": "x" * (2 * 1024 * 1024 + 1)}))
    assert huge.status_code == 413


def test_codex_step_rejects_inconsistent_stage_outputs(monkeypatch):
    _forbid_server_llm(monkeypatch)
    cases = [
        {"repair": json.dumps(BASE_IR)},
        {"judge": LOW_JUDGE, "rejudge": HIGH_JUDGE},
        {"judge": HIGH_JUDGE, "repair": json.dumps(BASE_IR)},
        {"judge": LOW_JUDGE, "repair": "not json", "rejudge": HIGH_JUDGE},
    ]
    for outputs in cases:
        result = server.quality_pass_codex_step(server.QualityPassCodexReq(
            ir=copy.deepcopy(BASE_IR), outputs=outputs))
        assert result.status_code == 422, outputs


def test_codex_step_preserves_graph_on_malformed_repair(monkeypatch):
    _forbid_server_llm(monkeypatch)
    source = copy.deepcopy(BASE_IR)
    result = server.quality_pass_codex_step(server.QualityPassCodexReq(
        ir=source, outputs={"judge": LOW_JUDGE, "repair": "not json"}))
    assert result["repair"]["attempted"] is True
    assert result["repair"]["applied"] is False
    assert result["repair"]["error"]
    assert result["ir"] == BASE_IR
    assert source == BASE_IR


if __name__ == "__main__":
    raise SystemExit(main())
