"""Трасса вызовов моделей: запись, ротация, чтение обоих источников, hook в llm_client."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client
import llm_trace


def test_record_and_recent_merge_python_and_electron_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_trace, "DATA_ROOT", tmp_path)
    entry = llm_trace.record(request_id="r1", role="quality_judge", provider="claude", model="opus", effort="high",
                             contract_version="agent-contract/1.0", duration_ms=1234.4, prompt_chars=40, output_chars=10,
                             dropped=[{"field": "temperature", "reason": "x"}], structured_output=True)
    assert entry["source"] == "python" and entry["ok"] is True and entry["durationMs"] == 1234
    assert entry["dropped"] == ["temperature"] and entry["structuredOutput"] is True
    assert llm_trace.write(entry)
    electron = tmp_path / "traces" / llm_trace.ELECTRON_FILE
    electron.write_text(json.dumps({"ts": "2099-01-01T00:00:00Z", "requestId": "e1", "provider": "codex"}) + "\n"
                        + "not json\n", encoding="utf-8")
    recent = llm_trace.recent(10)
    assert [item["requestId"] for item in recent] == ["e1", "r1"], "новые первыми, битые строки пропускаются"
    assert recent[0]["source"] == "electron" and recent[1]["source"] == "python"
    assert llm_trace.recent(10, source="python")[0]["requestId"] == "r1"
    assert llm_trace.recent(1) and len(llm_trace.recent(1)) == 1


def test_write_rotates_at_size_cap_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_trace, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(llm_trace, "MAX_BYTES", 120)
    for index in range(6):
        assert llm_trace.write({"ts": f"2026-09-09T00:00:0{index}Z", "requestId": f"r{index}"})
    directory = tmp_path / "traces"
    assert (directory / (llm_trace.PYTHON_FILE + ".1")).exists()
    assert llm_trace.recent(50)[0]["requestId"] == "r5"
    monkeypatch.setattr(llm_trace, "DATA_ROOT", tmp_path / "file-instead-of-dir")
    (tmp_path / "file-instead-of-dir").write_text("x", encoding="utf-8")
    assert llm_trace.write({"ts": "x"}) is False


def test_message_chars_counts_text_parts_only():
    messages = [{"role": "user", "content": "abcd"}, {"role": "user", "content": [
        {"type": "text", "text": "xyz"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    assert llm_trace.message_chars(messages, "SYS") == 3 + 4 + 3


def test_chat_envelope_writes_a_trace_for_cli_calls_and_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("DESIGNDNA_CLAUDE", str(tmp_path / "claude.exe"))
    (tmp_path / "claude.exe").write_text("")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    written = []
    monkeypatch.setattr(llm_trace, "write", lambda entry, data_root=None: written.append(entry) or True)
    monkeypatch.setattr(llm_client.cli_llm, "chat", lambda provider, messages, **kw: "{\"ok\": true}")
    request = llm_client.ChatRequest(messages=[{"role": "user", "content": "hello"}], provider="claude",
                                     system="SYS", reasoning_effort="high",
                                     response_format="json_schema", response_json_schema={"name": "v", "schema": {"type": "object"}})
    llm_client.chat_envelope(request, role="quality_judge")
    entry = written[-1]
    assert entry["provider"] == "claude" and entry["profile"] == "quality_judge" and entry["effort"] == "high"
    assert entry["ok"] is True and entry["outputChars"] == len('{"ok": true}') and entry["promptChars"] == len("SYS") + len("hello")
    assert entry["structuredOutput"] is True and entry["contractVersion"].startswith("agent-contract/")
    assert "hello" not in json.dumps(entry) and "SYS" not in json.dumps(entry)

    def boom(provider, messages, **kw):
        raise RuntimeError("Claude Code: not logged in")

    monkeypatch.setattr(llm_client.cli_llm, "chat", boom)
    try:
        llm_client.chat_envelope(llm_client.ChatRequest(messages=[{"role": "user", "content": "x"}], provider="claude"), role="generator")
    except RuntimeError:
        pass
    failed = written[-1]
    assert failed["ok"] is False and "not logged in" in failed["error"] and failed["profile"] == "generator"
