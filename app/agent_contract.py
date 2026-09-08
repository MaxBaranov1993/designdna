"""Пакет инструкций агентов (app/prompts/agent-contract).

Единый источник текстов ролей и правил для подписочных CLI (Claude Code,
Codex) и Python-пути. Тот же пакет читает desktop/services/agent-contract.mjs;
адаптеры собирают «роль + правило инструментов + правило вывода» одинаково,
различается только транспорт. Версия пакета пишется в generationLog и в
transport-метаданные ответов.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(os.environ.get("DESIGNDNA_APP_DIR") or Path(__file__).resolve().parent)
DEFAULT_DIR = APP_DIR / "prompts" / "agent-contract"
_VERSION_RE = re.compile(r"^agent-contract/\d+\.\d+$")
_ROLE_RE = re.compile(r"^[a-z_]{1,32}$")
_LOCK = threading.Lock()
_CACHE: dict[str, "AgentContract"] = {}


@dataclass(frozen=True)
class Role:
    name: str
    output: str
    instructions: str


@dataclass(frozen=True)
class AgentContract:
    version: str
    directory: Path
    roles: dict[str, Role]
    tool_rules: dict[str, str]
    output_rules: dict[str, str]
    reminders: dict[str, str]
    effort_levels: tuple[str, ...]
    effort_default: str

    def has_role(self, name: str) -> bool:
        return name in self.roles

    def role(self, name: str) -> Role:
        try:
            return self.roles[name]
        except KeyError:
            raise ValueError(f"Unsupported agent role: {name}") from None

    def tool_rule(self, kind: str) -> str:
        try:
            return self.tool_rules[kind]
        except KeyError:
            raise ValueError(f"Unsupported tool rule: {kind}") from None

    def compose(self, name: str, tool_rule: str) -> str:
        """«Роль + правило инструментов + правило вывода» — как в JS-адаптерах."""
        role = self.role(name)
        parts = [role.instructions, self.tool_rule(tool_rule), self.output_rules.get(role.output, "")]
        return " ".join(part for part in parts if part)

    def reminder(self, name: str) -> str:
        return self.reminders.get(self.role(name).output, "")

    def summary(self) -> dict:
        """Публичное описание для /api/config и UI: без текстов ролей."""
        return {
            "version": self.version,
            "roles": {name: {"output": role.output} for name, role in self.roles.items()},
            "effort": {"levels": list(self.effort_levels), "default": self.effort_default},
        }


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def load(directory: Path | str | None = None, *, reload: bool = False) -> AgentContract:
    root = Path(directory or DEFAULT_DIR).resolve()
    key = str(root)
    with _LOCK:
        if not reload and key in _CACHE:
            return _CACHE[key]
    raw = json.loads(_read(root / "contract.json"))
    version = str(raw.get("version") or "").strip()
    if not _VERSION_RE.match(version):
        raise ValueError(f"agent-contract: unsupported version {version!r}")
    tool_rules = {str(k): str(v) for k, v in (raw.get("toolRules") or {}).items()}
    output_rules = {str(k): str(v) for k, v in (raw.get("outputRules") or {}).items()}
    reminders = {str(k): str(v) for k, v in (raw.get("reminders") or {}).items()}
    roles: dict[str, Role] = {}
    for name, spec in (raw.get("roles") or {}).items():
        if not _ROLE_RE.match(str(name)):
            raise ValueError(f"agent-contract: invalid role name {name!r}")
        output = str((spec or {}).get("output") or "")
        if output not in output_rules:
            raise ValueError(f"agent-contract: role {name} has unknown output {output!r}")
        file = str((spec or {}).get("file") or "")
        if not file or ".." in file or Path(file).is_absolute():
            raise ValueError(f"agent-contract: role {name} has an invalid file path")
        instructions = _read(root / file).strip()
        if not instructions:
            raise ValueError(f"agent-contract: role {name} has empty instructions")
        roles[str(name)] = Role(str(name), output, instructions)
    effort = raw.get("effort") or {}
    contract = AgentContract(
        version=version,
        directory=root,
        roles=roles,
        tool_rules=tool_rules,
        output_rules=output_rules,
        reminders=reminders,
        effort_levels=tuple(str(level) for level in (effort.get("levels") or ("medium", "high", "max"))),
        effort_default=str(effort.get("default") or "medium"),
    )
    with _LOCK:
        _CACHE[key] = contract
    return contract


def version() -> str:
    return load().version
