"""Пайплайн мульти-агентного ревью: diff спринта → два независимых ревьювера
(qwen3.8-max и glm-5.2 через OpenRouter) → консолидированный JSON-отчёт.

Оркестрация — на мне (lead): модели дают независимые мнения, триаж и фиксы — человек/lead.
Использование:
    .venv/Scripts/python app/review_pipeline.py [git-range]   (по умолчанию 737478f..HEAD)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client

# Политика владельца: разработка/ревью — прямые API; OpenRouter — только ноды.
# glm-5.2 доступен лишь через OpenRouter, поэтому по умолчанию второе мнение —
# gemini (прямой ключ); glm включается явно флагом --allow-openrouter.
# (имя, provider, model, fallback) — fallback срабатывает при ошибке (напр. 401 у gemini)
REVIEWERS = [
    ("qwen3.8-max", "qwen", "qwen3.8-max", None),
    ("gemini", "gemini", None, ("xai", "grok-3-beta")),
]
REVIEWERS_OR = [
    ("qwen3.8-max", "openrouter", "qwen/qwen3.8-max", None),
    ("glm-5.2", "openrouter", "z-ai/glm-5.2", None),
]

PROMPT = (
    "Ты — senior-ревьювер vanilla-JS редактора в стиле Figma (geoedit/editor/inspector/"
    "renderer/nodes) + FastAPI-бэка. Ниже diff спринта. Ищи: баги геометрии и координат, "
    "регрессии выделения/drag/undo, дыры безопасности (инъекции, SSRF, квоты), утечки "
    "состояния, сломанные контракты между модулями. НЕ хвали, не пересказывай. "
    "Верни СТРОГО один JSON-массив объектов {\"file\", \"severity\": "
    "\"critical|major|minor\", \"issue\", \"fix\"} без markdown и пояснений."
)


def parse_items(raw: str) -> list:
    """Устойчивый разбор: целый массив → первый валидный [..] → пообъектно."""
    try:
        items = json.loads(raw)
        return items if isinstance(items, list) else [items]
    except Exception:
        pass
    m = re.search(r"\[[\s\S]*\]", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    items = []
    for om in re.finditer(r"\{[\s\S]*?\}(?=\s*(?:,|\]))", raw):
        try:
            items.append(json.loads(om.group(0)))
        except Exception:
            continue
    if items:
        return items
    raise ValueError("review JSON не распознан")


def main() -> int:
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rng = args[0] if args else "737478f..HEAD"
    reviewers = REVIEWERS_OR if "--allow-openrouter" in flags else REVIEWERS
    diff = subprocess.run(
        ["git", "-C", str(ROOT), "diff", rng, "--", "app/"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    if len(diff) > 60000:
        diff = diff[:60000] + "\n…[diff обрезан]"
    print(f"diff {rng}: {len(diff)} символов")

    report = {"range": rng, "reviewers": {}}
    for name, provider, model, fallback in reviewers:
        try:
            try:
                raw = llm_client.chat(provider, [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": diff},
                ], 0.2, role="judge", timeout=600, model=model)
            except Exception as e:
                if not fallback:
                    raise
                print(f"[{name}] {e} → fallback {fallback[0]}")
                raw = llm_client.chat(fallback[0], [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": diff},
                ], 0.2, role="judge", timeout=600, model=fallback[1])
                name = f"{name}→{fallback[0]}"
            items = parse_items(raw)
            report["reviewers"][name] = items
            crit = sum(1 for i in items if i.get("severity") == "critical")
            maj = sum(1 for i in items if i.get("severity") == "major")
            print(f"[{name}] замечаний: {len(items)} (critical={crit}, major={maj})")
        except Exception as e:
            print(f"[{name}] ОШИБКА: {e}")
            report["reviewers"][name] = [{"file": "-", "severity": "critical",
                                          "issue": f"review failed: {e}", "fix": "-"}]
    os.environ.pop("OPENROUTER_MODELS_JUDGE", None)

    out = ROOT / "results" / "review_sprint4.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("отчёт:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
