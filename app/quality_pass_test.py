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
    finally:
        server.llm.chat = original_chat

    if FAILS:
        print("FAILURES:", ", ".join(FAILS))
        return 1
    print("ALL QUALITY PASS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
