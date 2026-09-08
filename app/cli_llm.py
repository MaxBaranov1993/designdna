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
import time
import signal
from pathlib import Path

import cancel_token
import agent_contract

CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
CLAUDE_DEFAULT_MODEL = "opus"
# Полный IR-документ через CLI (промпт ~40 КБ + JSON ~15 КБ) занимает минуты:
# лимит заметно выше HTTP-пути, настраивается LLM_CLI_TIMEOUT_S.
DEFAULT_TIMEOUT = int(os.environ.get("LLM_CLI_TIMEOUT_S", "900"))
_EFFORTS = {"low", "medium", "high", "max", "xhigh", "ultra"}
# Запасной путь для старых Claude Code без --effort: бюджет thinking через env.
# Таблица совпадает с десктопным адаптером (claude-agent-server.mjs), чтобы
# одна и та же нода давала одинаковое усилие в обоих путях запуска.
_CLAUDE_THINKING = {"low": 0, "medium": 0, "high": 8_000, "max": 24_000, "xhigh": 24_000}
_CLAUDE_EFFORT_LEVELS = ("medium", "high", "max")
# Headless-флаги, появившиеся в Claude Code не одновременно. Продукт ставят на
# чужие машины с произвольной версией CLI: набор флагов — capability, которая
# читается из `claude --help` один раз на процесс; без справки считаем
# современный CLI.
_CLAUDE_FLAGS = {
    "setting_sources": "--setting-sources",
    "tools": "--tools",
    "strict_mcp_config": "--strict-mcp-config",
    "system_prompt_file": "--system-prompt-file",
    "effort": "--effort",
    "json_schema": "--json-schema",
}
_CLAUDE_HELP_CACHE: dict[str, str | None] = {}
# Переменные, которые переводят Claude Code с подписки на API/облако: детям
# их не отдаём (как claudeSubscriptionEnvironment в десктопе).
_CLAUDE_API_ROUTE_RE = re.compile(
    r"^(ANTHROPIC_.*|BASE_URL|AWS_BEARER_TOKEN_BEDROCK|"
    r"CLAUDE_CODE_(USE_(BEDROCK|VERTEX|FOUNDRY|ANTHROPIC_AWS)|SKIP_(BEDROCK|VERTEX|FOUNDRY)_AUTH))$",
    re.IGNORECASE)


def _command(provider: str) -> str | None:
    """Путь к CLI: переопределение DESIGNDNA_CODEX/DESIGNDNA_CLAUDE (как в десктопе) или PATH."""
    override = os.environ.get("DESIGNDNA_CODEX" if provider == "codex" else "DESIGNDNA_CLAUDE", "").strip()
    if override:
        return override if Path(override).exists() or shutil.which(override) else None
    return shutil.which(provider)


def _claude_help_text(command: str) -> str | None:
    """`claude --help` без модели и сети; None — справку прочитать не удалось."""
    if command in _CLAUDE_HELP_CACHE:
        return _CLAUDE_HELP_CACHE[command]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run([command, "--help"], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20, **options)
        text: str | None = (done.stdout or "") + (done.stderr or "")
    except Exception:
        text = None
    _CLAUDE_HELP_CACHE[command] = text
    return text


def _claude_capabilities(command: str) -> dict[str, bool]:
    text = _claude_help_text(command)
    if not text:
        return {key: True for key in _CLAUDE_FLAGS}
    caps = {}
    for key, flag in _CLAUDE_FLAGS.items():
        # `--system-prompt[-file]` в справке описывает оба флага сразу
        variants = {flag, flag.replace("-file", "[-file]")}
        caps[key] = any(re.search(rf"(^|[\s,]){re.escape(v)}(?=$|[\s,<])", text, re.M) for v in variants)
    return caps


def _claude_subscription_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not _CLAUDE_API_ROUTE_RE.match(key)}


def _split_system(messages: list) -> tuple[list[str], list]:
    """system-сообщения — в системный канал, остальные — в ввод."""
    system_texts: list[str] = []
    rest: list = []
    for message in messages:
        if str(message.get("role") or "") != "system":
            rest.append(message)
            continue
        content = message.get("content")
        if isinstance(content, list):
            if any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
                raise ValueError("system messages cannot carry images")
            text = "\n".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        else:
            text = str(content or "")
        if text.strip():
            system_texts.append(text)
    return system_texts, rest


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
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=str(cwd), env=env, **options)
    deadline = time.monotonic() + timeout
    pending_input = stdin_text
    try:
        while True:
            cancel_token.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = process.communicate(input=pending_input, timeout=min(0.25, remaining))
                cancel_token.check()
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                # communicate resumes buffered I/O; input may only be supplied once.
                pending_input = None
    finally:
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
        process.communicate()


def _codex(messages: list, *, model: str | None, effort: str | None, timeout: int,
           output_schema: dict | None = None) -> str:
    command = _command("codex")
    if not command:
        raise RuntimeError("Codex CLI не найден: установите @openai/codex и войдите в аккаунт (codex login)")
    with tempfile.TemporaryDirectory(prefix="ddna-codex-") as tmpdir:
        tmp = Path(tmpdir)
        prompt, images = _materialize(messages, tmp)
        last = tmp / "last-message.txt"
        # Герметично: пустой временный cwd, без AGENTS.md пользователя
        # (project_doc_max_bytes=0), без сохранения сессии (--ephemeral).
        # --ignore-rules касается только execpolicy .rules, не AGENTS.md.
        args = [
            command, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-rules",
            "-c", "project_doc_max_bytes=0", "-c", "mcp_servers={}",
            "-s", "read-only", "-C", str(tmp), "-m", model or CODEX_DEFAULT_MODEL,
            "-o", str(last),
        ]
        if effort in _EFFORTS:
            args += ["-c", f'model_reasoning_effort="{effort}"']
        if isinstance(output_schema, dict) and output_schema:
            # Структурированный вывод: JSON Schema финального сообщения (файл).
            schema_file = tmp / "output-schema.json"
            schema_file.write_text(json.dumps(output_schema, ensure_ascii=False), encoding="utf-8")
            args += ["--output-schema", str(schema_file)]
        for image in images:
            args += ["-i", str(image)]
        args.append("-")  # промпт из stdin: системные промпты больше лимита командной строки
        done = _run(args, stdin_text=prompt, cwd=tmp, timeout=timeout)
        text = last.read_text(encoding="utf-8").strip() if last.exists() else ""
        if not text:
            tail = (done.stderr or done.stdout or "").strip()[-600:]
            raise RuntimeError(f"Codex CLI не вернул ответ (exit {done.returncode}): {tail}")
        return text


def _claude(messages: list, *, model: str | None, effort: str | None, timeout: int,
            output_schema: dict | None = None) -> str:
    """Герметичный headless-запрос: тот же контракт, что у десктопного адаптера.

    - инструкции и system-сообщения — настоящий системный промпт через
      --system-prompt-file (файл обходит лимит командной строки Windows);
    - --tools "" запрещает инструменты на уровне CLI, для картинок — только Read;
    - --strict-mcp-config и --setting-sources "" отключают MCP и settings
      пользователя (хуки, apiKeyHelper, CLAUDE.md); --bare не подходит: он
      выключает OAuth;
    - усилие через --effort, для старых CLI — бюджет thinking через env.
    """
    command = _command("claude")
    if not command:
        raise RuntimeError("Claude Code не найден: установите claude и выполните /login")
    caps = _claude_capabilities(command)
    with tempfile.TemporaryDirectory(prefix="ddna-claude-") as tmpdir:
        tmp = Path(tmpdir)
        system_texts, rest = _split_system(messages) if caps["system_prompt_file"] else ([], list(messages))
        prompt, images = _materialize(rest, tmp)
        rule = agent_contract.load().tool_rule("read-images" if images else "none")
        args = [command, "-p", "--output-format", "json", "--model", model or CLAUDE_DEFAULT_MODEL]
        if caps["setting_sources"]:
            args += ["--setting-sources", ""]
        if caps["strict_mcp_config"]:
            args.append("--strict-mcp-config")
        if caps["tools"]:
            args += ["--tools", "Read" if images else ""]
        if images:
            args += ["--allowedTools", "Read"]
        env = _claude_subscription_env()
        if caps["effort"]:
            args += ["--effort", effort if effort in _CLAUDE_EFFORT_LEVELS else "medium"]
        else:
            budget = _CLAUDE_THINKING.get(effort or "medium", 0)
            if budget:
                env["MAX_THINKING_TOKENS"] = str(budget)
        structured = False
        if isinstance(output_schema, dict) and output_schema:
            if caps["json_schema"]:
                # structured_output в JSON-конверте; внутри CLI это отдельный ход,
                # поэтому --max-turns не ограничиваем.
                args += ["--json-schema", json.dumps(output_schema, ensure_ascii=False)]
                structured = True
        if caps["system_prompt_file"]:
            system_file = tmp / "system-prompt.md"
            system_file.write_text("\n\n".join([rule, *system_texts]), encoding="utf-8")
            args += ["--system-prompt-file", str(system_file)]
            stdin_text = prompt
        else:
            stdin_text = f"{rule}\n\n{prompt}"
        done = _run(args, stdin_text=stdin_text, cwd=tmp, timeout=timeout, env=env)
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
            if structured and envelope.get("structured_output") is not None:
                return json.dumps(envelope["structured_output"], ensure_ascii=False)
            result = envelope.get("result")
            if isinstance(result, str):
                return result.strip()
        return raw


def chat(provider: str, messages: list, *, model: str | None = None, effort: str | None = None,
         timeout: int | None = None, output_schema: dict | None = None) -> str:
    timeout = int(timeout or DEFAULT_TIMEOUT)
    if provider == "codex":
        return _codex(messages, model=model, effort=effort, timeout=timeout, output_schema=output_schema)
    if provider == "claude":
        return _claude(messages, model=model, effort=effort, timeout=timeout, output_schema=output_schema)
    raise ValueError(f"unknown CLI provider: {provider}")
