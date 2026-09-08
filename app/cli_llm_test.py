"""cli_llm: консольный транспорт Codex/Claude и маршрутизация в llm_client без API-ключа."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli_llm
import llm_client

PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

# Справка современного Claude Code (2.1.x): все headless-флаги на месте.
MODERN_HELP = """
  --setting-sources <sources>           Comma-separated list of setting sources
  --bare                                Minimal mode ... via: --system-prompt[-file], --append-system-prompt[-file]
  --tools <tools...>                    Specify the list of available tools
  --strict-mcp-config                   Only use MCP servers from --mcp-config
  --effort <level>                      Effort level for the current session
  --json-schema <schema>                JSON Schema for structured output
"""
# Старый CLI: только --setting-sources и --allowedTools.
LEGACY_HELP = """
  --setting-sources <sources>           Comma-separated list of setting sources
  --allowedTools, --allowed-tools <tools...>
  --toolset x
"""


class _Recorder:
    def __init__(self, stdout="", last_message="", returncode=0):
        self.calls = []
        self.stdout = stdout
        self.last_message = last_message
        self.returncode = returncode

    def __call__(self, args, **kwargs):
        kwargs["input"] = kwargs.pop("stdin_text")
        # системный промпт живёт во временном файле только на время вызова
        if "--system-prompt-file" in args:
            kwargs["system"] = Path(args[args.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")
        if "--output-schema" in args:
            kwargs["schema"] = json.loads(Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        self.calls.append({"args": args, **kwargs})
        # codex пишет финальное сообщение в файл из -o
        if "-o" in args:
            Path(args[args.index("-o") + 1]).write_text(self.last_message, encoding="utf-8")
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr="")


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DESIGNDNA_CODEX", str(tmp_path / "codex.exe"))
    monkeypatch.setenv("DESIGNDNA_CLAUDE", str(tmp_path / "claude.exe"))
    (tmp_path / "codex.exe").write_text("")
    (tmp_path / "claude.exe").write_text("")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_CLI_PROVIDER", raising=False)
    monkeypatch.setattr(cli_llm, "_claude_help_text", lambda command: MODERN_HELP)
    return tmp_path


def test_codex_prompt_goes_through_stdin_with_model_effort_and_last_message(cli_env, monkeypatch):
    rec = _Recorder(last_message='{"ok": 1}')
    monkeypatch.setattr(cli_llm, "_run", rec)
    out = cli_llm.chat("codex", [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}],
                       model="gpt-5.6-sol", effort="medium", timeout=30)
    assert out == '{"ok": 1}'
    call = rec.calls[0]
    args = call["args"]
    assert args[0].endswith("codex.exe") and args[1] == "exec"
    assert args[-1] == "-" and "USER" in call["input"] and "SYSTEM:\nSYS" in call["input"]
    assert "-m" in args and args[args.index("-m") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="medium"' in args
    assert "--ignore-rules" in args and "read-only" in args
    # герметично: без AGENTS.md и MCP-серверов пользователя
    assert args[args.index("-c") + 1] == "project_doc_max_bytes=0" or "project_doc_max_bytes=0" in args
    assert "mcp_servers={}" in args
    assert call["timeout"] == 30


def test_codex_images_become_files_passed_with_i(cli_env, monkeypatch):
    rec = _Recorder(last_message="seen")
    monkeypatch.setattr(cli_llm, "_run", rec)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "оцени"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + PNG_1PX}},
    ]}]
    assert cli_llm.chat("codex", messages) == "seen"
    args = rec.calls[0]["args"]
    image = args[args.index("-i") + 1]
    assert image.endswith("image-1.png")
    assert "IMAGE FILE 1" in rec.calls[0]["input"]


def test_codex_empty_answer_raises_with_stderr_tail(cli_env, monkeypatch):
    rec = _Recorder(last_message="", returncode=2)
    rec.stdout = ""
    monkeypatch.setattr(cli_llm, "_run", rec)
    with pytest.raises(RuntimeError, match="Codex CLI"):
        cli_llm.chat("codex", [{"role": "user", "content": "x"}])


def test_claude_parses_json_envelope_and_flags(cli_env, monkeypatch):
    rec = _Recorder(stdout=json.dumps({"type": "result", "is_error": False, "result": " {\"a\":1} "}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "смотри"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + PNG_1PX}},
    ]}]
    assert cli_llm.chat("claude", messages, effort="high") == '{"a":1}'
    call = rec.calls[0]
    args = call["args"]
    assert args[1] == "-p" and "--output-format" in args and "json" in args
    assert "--allowedTools" in args and "Read" in args
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--effort") + 1] == "high"
    assert "MAX_THINKING_TOKENS" not in call["env"]
    assert "--strict-mcp-config" in args and args[args.index("--setting-sources") + 1] == ""
    assert "Read tool ONLY" in call["system"] and "Read tool ONLY" not in call["input"]


def test_claude_system_messages_go_to_system_prompt_file(cli_env, monkeypatch):
    rec = _Recorder(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-leak")
    cli_llm.chat("claude", [{"role": "system", "content": "CONTRACT §1"}, {"role": "user", "content": "USER"}], effort="medium")
    call = rec.calls[0]
    args = call["args"]
    assert args[args.index("--tools") + 1] == "" and "--allowedTools" not in args
    assert "CONTRACT §1" in call["system"] and "Do not inspect files" in call["system"]
    assert "CONTRACT" not in call["input"] and "SYSTEM:" not in call["input"] and "USER" in call["input"]
    assert "ANTHROPIC_API_KEY" not in call["env"], "API-маршруты не должны попадать в подписочный CLI"
    assert str(call["cwd"]).startswith(str(Path(call["args"][args.index("--system-prompt-file") + 1]).parent))


def test_claude_legacy_cli_falls_back_to_env_budget_and_inline_rules(cli_env, monkeypatch):
    monkeypatch.setattr(cli_llm, "_claude_help_text", lambda command: LEGACY_HELP)
    rec = _Recorder(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    cli_llm.chat("claude", [{"role": "system", "content": "CONTRACT"}, {"role": "user", "content": "USER"}], effort="high")
    call = rec.calls[0]
    args = call["args"]
    assert "--tools" not in args and "--effort" not in args and "--strict-mcp-config" not in args
    assert "--system-prompt-file" not in args and "system" not in call
    assert args[args.index("--setting-sources") + 1] == ""
    assert call["env"]["MAX_THINKING_TOKENS"] == "8000"
    assert "SYSTEM:\nCONTRACT" in call["input"] and "Do not inspect files" in call["input"]


def test_claude_capabilities_parse_help_text():
    cli_llm._CLAUDE_HELP_CACHE["modern"] = MODERN_HELP
    cli_llm._CLAUDE_HELP_CACHE["legacy"] = LEGACY_HELP
    cli_llm._CLAUDE_HELP_CACHE["unknown"] = None
    try:
        modern = cli_llm._claude_capabilities("modern")
        assert modern == {"setting_sources": True, "tools": True, "strict_mcp_config": True,
                          "system_prompt_file": True, "effort": True, "json_schema": True}
        legacy = cli_llm._claude_capabilities("legacy")
        assert legacy["setting_sources"] and not legacy["tools"] and not legacy["effort"] and not legacy["system_prompt_file"]
        assert all(cli_llm._claude_capabilities("unknown").values()), "без справки считаем современный CLI"
    finally:
        for key in ("modern", "legacy", "unknown"):
            cli_llm._CLAUDE_HELP_CACHE.pop(key, None)


def test_claude_error_envelope_raises(cli_env, monkeypatch):
    rec = _Recorder(stdout=json.dumps({"is_error": True, "result": "not logged in"}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    with pytest.raises(RuntimeError, match="not logged in"):
        cli_llm.chat("claude", [{"role": "user", "content": "x"}])


def test_default_provider_prefers_env_then_codex(cli_env, monkeypatch):
    assert cli_llm.default_provider() == "codex"
    monkeypatch.setenv("LLM_CLI_PROVIDER", "claude")
    assert cli_llm.default_provider() == "claude"
    monkeypatch.setenv("DESIGNDNA_CLAUDE", str(cli_env / "missing.exe"))
    assert cli_llm.default_provider() == "codex"


def test_llm_client_routes_to_cli_without_openai_key(cli_env, monkeypatch):
    seen = {}

    def fake_chat(provider, messages, **kw):
        seen.update(provider=provider, messages=messages, **kw)
        return "cli-answer"

    monkeypatch.setattr(llm_client.cli_llm, "chat", fake_chat)
    deltas = []
    out = llm_client.chat("auto", [{"role": "user", "content": "hi"}], 0.2, role="generator",
                          reasoning_effort="high", on_delta=deltas.append)
    assert out == "cli-answer" and deltas == ["cli-answer"]
    assert seen["provider"] == "codex" and seen["effort"] == "high"
    # chat_vision складывает system + image в сообщения для CLI
    llm_client.chat_vision("claude", "data:image/png;base64," + PNG_1PX, "оцени", "СИСТЕМА")
    assert seen["provider"] == "claude"
    assert seen["messages"][0] == {"role": "system", "content": "СИСТЕМА"}
    assert seen["messages"][1]["content"][1]["type"] == "image_url"


def test_llm_client_explicit_openai_with_key_skips_cli(cli_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    called = {"cli": False}
    monkeypatch.setattr(llm_client.cli_llm, "chat", lambda *a, **k: called.__setitem__("cli", True) or "x")
    monkeypatch.setattr(llm_client, "_post_json", lambda *a, **k: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "api"}]}]})
    assert llm_client.chat("openai", [{"role": "user", "content": "hi"}], 0.2) == "api"
    assert called["cli"] is False


def test_llm_client_without_key_and_without_cli_explains(cli_env, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_CODEX", str(cli_env / "no.exe"))
    monkeypatch.setenv("DESIGNDNA_CLAUDE", str(cli_env / "no.exe"))
    with pytest.raises(RuntimeError, match="Codex CLI|Claude Code"):
        llm_client.chat("auto", [{"role": "user", "content": "hi"}], 0.2)


def test_claude_output_schema_uses_json_schema_and_structured_output(cli_env, monkeypatch):
    schema = {"type": "object", "required": ["approved"], "properties": {"approved": {"type": "boolean"}}}
    rec = _Recorder(stdout=json.dumps({"result": "{\"approved\": true}", "structured_output": {"approved": True}}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    out = cli_llm.chat("claude", [{"role": "user", "content": "judge"}], output_schema=schema)
    assert json.loads(out) == {"approved": True}
    args = rec.calls[0]["args"]
    assert json.loads(args[args.index("--json-schema") + 1]) == schema
    assert "--max-turns" not in args


def test_claude_output_schema_skipped_on_legacy_cli(cli_env, monkeypatch):
    monkeypatch.setattr(cli_llm, "_claude_help_text", lambda command: LEGACY_HELP)
    rec = _Recorder(stdout=json.dumps({"result": "{\"approved\": false}"}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    out = cli_llm.chat("claude", [{"role": "user", "content": "judge"}], output_schema={"type": "object"})
    assert out == '{"approved": false}'
    assert "--json-schema" not in rec.calls[0]["args"]


def test_codex_output_schema_is_written_to_a_file(cli_env, monkeypatch):
    schema = {"type": "object", "required": ["score"], "properties": {"score": {"type": "number"}}}
    rec = _Recorder(last_message='{"score": 90}')
    monkeypatch.setattr(cli_llm, "_run", rec)
    assert cli_llm.chat("codex", [{"role": "user", "content": "judge"}], output_schema=schema) == '{"score": 90}'
    call = rec.calls[0]
    assert call["schema"] == schema
    assert call["args"][call["args"].index("--output-schema") + 1].endswith("output-schema.json")


def test_claude_tool_rules_come_from_the_agent_contract_pack(cli_env, monkeypatch):
    import agent_contract
    rec = _Recorder(stdout=json.dumps({"result": "ok"}))
    monkeypatch.setattr(cli_llm, "_run", rec)
    cli_llm.chat("claude", [{"role": "user", "content": "x"}])
    assert rec.calls[0]["system"].startswith(agent_contract.load().tool_rule("none"))


def test_llm_client_passes_json_schema_to_cli(cli_env, monkeypatch):
    seen = {}

    def fake_chat(provider, messages, **kw):
        seen.update(provider=provider, **kw)
        return "{}"

    monkeypatch.setattr(llm_client.cli_llm, "chat", fake_chat)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    request = llm_client.ChatRequest(messages=[{"role": "user", "content": "hi"}], provider="claude",
                                     response_format="json_schema", response_json_schema={"name": "verdict", "schema": schema})
    llm_client.chat_envelope(request, role="quality_judge")
    assert seen["provider"] == "claude" and seen["output_schema"] == schema
    plain = llm_client.ChatRequest(messages=[{"role": "user", "content": "hi"}], provider="codex")
    llm_client.chat_envelope(plain, role="quality_judge")
    assert seen["output_schema"] is None
