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


class _Recorder:
    def __init__(self, stdout="", last_message="", returncode=0):
        self.calls = []
        self.stdout = stdout
        self.last_message = last_message
        self.returncode = returncode

    def __call__(self, args, **kwargs):
        kwargs["input"] = kwargs.pop("stdin_text")
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
    assert call["env"]["MAX_THINKING_TOKENS"] == "12000"
    assert "Read tool ONLY" in call["input"]


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
