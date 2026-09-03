"""Консольный LLM-транспорт: Codex CLI (`codex exec`) и Claude Code (`claude -p`).

Зачем: продукт работает через подключённые аккаунты приложений (OAuth Codex /
Claude Code), а не через API-ключи. Десктоп уже гоняет провайдеров через
main.mjs; здесь тот же контракт для Python-сервера и воркера, чтобы генерация,
арт-дирекция и vision-судья ходили одним путём в обоих режимах.

Контракт: chat(provider, messages, model=, effort=, timeout=) -> str.
Сообщения — OpenAI-формат; части image_url с data:-URL материализуются во
временные PNG: Codex получает их флагом -i, Claude — через Read tool.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cancel_token

CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
CLAUDE_DEFAULT_MODEL = "opus"
DEFAULT_TIMEOUT = 240
_EFFORTS = {"low", "medium", "high", "max", "xhigh"}
# Claude Code думает по бюджету токенов, а не по уровню усилия (как в десктопе)
_CLAUDE_THINKING = {"low": 0, "medium": 4_000, "high": 12_000, "max": 32_000, "xhigh": 32_000}


def _command(provider: str) -> str | None:
    """Путь к CLI: переопределение DESIGNDNA_CODEX/DESIGNDNA_CLAUDE (как в десктопе) или PATH."""
    override = os.environ.get("DESIGNDNA_CODEX" if provider == "codex" else "DESIGNDNA_CLAUDE", "").strip()
    if override:
        return override if Path(override).exists() or shutil.which(override) else None
    return shutil.which(provider)


def available(provider: str) -> bool:
    return provider in ("codex", "claude") and _command(provider) is not None


def default_provider() -> str | None:
    """Кто отвечает, если API-ключа OpenAI нет: LLM_CLI_PROVIDER или первый доступный."""
    preferred = os.environ.get("LLM_CLI_PROVIDER", "").strip().lower()
    order = [preferred] if preferred in ("codex", "claude") else []
    order += [p for p in ("codex", "claude") if p not in order]
    for provider in order:
        if available(provider):
            return provider
    return None


def _materialize(messages: list, tmp: Path) -> tuple[str, list[Path]]:
    """Сообщения → один текстовый промпт; картинки → файлы во временной папке."""
    lines: list[str] = []
    images: list[Path] = []
    for message in messages or []:
        role = str(message.get("role") or "user").upper()
        content = message.get("content")
        if not isinstance(content, list):
            lines.append(f"{role}:\n{content or ''}")
            continue
        pieces: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = str((part.get("image_url") or {}).get("url") or "")
                match = re.match(r"^data:image/([a-z0-9.+-]+);base64,(.+)$", url, re.I | re.S)
                if not match:
                    raise RuntimeError("CLI transport accepts only data:image base64 parts")
                ext = "jpg" if match.group(1).lower() == "jpeg" else match.group(1).lower()
                file = tmp / f"image-{len(images) + 1}.{ext}"
                file.write_bytes(base64.b64decode(match.group(2)))
                images.append(file)
                pieces.append(f"IMAGE FILE {len(images)}: {file}")
            elif isinstance(part, dict):
                pieces.append(str(part.get("text") or ""))
        lines.append(f"{role}:\n" + "\n".join(pieces))
    return "\n\n".join(lines), images


def _run(args: list[str], *, stdin_text: str, cwd: Path, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    cancel_token.check()
    return subprocess.run(
        args, input=stdin_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd), timeout=timeout, env=env, check=False,
    )


def _codex(messages: list, *, model: str | None, effort: str | None, timeout: int) -> str:
    command = _command("codex")
    if not command:
        raise RuntimeError("Codex CLI не найден: установите @openai/codex и войдите в аккаунт (codex login)")
    with tempfile.TemporaryDirectory(prefix="ddna-codex-") as tmpdir:
        tmp = Path(tmpdir)
        prompt, images = _materialize(messages, tmp)
        last = tmp / "last-message.txt"
        args = [
            command, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-rules",
            "-s", "read-only", "-C", str(tmp), "-m", model or CODEX_DEFAULT_MODEL,
            "-o", str(last),
        ]
        if effort in _EFFORTS:
            args += ["-c", f'model_reasoning_effort="{effort}"']
        for image in images:
            args += ["-i", str(image)]
        args.append("-")  # промпт из stdin: системные промпты больше лимита командной строки
        done = _run(args, stdin_text=prompt, cwd=tmp, timeout=timeout)
        text = last.read_text(encoding="utf-8").strip() if last.exists() else ""
        if not text:
            tail = (done.stderr or done.stdout or "").strip()[-600:]
            raise RuntimeError(f"Codex CLI не вернул ответ (exit {done.returncode}): {tail}")
        return text


def _claude(messages: list, *, model: str | None, effort: str | None, timeout: int) -> str:
    command = _command("claude")
    if not command:
        raise RuntimeError("Claude Code не найден: установите claude и выполните /login")
    with tempfile.TemporaryDirectory(prefix="ddna-claude-") as tmpdir:
        tmp = Path(tmpdir)
        prompt, images = _materialize(messages, tmp)
        rule = ("Use the Read tool ONLY to view the image files listed in the messages. Do not run commands or use any other tool."
                if images else "Do not inspect files, run commands, or call tools.")
        args = [command, "-p", "--output-format", "json", "--model", model or CLAUDE_DEFAULT_MODEL]
        if images:
            args += ["--allowedTools", "Read"]
        env = dict(os.environ)
        budget = _CLAUDE_THINKING.get(effort or "medium", 4_000)
        if budget:
            env["MAX_THINKING_TOKENS"] = str(budget)
        done = _run(args, stdin_text=f"{rule}\n\n{prompt}", cwd=tmp, timeout=timeout, env=env)
        raw = (done.stdout or "").strip()
        if not raw:
            raise RuntimeError(f"Claude Code не вернул ответ (exit {done.returncode}): {(done.stderr or '')[-600:]}")
        try:
            envelope = json.loads(raw)
        except ValueError:
            return raw
        if isinstance(envelope, dict):
            if envelope.get("is_error"):
                raise RuntimeError(f"Claude Code: {envelope.get('result') or envelope.get('error') or 'ошибка'}")
            result = envelope.get("result")
            if isinstance(result, str):
                return result.strip()
        return raw


def chat(provider: str, messages: list, *, model: str | None = None, effort: str | None = None,
         timeout: int | None = None) -> str:
    timeout = int(timeout or DEFAULT_TIMEOUT)
    if provider == "codex":
        return _codex(messages, model=model, effort=effort, timeout=timeout)
    if provider == "claude":
        return _claude(messages, model=model, effort=effort, timeout=timeout)
    raise ValueError(f"unknown CLI provider: {provider}")
