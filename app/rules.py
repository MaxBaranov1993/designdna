"""Правила проекта: встроенные промпт-ассеты и пользовательские правила.

Закрывает «чёрный ящик» AI-редакторов: правила, по которым генератор и судья
принимают решения, видны в приложении (DESIGN.md / BLOCKS.md / RUBRIC.md) и
дополняются правилами проекта, которые пользователь пишет сам. Правила проекта
хранятся в data/rules/project.md, попадают в промпт генерации и в рубрику
vision-судьи — то есть проверяются, а не просто «учитываются».

Публичный API:
- builtin()               -> [{id, title, file, text}]
- project_rules()         -> str
- save_project_rules(str) -> str (нормализованный текст)
- prompt_block(section)   -> str для промпта ("" если правил нет)
- payload()               -> dict для GET /api/rules
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or APP_ROOT.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")

MAX_PROJECT_RULES = 20_000  # символов; больше — это уже документ, а не правила

_BUILTIN = (
    ("design", "Ремесло генерации (DESIGN.md)", "DESIGN.md"),
    ("blocks", "Библиотека блоков (BLOCKS.md)", "BLOCKS.md"),
    ("rubric", "Рубрика vision-судьи (RUBRIC.md)", "RUBRIC.md"),
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def builtin() -> list[dict]:
    """Встроенные правила — только чтение: они версионируются с приложением."""
    out = []
    for rule_id, title, name in _BUILTIN:
        path = APP_ROOT / "prompts" / name
        out.append({"id": rule_id, "title": title, "file": f"app/prompts/{name}",
                    "text": _read(path), "editable": False})
    return out


def project_rules_path() -> Path:
    return DATA_ROOT / "rules" / "project.md"


def project_rules() -> str:
    return _read(project_rules_path()).strip()


def normalize(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Правила должны быть текстом")
    cleaned = text.replace("\r\n", "\n").strip()
    if len(cleaned) > MAX_PROJECT_RULES:
        raise ValueError(f"Правила проекта длиннее {MAX_PROJECT_RULES} символов")
    return cleaned


def save_project_rules(text: str) -> str:
    cleaned = normalize(text)
    path = project_rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned + ("\n" if cleaned else ""), encoding="utf-8")
    return cleaned


def prompt_block(section: str = "generation") -> str:
    """Блок для промпта. section: generation — генератор/правки; judge — рубрика судьи."""
    text = project_rules()
    if not text:
        return ""
    if section == "judge":
        head = ("## Правила проекта (заданы пользователем)\n"
                "Нарушение любого из них — issue категории brief с severity major и снижение балла.\n")
    else:
        head = ("## Правила проекта (заданы пользователем, обязательны)\n"
                "Эти правила важнее общих рекомендаций по ремеслу; судья проверяет их отдельно.\n")
    return head + text


def payload() -> dict:
    return {"builtin": builtin(), "project": project_rules(),
            "projectFile": str(project_rules_path()), "maxProjectChars": MAX_PROJECT_RULES}
