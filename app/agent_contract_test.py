"""Пакет инструкций агентов: загрузка, сборка, паритет с JS-загрузчиком."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_contract

ROLES = {"chat", "generator", "quality_judge", "quality_repair", "editor", "graphics"}


def test_pack_loads_with_expected_roles():
    contract = agent_contract.load()
    assert contract.version == "agent-contract/1.0"
    assert set(contract.roles) == ROLES
    generator = contract.roles["generator"]
    assert contract.compose("generator", "none") == f"{generator.instructions} {contract.tool_rules['none']} {contract.output_rules['json']}"
    assert contract.compose("chat", "none") == f"{contract.roles['chat'].instructions} {contract.tool_rules['none']}"
    assert contract.reminder("chat") == "" and "<svg>" in contract.reminder("graphics")
    assert agent_contract.version() == contract.version
    summary = contract.summary()
    assert summary["version"] == contract.version and set(summary["roles"]) == ROLES
    assert "instructions" not in json.dumps(summary), "публичная сводка не раскрывает тексты ролей"
    with pytest.raises(ValueError, match="Unsupported agent role"):
        contract.role("nope")
    with pytest.raises(ValueError, match="Unsupported tool rule"):
        contract.compose("generator", "shell")


def test_pack_files_match_manifest():
    raw = json.loads((agent_contract.DEFAULT_DIR / "contract.json").read_text(encoding="utf-8"))
    assert set(raw) >= {"version", "roles", "toolRules", "outputRules", "reminders"}
    for name, spec in raw["roles"].items():
        assert (agent_contract.DEFAULT_DIR / spec["file"]).exists(), name


def test_invalid_pack_is_rejected(tmp_path):
    (tmp_path / "contract.json").write_text(json.dumps({
        "version": "v9", "roles": {}, "toolRules": {}, "outputRules": {}, "reminders": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        agent_contract.load(tmp_path, reload=True)
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "generator.md").write_text("  \n", encoding="utf-8")
    (tmp_path / "contract.json").write_text(json.dumps({
        "version": "agent-contract/1.0", "roles": {"generator": {"output": "json", "file": "roles/generator.md"}},
        "toolRules": {"none": "x"}, "outputRules": {"json": "y"}, "reminders": {"json": "z"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="empty instructions"):
        agent_contract.load(tmp_path, reload=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="node не установлен")
def test_python_and_javascript_loaders_compose_identical_text():
    """Один пакет читают два загрузчика: собранный текст роли обязан совпадать байт в байт."""
    loader = (Path(__file__).resolve().parent.parent / "desktop" / "services" / "agent-contract.mjs").as_uri()
    script = (
        f"import {{ loadAgentContract }} from {json.dumps(loader)};\n"
        "const c = loadAgentContract();\n"
        "const out = {};\n"
        "for (const role of Object.keys(c.roles)) out[role] = [c.composeInstructions(role, 'none'), c.composeInstructions(role, 'inline-images'), c.reminder(role)];\n"
        "process.stdout.write(JSON.stringify({ version: c.version, out }));\n"
    )
    done = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=True)
    js = json.loads(done.stdout)
    contract = agent_contract.load()
    assert js["version"] == contract.version
    assert set(js["out"]) == set(contract.roles)
    for role, (none, inline, reminder) in js["out"].items():
        assert none == contract.compose(role, "none"), role
        assert inline == contract.compose(role, "inline-images"), role
        assert reminder == contract.reminder(role), role
