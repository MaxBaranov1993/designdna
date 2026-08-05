"""Пайплайн мульти-агентного ревью: diff спринта → два независимых ревьювера
(оба — qwencloud/Bailian, провайдер qwen) → консолидированный JSON-отчёт.

Политика владельца от 2026-08-05: разработка и ревью — только API qwencloud
(провайдер qwen, Bailian Token Plan); OpenRouter и прямые API других вендоров —
только LLM-вызовы внутри продукта (ноды).
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

# Политика владельца от 2026-08-05: разработка/ревью — только qwencloud (провайдер
# qwen, Bailian Token Plan); gemini/xai и прочие прямые API — только ноды продукта.
# (имя, provider, model, fallback) — fallback срабатывает при ошибке вызова.
REVIEWERS = [
    ("qwen3.8-max", "qwen", "qwen3.8-max", None),
    # вторая модель qwen для независимого мнения; qwen3-max и qwen-plus на
    # token-plan эндпоинте отсутствуют (404), из доступных выбран qwen3.7-max
    ("qwen3.7-max", "qwen", "qwen3.7-max", None),
]
# Вариант через OpenRouter — только для работ по нодам продукта (по политике
# ноды ходят в OpenRouter); включается явно флагом --allow-openrouter.
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
    """Устойчивый разбор: целый JSON → raw_decode от первой '[' (баланс скобок
    учитывает парсер, а не regex) → пообъектно как последний шанс."""
    try:
        items = json.loads(raw)
        return items if isinstance(items, list) else [items]
    except Exception:
        pass
    start = raw.find("[")
    if start >= 0:
        dec = json.JSONDecoder()
        try:
            items, _ = dec.raw_decode(raw, start)
            if isinstance(items, list):
                return items
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
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(__doc__)
        return 0
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rng = args[0] if args else "737478f..HEAD"
    # ведущий '-' запрещён: аргумент не должен разбираться git'ом как флаг
    if not re.fullmatch(r"[\w.~/][\w.~/^-]*(\.\.[\w.~/][\w.~/^-]*)?", rng):
        print("некорректный git-range:", rng)
        return 2
    # концы диапазона обязаны существовать в репозитории
    for rev in (rng.split("..", 1) if ".." in rng else [rng]):
        chk = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", rev + "^{commit}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if chk.returncode != 0:
            print("некорректная ревизия в диапазоне:", rev)
            return 2
    reviewers = REVIEWERS_OR if "--allow-openrouter" in flags else REVIEWERS
    # '--' отделяет ревизии от pathspec: аргументы после него git не примет за флаги
    diff = subprocess.run(
        ["git", "-C", str(ROOT), "diff", rng, "--", "app/"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    if len(diff) > 60000:
        # режем по границе файла, чтобы не рвать ханки; указываем, что пропало
        cut = diff.rfind("\ndiff --git", 0, 60000)
        omitted = []
        if cut > 0:
            omitted = sorted(set(re.findall(r"^diff --git a/(\S+)", diff[cut + 1:], re.M)))
            diff = diff[:cut + 1]
        else:
            diff = diff[:60000]
        diff += "\n…[diff обрезан по границе файла; пропущены: " + ", ".join(omitted) + "]"
    print(f"diff {rng}: {len(diff)} символов")

    report = {"range": rng, "reviewers": {}}
    empty = not diff.strip()
    if empty:
        # правок app/ в диапазоне нет: нечего ревьювить, вызовы LLM не делаем
        print("diff пуст: правок app/ нет, ревью без вызовов LLM")
        report["reviewers"] = {name: [] for name, _, _, _ in reviewers}
    for name, provider, model, fallback in ([] if empty else reviewers):
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

    out = ROOT / "results" / "review_sprint4.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("отчёт:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
