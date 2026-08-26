"""Продакшен LLM-клиент DesignAI Web (ранее жил в spike/run_test.py).

Только stdlib. Текстовые и vision-вызовы идут напрямую в OpenAI API и Kimi API
(OpenAI-совместимый формат), без OpenRouter. Модель задаётся композитным
slug'ом «provider/model»; записи цепочки без ключа в env пропускаются —
работает тот аккаунт, который подключён.
Провайдер «zcode» ключа не требует вообще: он вызывает локальный
авторизованный ZCode CLI (coding plan Z.AI) — приложение работает из коробки
на аккаунте ZCode, без ключей open.bigmodel.cn.
Таймауты: LLM_TIMEOUT_S (по умолчанию 120с), раньше было 600с.

Контракт параметров: ChatRequest (типизированный provider-нейтральный
envelope). Всё, что целевой провайдер не умеет, либо падает явным
ValueError (hard-поля), либо возвращается в transport.dropped с причиной —
молчаливых потерь параметров нет. Секретов в envelope нет: ключи
резолвятся из env в момент вызова.
"""
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent)

# таймаут одного LLM-вызова; генерация IR обычно 10-60с
TIMEOUT = int(os.environ.get("LLM_TIMEOUT_S", "120"))


def load_dotenv(path: Path | None = None) -> int:
    """KEY=VALUE из .env в os.environ (только если ключ ещё не задан).
    Возвращает число установленных ключей. Без зависимостей."""
    p = path or (ROOT / ".env")
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


load_dotenv()

PROVIDERS = {
    # Прямые транспорты продукта. Модель выбирается из ROUTING по роли.
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "env": "OPENAI_API_KEY",
    },
    "kimi": {
        "url": "https://api.kimi.com/coding/v1/chat/completions",
        "env": "KIMI_API_KEY",
        "base_env": "KIMI_BASE_URL",  # опциональный оверрайд базового URL
    },
    "glm": {
        # Zhipu GLM: OpenAI-совместимый v4 endpoint
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "env": "GLM_API_KEY",
        "base_env": "GLM_BASE_URL",
    },
    "zai": {
        # Прямой Z.AI GLM: отдельный провайдер/ключ, хост api.z.ai. Не путать с
        # Zhipu (bigmodel.cn) — ключи и хосты не смешиваются. Coding-plan
        # endpoint — только явный opt-in: ZAI_ENDPOINT=coding.
        "url": "https://api.z.ai/api/paas/v4/chat/completions",
        "coding_url": "https://api.z.ai/api/coding/paas/v4/chat/completions",
        "endpoint_env": "ZAI_ENDPOINT",
        "env": "ZAI_API_KEY",
        "base_env": "ZAI_BASE_URL",
    },
    "grok": {
        # xAI Grok: OpenAI-совместимый v1 endpoint
        "url": "https://api.x.ai/v1/chat/completions",
        "env": "XAI_API_KEY",
    },
    # Локальный ZCode CLI: без ключа, через авторизованный login Z.AI
    # (coding plan). Не HTTP-транспорт — обрабатывается отдельно в chat().
    "zcode": {
        "url": "",
        "env": "",  # ключ не нужен; доступность = наличие CLI и login
    },
}

# Роутинг моделей по ролям (роль ноды → [основная, fallback]).
# Каждая запись — композитный slug «provider/model» (разбор по первому '/').
# Если у записи нет ключа провайдера в env — она пропускается: так цепочка
# сама выбирает подключённый аккаунт (только Kimi → Kimi, только OpenAI → OpenAI).
# zcode/GLM-5.3 стоит последним в текстовых цепочках: локальный ZCode CLI —
# вход «Z.AI без API-ключа» (login Z.AI, coding plan); discovery стандартной
# установки + override через ZCODE_CLI.
# Vision не включён: модели coding-плана (GLM-5.x) не принимают
# inline-изображения на этом эндпоинте — vision остаётся на прямых API.
# Любую роль можно переопределить env: LLM_MODELS_<ROLE> (через запятую).
# Текущий роутинг (ветка GLM-5.3): все роли — glm/glm-5.3 (Zhipu) с запасным
# zai/glm-5.3 (прямой Z.AI), затем openai/gpt-5.6-sol и kimi/k3;
# vision-роли — glm/glm-5.3 с запасом openai/kimi (обе vision-capable).
STRONG = CHEAP = ["glm/glm-5.3", "zai/glm-5.3", "openai/gpt-5.6-sol", "kimi/k3", "grok/grok-4.6", "zcode/GLM-5.3"]
VISION = ["glm/glm-5.3", "openai/gpt-5.6-sol", "kimi/k3"]
ROUTING = {
    # канонические роли владельца
    "prompt_enhancer": STRONG,
    "planner":    STRONG,
    "motion_director": STRONG,
    "generator":  STRONG,
    "reskin":     STRONG,
    "repair":     CHEAP,
    "style_analysis": STRONG,
    "vision":     VISION,
    "vision_fast": VISION,
    "vision_pixel_qa": VISION,
    "judge":      STRONG,
    # Премиальный Quality Pass: независимая оценка и адресная починка.
    "quality_judge": STRONG,
    "quality_repair": STRONG,
    # дополнительные роли
    "edit":       STRONG,
    "derive":     STRONG,
    "optimizer":  CHEAP,
    "tokens":     STRONG,
    "components": STRONG,
    "clone":      CHEAP,
    "blockparse": CHEAP,
    # Source Import geometry stays deterministic; the model labels only
    # ambiguous rendered containers — it is not the pixel/layout engine.
    "source_semantics": CHEAP,
    "source_vision_audit": VISION,
    "reproduce":  VISION,
    "a11y":       STRONG,
    "docs":       CHEAP,
    # legacy-роли (старые вызовы и env-оверрайды)
    "mechanics":  CHEAP,
    "taste":      STRONG,
}


def routing_models(role: str) -> list:
    env_key = "LLM_MODELS_" + role.upper()
    if os.environ.get(env_key):
        return [m.strip() for m in os.environ[env_key].split(",") if m.strip()]
    return list(ROUTING.get(role, ROUTING["mechanics"]))


def _valid_model_slug(slug) -> bool:
    """Slug модели попадает в URL и аргументы API: только безопасные имена.
    Запрещены ведущие/концевые слеши, пустые сегменты и '..' (path traversal)."""
    if not isinstance(slug, str) or not slug:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", slug):
        return False
    if slug.startswith("/") or slug.endswith("/"):
        return False
    return all(seg and seg != ".." for seg in slug.split("/"))


def _check_model_slug(slug) -> None:
    if not _valid_model_slug(slug):
        raise ValueError(f"недопустимый model slug: {slug!r}")


# --------------------------------------------------------------------------
# Типизированный provider-нейтральный request envelope (зеркало desktop
# provider-envelope.mjs). Молчаливых потерь параметров нет:
#  - hard-поля, которые провайдер не умеет вообще, -> ValueError до сети;
#  - value-несовместимости снимаются adapt_for_provider() и возвращаются
#    списком dropped [{field, reason}] в transport-блоке результата.
# --------------------------------------------------------------------------

REASONING_EFFORTS = ("minimal", "low", "medium", "high", "max", "xhigh")
_ROLES = {"system", "user", "assistant", "tool"}
_TOOL_CHOICES = {"auto", "none", "required"}
_MESSAGE_FIELDS = {"role", "content", "tool_calls", "toolCalls", "tool_call_id", "toolCallId", "name", "toolName"}
_TOOL_CALL_FIELDS = {"id", "type", "function", "name", "arguments"}
_TOOL_CALL_FN_FIELDS = {"name", "arguments"}
_TOOL_WRAPPER_FIELDS = {"type", "function"}
_TOOL_FN_FIELDS = {"name", "description", "parameters"}
_TEXT_PART_FIELDS = {"type", "text"}
_IMAGE_PART_FIELDS = {"type", "image_url"}
_IMAGE_URL_FIELDS = {"url", "detail"}
_RESPONSE_SCHEMA_FIELDS = {"name", "schema"}
_KNOWN_OPTION_PROVIDERS = {"openai", "kimi", "glm", "zai", "zcode", "grok", "codex"}
PROVIDER_OPTIONS_MAX_BYTES = 8_192
PROVIDER_OPTIONS_MAX_DEPTH = 8
MAX_MESSAGE_CHARS = 400_000
MAX_STOP_CHARS = 256
MAX_ID_CHARS = 128
MAX_TIMEOUT_S = 600
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
RESERVED_WIRE_FIELDS = {
    "model", "messages", "system", "tools", "tool_choice", "response_format",
    "reasoning", "reasoning_effort", "thinking", "stream",
    "temperature", "top_p", "max_tokens", "max_completion_tokens", "seed",
    "stop", "parallel_tool_calls", "user", "user_id", "request_id", "metadata",
}
FORBIDDEN_OPTION_KEYS = {"__proto__", "constructor", "prototype"}

PROVIDER_LIMITS = {
    # hard: поля, которые провайдер не может передать в принципе.
    # value: {поле: причина} — снимается с явной записью в dropped.
    "openai": {"hard": (), "value": {}},
    "grok": {"hard": (), "value": {}},
    "glm": {
        "hard": ("parallel_tool_calls",),
        "value": {
            "reasoning.budgetTokens": "GLM-5.3 принимает reasoning_effort low|high|max, без токен-бюджета",
            "seed": "GLM v4 endpoint отвергает seed",
        },
    },
    "zai": {
        # Та же v4-семья API, что и Zhipu glm, но на хосте api.z.ai.
        "hard": ("parallel_tool_calls",),
        "value": {
            "reasoning.budgetTokens": "GLM-5.3 принимает reasoning_effort low|high|max, без токен-бюджета",
            "seed": "GLM v4 endpoint отвергает seed",
        },
    },
    "kimi": {
        # Kimi coding API (k3 series) supports function calling, tool_choice and
        # parallel_tool_calls. Reasoning controls, forced response_format, stop
        # sequences and seed are not accepted on the managed coding endpoint.
        "hard": (),
        "value": {
            "temperature": "kimi/k3 managed coding endpoint applies temperature server-side",
            "topP": "kimi/k3 игнорирует top_p",
            "reasoning": "у kimi/k3 нет управления reasoning на этом endpoint",
            "responseFormat": "kimi/k3 чаще всего отвергает response_format; JSON уже запрошен промптом",
            "stop": "kimi/k3 не принимает stop-последовательности",
            "seed": "kimi/k3 не поддерживает seed",
        },
    },
    "zcode": {
        "hard": ("top_p", "max_output_tokens", "reasoning", "response_format",
                 "stop", "seed", "tool_choice", "parallel_tool_calls", "tools",
                 "provider_options", "multimodal"),
        "value": {"temperature": "ZCode CLI управляет сэмплингом сам"},
    },
}


def _utf8_len(value: str) -> int:
    return len(value.encode("utf-8"))


def _bounded_id(value, field: str, issues: list[str]) -> None:
    if not isinstance(value, str) or not value or _utf8_len(value) > MAX_ID_CHARS:
        issues.append(f"{field}: нужна непустая строка ≤ {MAX_ID_CHARS} UTF-8 байт")


def _reject_unknown_keys(obj: dict, allowed: set[str], field: str, issues: list[str]) -> None:
    extra = sorted(set(obj) - allowed)
    if extra:
        issues.append(f"{field}: unknown field {extra} — it would be silently ignored")


def _is_plain_dict(value) -> bool:
    return isinstance(value, dict) and type(value) is dict


def _check_json_safe(value, field: str, issues: list[str], seen: set, depth: int) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            issues.append(f"{field}: non-finite number is not JSON-safe")
        return
    if isinstance(value, list):
        if id(value) in seen:
            issues.append(f"{field}: cyclic structure is not JSON-safe")
            return
        if depth > PROVIDER_OPTIONS_MAX_DEPTH:
            issues.append(f"{field}: nesting deeper than {PROVIDER_OPTIONS_MAX_DEPTH} is not supported")
            return
        seen.add(id(value))
        for index, item in enumerate(value):
            _check_json_safe(item, f"{field}[{index}]", issues, seen, depth + 1)
        seen.discard(id(value))
        return
    if _is_plain_dict(value):
        if id(value) in seen:
            issues.append(f"{field}: cyclic structure is not JSON-safe")
            return
        if depth > PROVIDER_OPTIONS_MAX_DEPTH:
            issues.append(f"{field}: nesting deeper than {PROVIDER_OPTIONS_MAX_DEPTH} is not supported")
            return
        seen.add(id(value))
        for key, item in value.items():
            if key in FORBIDDEN_OPTION_KEYS:
                issues.append(f"{field}.{key}: forbidden key (prototype-pollution risk)")
                continue
            _check_json_safe(item, f"{field}.{key}", issues, seen, depth + 1)
        seen.discard(id(value))
        return
    if isinstance(value, dict):
        issues.append(f"{field}: non-plain object is not JSON-safe")
        return
    issues.append(f"{field}: non-serializable type \"{type(value).__name__}\"")


def _validate_provider_options(options) -> list[str]:
    if options is None:
        return []
    issues: list[str] = []
    if not _is_plain_dict(options):
        issues.append("provider_options: must be an object keyed by provider")
        return issues
    for key, value in options.items():
        if key not in _KNOWN_OPTION_PROVIDERS:
            issues.append(f"providerOptions.{key}: unknown provider key \"{key}\"")
            continue
        if not _is_plain_dict(value):
            issues.append(f"providerOptions.{key}: extras must be a JSON object")
            continue
        for option in value:
            if option in RESERVED_WIRE_FIELDS:
                issues.append(
                    f"providerOptions.{key}.{option}: reserved canonical wire field \"{option}\" cannot be overridden via providerOptions")
        _check_json_safe(value, f"providerOptions.{key}", issues, set(), 1)
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            encoded = ""
        if encoded and _utf8_len(encoded) > PROVIDER_OPTIONS_MAX_BYTES:
            issues.append(f"providerOptions.{key}: exceeds {PROVIDER_OPTIONS_MAX_BYTES} UTF-8 bytes")
    return issues


def _validate_stop(stop) -> list[str]:
    if stop is None:
        return []
    issues: list[str] = []
    if isinstance(stop, str):
        stops = [stop]
    elif isinstance(stop, list):
        stops = stop
    else:
        return ["stop: must be a string or an array of strings"]
    if len(stops) > 4:
        issues.append("stop: список до 4 строк")
    for index, item in enumerate(stops):
        if not isinstance(item, str):
            issues.append(f"stop[{index}]: must be a string")
        elif _utf8_len(item) > MAX_STOP_CHARS:
            issues.append(f"stop[{index}]: exceeds {MAX_STOP_CHARS} UTF-8 bytes")
    return issues


def _validate_tools(tools) -> list[str]:
    if not isinstance(tools, list):
        return ["tools: must be an array"]
    issues: list[str] = []
    if len(tools) > 64:
        issues.append("tools: at most 64 tools are supported")
    for index, tool in enumerate(tools):
        field = f"tools[{index}]"
        if not isinstance(tool, dict):
            issues.append(f"{field}: must be an object")
            continue
        wrapped = "function" in tool
        if wrapped:
            _reject_unknown_keys(tool, _TOOL_WRAPPER_FIELDS, field, issues)
            if tool.get("type") not in (None, "function"):
                issues.append(f'{field}.type: tool type must be "function"')
            if not isinstance(tool.get("function"), dict):
                issues.append(f"{field}.function: must be an object")
                continue
            fn = tool["function"]
        else:
            _reject_unknown_keys(tool, _TOOL_FN_FIELDS, field, issues)
            fn = tool
        _reject_unknown_keys(fn, _TOOL_FN_FIELDS, f"{field}.function", issues)
        name = fn.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
            issues.append(f"{field}.name: tool name must be 1-128 [A-Za-z0-9_-]")
        description = fn.get("description")
        if description is not None:
            if not isinstance(description, str):
                issues.append(f"{field}.function.description: must be a string")
            elif _utf8_len(description) > 1024:
                issues.append(f"{field}.function.description: exceeds 1024 UTF-8 bytes")
        parameters = fn.get("parameters")
        if parameters is not None and not isinstance(parameters, dict):
            issues.append(f"{field}.function.parameters: must be a JSON Schema object")
    return issues


def _validate_content(content, field: str, issues: list[str], *, allow_image: bool = True) -> None:
    if isinstance(content, str):
        if _utf8_len(content) > MAX_MESSAGE_CHARS:
            issues.append(f"{field}: exceeds {MAX_MESSAGE_CHARS} UTF-8 bytes")
        return
    if not isinstance(content, list):
        issues.append(f"{field}: must be a string or an array of parts")
        return
    if not content:
        issues.append(f"{field}: empty content array")
        return
    if len(content) > 32:
        issues.append(f"{field}: at most 32 parts are supported")
    for index, part in enumerate(content[:32]):
        part_field = f"{field}[{index}]"
        if not isinstance(part, dict):
            issues.append(f"{part_field}: part must be an object")
            continue
        if part.get("type") == "text":
            _reject_unknown_keys(part, _TEXT_PART_FIELDS, part_field, issues)
            text = part.get("text")
            if not isinstance(text, str):
                issues.append(f"{part_field}.text: must be a string")
            elif _utf8_len(text) > MAX_MESSAGE_CHARS:
                issues.append(f"{part_field}.text: exceeds {MAX_MESSAGE_CHARS} UTF-8 bytes")
            continue
        if part.get("type") == "image_url":
            _reject_unknown_keys(part, _IMAGE_PART_FIELDS, part_field, issues)
            if not allow_image:
                issues.append(f"{part_field}: image parts are not valid for tool messages")
                continue
            image = part.get("image_url")
            if not isinstance(image, dict):
                issues.append(f"{part_field}.image_url: must be an object")
                continue
            _reject_unknown_keys(image, _IMAGE_URL_FIELDS, f"{part_field}.image_url", issues)
            url = image.get("url")
            if not isinstance(url, str):
                issues.append(f"{part_field}.image_url.url: must be a string")
            elif _utf8_len(url) > 8_000_000:
                issues.append(f"{part_field}.image_url.url: exceeds 8000000 UTF-8 bytes")
            elif not (url.startswith("https://") or re.match(r"^data:image/[a-z0-9.+-]+;base64,", url)):
                issues.append(f"{part_field}.image_url.url: must be a data:image or https URL")
            detail = image.get("detail")
            if detail is not None and detail not in ("auto", "low", "high"):
                issues.append(f"{part_field}.image_url.detail: must be auto|low|high")
            continue
        issues.append(f"{part_field}.type: unsupported content part {part.get('type')!r}")


def _has_multimodal(messages) -> bool:
    return any(
        isinstance(message, dict)
        and isinstance(message.get("content"), list)
        and any(isinstance(part, dict) and part.get("type") != "text"
                for part in message["content"])
        for message in messages or []
    )


def _validate_messages(messages) -> list[str]:
    issues: list[str] = []
    if not isinstance(messages, list) or not messages:
        issues.append("messages: нужен хотя бы один message")
        return issues
    if len(messages) > 128:
        issues.append("messages: at most 128 entries are supported")
    for i, message in enumerate(messages[:128]):
        field = f"messages[{i}]"
        if not isinstance(message, dict):
            issues.append(f"{field}: message must be an object")
            continue
        _reject_unknown_keys(message, _MESSAGE_FIELDS, field, issues)
        role = message.get("role")
        if role not in _ROLES:
            issues.append(f"{field}: роль должна быть system/user/assistant/tool")
            continue
        content = message.get("content")
        if message.get("tool_calls") is not None and message.get("toolCalls") is not None:
            issues.append(f"{field}.tool_calls: provide only one of tool_calls or toolCalls")
        calls = message.get("tool_calls") if message.get("tool_calls") is not None else message.get("toolCalls")
        if role == "tool":
            if calls is not None:
                issues.append(f"{field}.tool_calls: tool messages cannot contain assistant tool_calls")
            if message.get("tool_call_id") is not None and message.get("toolCallId") is not None:
                issues.append(f"{field}.tool_call_id: provide only one alias")
            if message.get("name") is not None and message.get("toolName") is not None:
                issues.append(f"{field}.name: provide only one alias")
            tool_id = message.get("tool_call_id") if message.get("tool_call_id") is not None else message.get("toolCallId")
            _bounded_id(tool_id, f"{field}.tool_call_id", issues)
            name = message.get("name") if message.get("name") is not None else message.get("toolName")
            if name is not None:
                _bounded_id(name, f"{field}.name", issues)
            if content in (None, "", []):
                issues.append(f"{field}.content: tool message content is empty")
            else:
                _validate_content(content, f"{field}.content", issues, allow_image=False)
            continue

        if message.get("tool_call_id") is not None or message.get("toolCallId") is not None or message.get("toolName") is not None:
            issues.append(f"{field}.tool_call_id: only tool messages may carry tool_call_id/toolName")
        name = message.get("name")
        if name is not None:
            _bounded_id(name, f"{field}.name", issues)
        if role != "assistant" and calls is not None:
            issues.append(f"{field}.tool_calls: only assistant messages may contain tool_calls")

        has_calls = role == "assistant" and calls is not None
        if has_calls:
            try:
                seen: set = set()
                if not isinstance(calls, list):
                    raise ValueError(f"{field}.tool_calls: must be an array")
                if len(calls) > 32:
                    raise ValueError(f"{field}.tool_calls: более 32 вызовов")
                for j, call in enumerate(calls):
                    _validate_tool_call(call, f"{field}.tool_calls[{j}]", seen)
                    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                    args = fn.get("arguments") if "arguments" in fn else call.get("arguments")
                    _canonical_tool_arguments(args, f"{field}.tool_calls[{j}].function.arguments")
            except ValueError as error:
                issues.append(str(error))
        if content in (None, "", []):
            if has_calls and isinstance(calls, list) and calls:
                continue
            issues.append(f"{field}.content: пустой")
        else:
            _validate_content(content, f"{field}.content", issues)
    return issues


@dataclasses.dataclass
class ChatRequest:
    """Провайдер-нейтральный запрос: поля переживают любой хоп без потерь."""

    messages: list
    provider: str | None = None
    model: str | None = None
    system: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    reasoning_budget_tokens: int | None = None
    response_format: str | None = None          # json_object | json_schema | text
    response_json_schema: dict | None = None    # {name, schema}
    stop: list | None = None
    seed: int | None = None
    stream: bool | None = None
    tool_choice: str | dict | None = None
    parallel_tool_calls: bool | None = None
    tools: list | None = None
    provider_options: dict | None = None
    timeout_s: int | None = None
    request_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex[:16])

    def validate(self) -> list[str]:
        issues = []
        issues.extend(_validate_messages(self.messages))
        if self.provider is not None and self.provider not in (*PROVIDERS, "auto"):
            issues.append(f"provider: неизвестный провайдер {self.provider!r}")
        if self.model is not None:
            if not isinstance(self.model, str):
                issues.append("model: must be a provider/model string")
            else:
                try:
                    _check_model_slug(self.model)
                except ValueError as error:
                    issues.append(f"model: {error}")
        if self.temperature is not None:
            if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)):
                issues.append("temperature: должен быть числом в [0, 2]")
            elif not (0 <= self.temperature <= 2):
                issues.append("temperature: должен быть в [0, 2]")
        if self.top_p is not None:
            if isinstance(self.top_p, bool) or not isinstance(self.top_p, (int, float)):
                issues.append("top_p: должен быть числом в [0, 1]")
            elif not (0 <= self.top_p <= 1):
                issues.append("top_p: должен быть в [0, 1]")
        if self.max_output_tokens is not None:
            if (isinstance(self.max_output_tokens, bool)
                    or not isinstance(self.max_output_tokens, int)
                    or self.max_output_tokens <= 0 or self.max_output_tokens > 1_000_000):
                issues.append("max_output_tokens: положительное целое")
        if self.reasoning_effort is not None and self.reasoning_effort not in REASONING_EFFORTS:
            issues.append(f"reasoning_effort: один из {REASONING_EFFORTS}")
        if self.reasoning_budget_tokens is not None:
            if (isinstance(self.reasoning_budget_tokens, bool)
                    or not isinstance(self.reasoning_budget_tokens, int)
                    or self.reasoning_budget_tokens <= 0 or self.reasoning_budget_tokens > 128_000):
                issues.append("reasoning_budget_tokens: положительное целое ≤ 128000")
        if self.response_format not in (None, "json_object", "json_schema", "text"):
            issues.append("response_format: json_object|json_schema|text")
        if self.response_format == "json_schema":
            schema = self.response_json_schema or {}
            if not isinstance(schema, dict) or not isinstance(schema.get("schema"), dict):
                issues.append("response_json_schema: нужен {name, schema}")
            else:
                _reject_unknown_keys(schema, _RESPONSE_SCHEMA_FIELDS, "response_json_schema", issues)
                if schema.get("name") is not None:
                    name = schema.get("name")
                    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > MAX_ID_CHARS:
                        issues.append("response_json_schema.name: непустая строка ≤ 128 UTF-8 байт")
        if self.tool_choice is not None:
            if isinstance(self.tool_choice, str) and self.tool_choice in _TOOL_CHOICES:
                pass
            elif isinstance(self.tool_choice, dict) and self.tool_choice.get("name"):
                extra = set(self.tool_choice) - {"name"}
                if extra:
                    issues.append(f"tool_choice: unknown field {sorted(extra)}")
                name = self.tool_choice.get("name")
                if not isinstance(name, str) or not name or len(name.encode("utf-8")) > MAX_ID_CHARS:
                    issues.append("tool_choice.name: непустая строка ≤ 128 UTF-8 байт")
            else:
                issues.append("tool_choice: auto|none|required|{name}")
        if self.tools is not None:
            issues.extend(_validate_tools(self.tools))
        if self.parallel_tool_calls is not None and not isinstance(self.parallel_tool_calls, bool):
            issues.append("parallel_tool_calls: must be a boolean")
        if self.stream is not None and not isinstance(self.stream, bool):
            issues.append("stream: must be a boolean")
        elif self.stream:
            issues.append("stream: десктоп-транспорты не стримят; используйте обычный запрос")
        issues.extend(_validate_stop(self.stop))
        if self.seed is not None and (not isinstance(self.seed, int)
                                      or isinstance(self.seed, bool)
                                      or self.seed < 0):
            issues.append("seed: неотрицательное целое")
        if self.timeout_s is not None:
            if (isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, int)
                    or self.timeout_s < 1):
                issues.append("timeout_s: ≥ 1")
            elif self.timeout_s > MAX_TIMEOUT_S:
                issues.append(f"timeout_s: must be ≤ {MAX_TIMEOUT_S}")
        if self.system is not None:
            if not isinstance(self.system, str):
                issues.append("system: must be a string")
            elif len(self.system.encode("utf-8")) > MAX_MESSAGE_CHARS:
                issues.append(f"system: exceeds {MAX_MESSAGE_CHARS} UTF-8 bytes")
        if not isinstance(self.request_id, str) or not _REQUEST_ID_RE.fullmatch(self.request_id):
            issues.append("request_id: must match [A-Za-z0-9-]{1,64} (no silent truncation)")
        issues.extend(_validate_provider_options(self.provider_options))
        return issues

    def check(self) -> "ChatRequest":
        issues = self.validate()
        if issues:
            raise ValueError("некорректный ChatRequest: " + "; ".join(issues))
        return self

    def present_fields(self) -> set[str]:
        fields = set()
        for name in ("temperature", "top_p", "max_output_tokens", "response_format",
                     "stop", "seed", "tool_choice", "parallel_tool_calls", "tools"):
            if getattr(self, name) is not None:
                fields.add(name)
        if self.reasoning_effort is not None:
            fields.add("reasoning")
        if self.provider_options:
            fields.add("provider_options")
        if _has_multimodal(self.messages):
            fields.add("multimodal")
        return fields

    def assert_supported(self, provider: str) -> None:
        limits = PROVIDER_LIMITS.get(provider)
        if limits is None:
            return
        present = self.present_fields()
        unsupported = sorted(present & set(limits["hard"]))
        if unsupported:
            raise ValueError(
                f"провайдер {provider!r} не поддерживает: {', '.join(unsupported)}")
        if provider == "zai":
            # Официальные ограничения Z.AI v4 (GLM-5.3): громкая ошибка ДО
            # сети — не форвардим заведомый 400 и не снимаем молча.
            issues = []
            if self.temperature is not None and not (0 <= self.temperature <= 1):
                issues.append("temperature: Z.AI GLM-5.3 принимает [0, 1]")
            if self.top_p is not None and not (0.01 <= self.top_p <= 1):
                issues.append("top_p: Z.AI GLM-5.3 принимает [0.01, 1]")
            if self.max_output_tokens is not None and self.max_output_tokens > 131072:
                issues.append("max_output_tokens: Z.AI GLM-5.3 ≤ 131072")
            if self.tool_choice is not None and self.tool_choice != "auto":
                issues.append('tool_choice: Z.AI GLM-5.3 поддерживает только "auto"')
            if self.response_format == "json_schema":
                issues.append("response_format: Z.AI GLM-5.3 поддерживает только text|json_object")
            stop_count = 1 if isinstance(self.stop, str) else len(self.stop or [])
            if stop_count > 1:
                issues.append("stop: Z.AI GLM-5.3 поддерживает одно stop-слово")
            if issues:
                raise ValueError("провайдер 'zai' не поддерживает: " + "; ".join(issues))
        if provider == "grok" and self.stop is not None:
            # grok-4.6: stop-последовательности несовместимы — громко, до сети.
            raise ValueError("провайдер 'grok' не поддерживает: stop (grok-4.6 не принимает stop-последовательности)")

    def adapt_for_provider(self, provider: str) -> tuple["ChatRequest", list[dict]]:
        """Снять value-несовместимости; каждая снятая пара -> dropped."""
        limits = PROVIDER_LIMITS.get(provider) or {"hard": (), "value": {}}
        self.assert_supported(provider)
        adapted = dataclasses.replace(self)
        dropped: list[dict] = []

        def drop(field: str, attr: str, reason: str) -> None:
            if getattr(adapted, attr) is None:
                return
            dropped.append({"field": field, "reason": reason})
            setattr(adapted, attr, None)

        value = limits["value"]
        if "temperature" in value and adapted.temperature is not None and adapted.temperature != 1:
            drop("temperature", "temperature", value["temperature"])
        if "topP" in value:
            drop("topP", "top_p", value["topP"])
        if "reasoning" in value:
            drop("reasoning", "reasoning_effort", value["reasoning"])
        if "responseFormat" in value:
            drop("responseFormat", "response_format", value["responseFormat"])
        if "stop" in value:
            drop("stop", "stop", value["stop"])
        if "seed" in value:
            drop("seed", "seed", value["seed"])
        if "parallelToolCalls" in value:
            drop("parallelToolCalls", "parallel_tool_calls", value["parallelToolCalls"])
        if "reasoning.budgetTokens" in value and adapted.reasoning_budget_tokens is not None:
            adapted.reasoning_budget_tokens = None
            dropped.append({"field": "reasoning.budgetTokens",
                            "reason": value["reasoning.budgetTokens"]})
        if adapted.provider_options:
            own = adapted.provider_options.get(provider)
            foreign = [k for k in adapted.provider_options if k != provider]
            adapted.provider_options = {provider: own} if own else {}
            for key in foreign:
                dropped.append({"field": f"providerOptions.{key}",
                                "reason": f"экстра-опции {key!r} не отправляются в {provider!r}"})
        return adapted, dropped

    def to_openai_payload(self, provider: str, model_id: str,
                          *, json_mode: bool = False) -> tuple[dict, list[dict]]:
        """Wire-формат OpenAI-совместимой семьи (openai/kimi/glm/grok)."""
        adapted, dropped = self.adapt_for_provider(provider)
        payload: dict = {"model": model_id, "messages": _wire_messages(adapted)}
        if adapted.system:
            payload["messages"].insert(0, {"role": "system", "content": adapted.system})
        if adapted.temperature is not None:
            payload["temperature"] = adapted.temperature
        if adapted.top_p is not None:
            payload["top_p"] = adapted.top_p
        if adapted.max_output_tokens is not None:
            key = "max_completion_tokens" if provider == "openai" else "max_tokens"
            payload[key] = adapted.max_output_tokens
        if adapted.reasoning_effort is not None:
            if provider in ("glm", "zai"):
                # GLM-5.3: reasoning всегда включён — thinking.type "disabled"
                # удалён и отвергается сервером. reasoning_effort принимает
                # low|high|max (max рекомендован для coding). Legacy-значения
                # нормализуются ЯВНО, с записью в dropped — не молча.
                payload["thinking"] = {"type": "enabled"}
                effort = adapted.reasoning_effort
                if effort in ("low", "high", "max"):
                    payload["reasoning_effort"] = effort
                else:
                    mapped = "low" if effort == "minimal" else "high"
                    payload["reasoning_effort"] = mapped
                    dropped.append({"field": "reasoning.effort",
                                    "reason": f"GLM-5.3 принимает reasoning_effort low|high|max; {effort!r} нормализован в {mapped!r}"})
            elif provider == "grok":
                # grok-4.6 (xAI): reasoning_effort low|medium|high|xhigh,
                # отключить reasoning нельзя — minimal/max нормализуются ЯВНО.
                effort = adapted.reasoning_effort
                if effort in ("low", "medium", "high", "xhigh"):
                    payload["reasoning_effort"] = effort
                else:
                    mapped = "low" if effort == "minimal" else "xhigh"
                    payload["reasoning_effort"] = mapped
                    dropped.append({"field": "reasoning.effort",
                                    "reason": f"grok-4.6 принимает reasoning_effort low|medium|high|xhigh (reasoning не отключается); {effort!r} нормализован в {mapped!r}"})
            else:
                payload["reasoning_effort"] = adapted.reasoning_effort
        if adapted.response_format == "json_schema":
            payload["response_format"] = {"type": "json_schema", "json_schema": adapted.response_json_schema}
        elif adapted.response_format in ("json_object", "text"):
            payload["response_format"] = {"type": adapted.response_format}
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        if adapted.stop is not None:
            payload["stop"] = [adapted.stop] if isinstance(adapted.stop, str) else list(adapted.stop)
        if adapted.seed is not None and provider not in ("glm", "zai"):
            payload["seed"] = adapted.seed
        if adapted.tools is not None:
            payload["tools"] = _wire_tools(adapted.tools)
        if adapted.tool_choice is not None:
            # {name: "..."} — это каноническая envelope-форма; на wire она
            # конвертируется в OpenAI-формат (зеркало provider-envelope.mjs).
            if isinstance(adapted.tool_choice, dict):
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": adapted.tool_choice["name"]},
                }
            else:
                payload["tool_choice"] = adapted.tool_choice
        if adapted.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = adapted.parallel_tool_calls
        if adapted.provider_options and provider in adapted.provider_options:
            extras = adapted.provider_options[provider]
            reserved = _validate_provider_options({provider: extras})
            if reserved:
                raise ValueError("некорректный ChatRequest: " + "; ".join(reserved))
            if extras:
                payload.update(extras)
        if "response_format" in payload and ("tools" in payload or adapted.tools):
            del payload["response_format"]
            dropped.append({"field": "responseFormat",
                            "reason": "tool-вызовы и принудительный формат ответа несовместимы"})
        return payload, dropped


def _wire_tools(tools: list) -> list[dict]:
    out = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        function = {"name": fn.get("name")}
        if fn.get("description") is not None:
            function["description"] = fn.get("description")
        function["parameters"] = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {
            "type": "object", "properties": {},
        }
        out.append({"type": "function", "function": function})
    return out


def _wire_messages(request: "ChatRequest") -> list[dict]:
    out = []
    for i, m in enumerate(request.messages):
        role = m.get("role")
        if role == "tool":
            wire_tool = {
                "role": "tool",
                "tool_call_id": m.get("tool_call_id") or m.get("toolCallId"),
                "content": _wire_content(m.get("content")),
            }
            name = m.get("name") or m.get("toolName")
            if name:
                wire_tool["name"] = name
            out.append(wire_tool)
            continue
        wire: dict = {"role": role}
        name = m.get("name")
        if name:
            wire["name"] = name
        content = _wire_content(m.get("content"))
        if content:
            wire["content"] = content
        tool_calls = m.get("tool_calls") or m.get("toolCalls")
        if tool_calls:
            # arguments канонизируются (object → deterministic JSON-строка,
            # строка — дословно после parse-валидации); структура (лимит 32,
            # shape, id/name, type, дубли) валидируется громко — всё ДО сети.
            if not isinstance(tool_calls, list):
                raise ValueError(f"messages[{i}].tool_calls: must be an array")
            if len(tool_calls) > 32:
                raise ValueError(f"messages[{i}].tool_calls: более 32 вызовов")
            seen_ids: set = set()
            wire_calls = []
            for j, call in enumerate(tool_calls):
                field = f"messages[{i}].tool_calls[{j}]"
                _validate_tool_call(call, field, seen_ids)
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                name = fn.get("name") or call.get("name")
                args = fn.get("arguments") if "arguments" in fn else call.get("arguments")
                wire_calls.append({
                    "id": call.get("id"),
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": _canonical_tool_arguments(
                            args, f"{field}.function.arguments"),
                    },
                })
            wire["tool_calls"] = wire_calls
        out.append(wire)
    return out


def _wire_content(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if not isinstance(part, dict):
                raise ValueError("message content part must be an object")
            if part.get("type") == "text":
                out.append({"type": "text", "text": part.get("text")})
            elif part.get("type") == "image_url":
                image = part.get("image_url")
                out.append({"type": "image_url", "image_url": dict(image) if isinstance(image, dict) else image})
            else:
                raise ValueError(f"unsupported message content part: {part.get('type')!r}")
        return out
    raise ValueError("message content must be a string or an array of parts")


MAX_TOOL_ARGUMENTS_CHARS = 16_000


def _canonical_tool_arguments(value, field: str = "arguments") -> str:
    """Контракт tool_call arguments (зеркало provider-envelope.mjs):
    Z.AI GLM-5.3 возвращает function.arguments ОБЪЕКТОМ — канонизируем в
    deterministic JSON-строку (sorted keys); строки (OpenAI/xAI) — дословно,
    без переформатирования и усечений, НО сначала parse-валидация: строка
    обязана быть JSON-объектом или массивом (malformed JSON и закодированные
    null/примитивы отвергаются). Лимиты — в UTF-8 БАЙТАХ, не в code points.
    None/примитивы/циклы/несериализуемые/oversize — громкая ValueError ДО
    сетевого раунда."""
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_TOOL_ARGUMENTS_CHARS:
            raise ValueError(f"{field}: строка длиннее {MAX_TOOL_ARGUMENTS_CHARS} UTF-8 байт")
        try:
            parsed = json.loads(value)
        except ValueError as error:
            raise ValueError(f"{field}: malformed JSON string") from error
        if not isinstance(parsed, (dict, list)):
            raise ValueError(f"{field}: arguments must encode a JSON object or array")
        return value
    if value is None:
        raise ValueError(f'{field}: null/missing arguments недопустимы — нужен объект или "{{}}"')
    if isinstance(value, bool) or not isinstance(value, (dict, list)):
        raise ValueError(f"{field}: примитив {type(value).__name__} — не tool arguments payload")
    try:
        out = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field}: не сериализуется ({error})") from error
    if len(out.encode("utf-8")) > MAX_TOOL_ARGUMENTS_CHARS:
        raise ValueError(f"{field}: сериализованные arguments длиннее {MAX_TOOL_ARGUMENTS_CHARS} UTF-8 байт")
    return out


def _validate_tool_call(call, field: str, seen_ids: set) -> None:
    """Структурная валидация tool_call из истории (зеркало extractContent):
    объект, type=function, непустые строковые id/name ≤ 128 UTF-8 байт,
    без дублей id — громко, ДО сети. Wire-форма {function:{name,arguments}}
    и плоская UI-форма {id,name,arguments} принимаются одинаково."""
    if not isinstance(call, dict):
        raise ValueError(f"{field}: tool_call должен быть объектом")
    extra = sorted(set(call) - _TOOL_CALL_FIELDS)
    if extra:
        raise ValueError(f"{field}: unknown field {extra} — it would be silently ignored")
    call_type = call.get("type")
    if call_type is not None and call_type != "function":
        raise ValueError(f'{field}.type: неподдерживаемый тип {call_type!r}')
    fn = call.get("function")
    if fn is not None and not isinstance(fn, dict):
        raise ValueError(f"{field}.function: должен быть объектом")
    fn = fn if isinstance(fn, dict) else {}
    extra_fn = sorted(set(fn) - _TOOL_CALL_FN_FIELDS)
    if extra_fn:
        raise ValueError(f"{field}.function: unknown field {extra_fn} — it would be silently ignored")
    name = fn.get("name") or call.get("name")
    call_id = call.get("id")
    for key, value in (("id", call_id), ("function.name", name)):
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 128:
            raise ValueError(f"{field}.{key}: нужна непустая строка ≤ 128 UTF-8 байт")
    if call_id in seen_ids:
        raise ValueError(f'{field}.id: дубликат tool_call id {call_id!r}')
    seen_ids.add(call_id)


def _provider_url(cfg: dict) -> str:
    """URL chat/completions провайдера. base_env — явный полный override базы;
    endpoint_env=coding — явный opt-in coding-plan endpoint (только Z.AI).
    Ключ провайдера никогда не уходит на чужой хост молча: любая смена хоста
    происходит только через эти явные env-настройки."""
    base = os.environ.get(cfg.get("base_env", ""), "")
    if base:
        return base.rstrip("/") + "/chat/completions"
    endpoint_env = cfg.get("endpoint_env", "")
    if endpoint_env and os.environ.get(endpoint_env, "").strip() == "coding":
        return cfg["coding_url"]
    return cfg["url"]


# --------------------------------------------------------------------------
# Провайдер «zcode»: локальный ZCode CLI с общим login Z.AI (coding plan).
# Ключей API не нужно — модель отвечает от имени учётки ZCode.
# CLI требует ~/.zcode/cli/config.json с явным провайдером; конфиг
# бутстрапится из ~/.zcode/v2/config.json (там лежит подключённый план).
# --------------------------------------------------------------------------

# Короткая инструкция headless-агенту: полный промпт лежит в TASK.md,
# потому что командная строка Windows ограничена ~32К символов.
ZCODE_TASK_PROMPT = (
    "Read the file TASK.md in the current working directory and complete "
    "the task it describes. Output only the final answer the task requires, "
    "nothing else. Do not read, create or modify any other files."
)

# Агент не должен пользоваться инструментами (мы хотим чистую генерацию
# текста); Read остаётся разрешённым, чтобы он прочёл TASK.md и вложения.
ZCODE_DENY_TOOLS = (
    "Bash Edit Write Glob Grep Agent Task WebFetch WebSearch TodoWrite Skill "
    "SendMessage CronCreate CronDelete CronList CronUpdate TaskOutput TaskStop "
    "EnterPlanMode ExitPlanMode AskUserQuestion"
)

ZCODE_MODEL_PREFERENCE = ["GLM-5.3", "GLM-5.2", "GLM-5-Turbo"]

# Стартовый запас сверх LLM-таймаута: загрузка CLI + чтение TASK.md агентом.
ZCODE_BOOT_GRACE_S = 45
# Пол agent-цикл CLI (reasoning-модель + чтение TASK.md) медленнее прямого API
# и высоковариативен (замерено 60–285с на полную генерацию IR): не даём коротким
# таймаутам ролей убивать большие генерации.
ZCODE_MIN_TIMEOUT_S = 420


def _zcode_cli_path() -> str | None:
    """Путь к zcode.cjs: явный ZCODE_CLI → стандартный путь установленного
    приложения (resources/glm/zcode.cjs). Это вход «Z.AI без API-ключа»
    (login Z.AI, coding plan) — владелец явно попросил автоподключение;
    override выигрывает, авторизацию проверяет zcode_available()."""
    override = os.environ.get("ZCODE_CLI", "").strip()
    if override and Path(override).exists():
        return override
    localappdata = os.environ.get("LOCALAPPDATA", "").strip()
    if localappdata:
        candidate = Path(localappdata) / "Programs" / "ZCode" / "resources" / "glm" / "zcode.cjs"
        if candidate.exists():
            return str(candidate)
    return None


def _zcode_node_path() -> str | None:
    return os.environ.get("ZCODE_NODE", "").strip() or shutil.which("node")


def _zcode_pick_provider(v2cfg: dict) -> tuple[str, str] | None:
    """Выбрать провайдера/модель из v2-конфига ZCode: активный coding plan."""
    providers = v2cfg.get("provider") or {}
    ordered = sorted(
        providers.items(),
        key=lambda kv: (0 if "coding-plan" in kv[0] and kv[1].get("enabled") else 1, kv[0]),
    )
    for pid, p in ordered:
        models = list((p.get("models") or {}).keys())
        if not models or not (p.get("options") or {}).get("baseURL"):
            continue
        for pref in ZCODE_MODEL_PREFERENCE:
            if pref in models:
                return pid, pref
        return pid, models[0]
    return None


def zcode_available() -> bool:
    """ZCode CLI установлен и авторизован (login Z.AI на месте).
    Идемпотентно бутстрапит ~/.zcode/cli/config.json из v2-конфига."""
    cli = _zcode_cli_path()
    if not cli:
        return False
    home = Path.home()
    if not (home / ".zcode" / "v2" / "credentials.json").exists():
        return False  # не авторизован (zcode login не выполнялся)
    cfg_path = home / ".zcode" / "cli" / "config.json"
    if cfg_path.exists():
        return True
    v2_path = home / ".zcode" / "v2" / "config.json"
    if not v2_path.exists():
        return False
    try:
        v2cfg = json.loads(v2_path.read_text(encoding="utf-8"))
        picked = _zcode_pick_provider(v2cfg)
        if not picked:
            return False
        pid, model_id = picked
        cfg = {
            "provider": {pid: v2cfg["provider"][pid]},
            "model": {"main": f"{pid}/{model_id}"},
        }
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except (OSError, ValueError, KeyError):
        return False


def _zcode_render_task(messages: list) -> str:
    """Собрать TASK.md из сообщений chat-completions формата."""
    parts = []
    for m in messages:
        role = (m.get("role") or "user").upper()
        content = m.get("content", "")
        if isinstance(content, list):  # мультимодальные блоки — берём текст
            content = "\n".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
        parts.append(f"### {role}\n{content}")
    return "\n\n".join(parts)


def _zcode_run(args: list, timeout: int, task_dir: str | None = None) -> str:
    """Запустить zcode CLI, вернуть финальный текст ответа."""
    node = _zcode_node_path()
    cli = _zcode_cli_path()
    if not node or not cli:
        raise RuntimeError("zcode: node или zcode.cjs не найдены")
    cmd = [node, cli, *args]
    cap = max(timeout, ZCODE_MIN_TIMEOUT_S) + ZCODE_BOOT_GRACE_S
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=cap,
            cwd=task_dir or tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"zcode: таймаут {cap}s")
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError(f"zcode: exit {proc.returncode}: {err or 'пустой ответ'}")
    return out


def _chat_zcode_once(model_id: str, messages: list, timeout: int) -> str:
    """Текстовая генерация через ZCode CLI: промпт в TASK.md, ответ — stdout."""
    task_dir = tempfile.mkdtemp(prefix="zcode-task-")
    try:
        (Path(task_dir) / "TASK.md").write_text(
            _zcode_render_task(messages), encoding="utf-8")
        return _zcode_run(
            ["--prompt", ZCODE_TASK_PROMPT, "--cwd", task_dir,
             "--disallowed-tools", ZCODE_DENY_TOOLS],
            timeout, task_dir)
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)


def _resolve_chain(role: str, model: str | None, provider: str | None) -> list:
    """Цепочка (provider_name, model_id, cfg) из явного model или ROUTING/env.
    provider — необязательный фильтр предпочтительного провайдера
    (None/"auto" = вся цепочка)."""
    chain = []
    for slug in ([model] if model else routing_models(role)):
        _check_model_slug(slug)
        name, _, model_id = slug.partition("/")
        if not model_id:
            raise ValueError(f"model slug без провайдера (нужен 'provider/model'): {slug!r}")
        cfg = PROVIDERS.get(name)
        if cfg is None:
            raise ValueError(f"неизвестный провайдер в model slug: {slug!r}")
        if provider and provider != "auto" and name != provider:
            continue
        chain.append((name, model_id, cfg))
    return chain


def load(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def build_system_prompt(mode: str = "generate") -> str:
    template = load("spike/system-prompt.md")
    template = template.split("---", 1)[-1]  # убрать шапку-описание
    return (
        template.replace("{{SCHEMA}}", load("schema/design-ir.schema.json"))
        .replace("{{BLOCKS}}", load("app/prompts/BLOCKS.md"))
        # craft-правила нужны только свободной генерации; в edit они шум
        .replace("{{DESIGN}}", load("app/prompts/DESIGN.md") if mode == "generate" else "")
        .replace("{{BRIEF}}", "")
        .replace("{{STYLE_HINT}}", "")
        .replace("{{MODE}}", mode)
        .strip()
    )


def _post_json(url: str, payload: dict, key: str | None, timeout: int,
               extra_headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _grok_conv_headers(request: "ChatRequest") -> dict:
    """x-grok-conv-id: стабильный id конверсации для cache affinity.
    Безопасно: это request_id конверта (уже проверенный [A-Za-z0-9-]{1,64}).
    Никакого молчаливого truncate/coerce — невалидный id отвергается в validate()."""
    conv = request.request_id
    if not isinstance(conv, str) or not _REQUEST_ID_RE.fullmatch(conv):
        raise ValueError("request_id: must match [A-Za-z0-9-]{1,64} (no silent truncation)")
    return {"x-grok-conv-id": conv}


def _post_openai_payload(cfg, key, provider, model_id, request: ChatRequest,
                         timeout: int) -> tuple[dict, list[dict]]:
    """POST wire-payload; HTTP 400 с известными value-несовместимостями
    провайдера ретраится (до 3 снятий) с ЯВНОЙ записью каждого снятого поля."""
    payload, dropped = request.to_openai_payload(provider, model_id, json_mode=True)
    extra = _grok_conv_headers(request) if provider == "grok" else None

    def _post():
        # extra_headers передаём только когда они есть: тестовые double'ы
        # _post_json принимают ровно 4 аргумента.
        if extra:
            return _post_json(_provider_url(cfg), payload, key, timeout, extra)
        return _post_json(_provider_url(cfg), payload, key, timeout)

    for _ in range(3):
        try:
            return _post(), dropped
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            body = e.read()[:500].decode("utf-8", "replace")
            removed = False
            for field in ("response_format", "temperature", "top_p", "stop", "seed"):
                if field in payload and field in body:
                    del payload[field]
                    dropped.append({"field": field,
                                    "reason": f"провайдер отверг параметр (HTTP 400): {body[:120]}"})
                    removed = True
                    break
            if not removed:
                raise
    return _post(), dropped


def chat_envelope(request: ChatRequest, role: str = "mechanics") -> dict:
    """Полный контрактный вызов: возвращает content + transport-блок
    {provider, model, request_id, dropped}. Ничего не теряется молча."""
    request.check()
    t = request.timeout_s or TIMEOUT

    chain = _resolve_chain(role, request.model, request.provider)
    skipped: list[str] = []
    last_error: str | None = None
    for name, model_id, cfg in chain:
        try:
            request.assert_supported(name)
        except ValueError as error:
            skipped.append(f"{name}/{model_id}: {error}")
            continue
        if name == "zcode":
            if not zcode_available():
                skipped.append("zcode: транспорт отключён — задайте ZCODE_CLI явно (авто-discovery удалён) или нет login Z.AI")
                continue
            adapted, dropped = request.adapt_for_provider(name)
            try:
                content = _chat_zcode_once(model_id, adapted.messages, t)
                return {"content": content, "transport": {
                    "provider": name, "model": model_id,
                    "request_id": request.request_id, "dropped": dropped}}
            except Exception as e:  # noqa: BLE001 — цепочка пробует следующую запись
                last_error = f"zcode/{model_id}: {e}"
                continue
        key = os.environ.get(cfg["env"], "")
        if not key:
            skipped.append(f"{name}/{model_id}: нет {cfg['env']}")
            continue  # аккаунт провайдера не подключён — следующая запись
        try:
            data, dropped = _post_openai_payload(cfg, key, name, model_id, request, t)
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            if not content.strip():
                raise RuntimeError(
                    f"пустой content (reasoning: {str(msg.get('reasoning_content'))[:100]!r})")
            return {"content": content, "transport": {
                "provider": name, "model": model_id,
                "request_id": request.request_id, "dropped": dropped}}
        except urllib.error.HTTPError as e:
            last_error = f"{name}/{model_id} HTTP {e.code}: {e.read()[:300]!r}"
            if e.code in (404, 429, 500, 502, 503) and (name, model_id, cfg) != chain[-1]:
                continue  # fallback на следующую модель цепочки
            raise RuntimeError(last_error)
    detail = f" Последняя ошибка: {last_error}." if last_error else ""
    if skipped:
        detail += " Пропущено: " + "; ".join(skipped)
    raise RuntimeError(f"все модели цепочки недоступны.{detail}")


def chat(provider: str | None, messages: list, temperature: float, timeout: int | None = None,
         role: str = "mechanics", model: str | None = None) -> str:
    """Прямой вызов OpenAI/Kimi/GLM/Grok/Zcode через типизированный envelope
    (обёртка над chat_envelope для legacy-вызовов). role выбирает цепочку
    ROUTING, model — явный override, provider — необязательный фильтр."""
    if model is not None:
        _check_model_slug(model)
    request = ChatRequest(
        messages=messages, provider=provider, model=model,
        temperature=temperature, timeout_s=timeout,
    )
    return chat_envelope(request, role=role)["content"]


def chat_vision(provider: str | None, image_data_url: str, text_prompt: str,
                system_prompt: str = "", temperature: float = 0.2,
                timeout: int | None = None, role: str = "vision") -> str:
    """Vision-вызов напрямую (OpenAI/Kimi) с fallback-моделями роли.
    provider — необязательный фильтр (None/"auto" = вся цепочка)."""
    t = timeout or TIMEOUT

    chain = _resolve_chain(role, None, provider)
    skipped = []
    last_error = None
    for name, model_id, cfg in chain:
        key = os.environ.get(cfg["env"], "")
        if not key:
            skipped.append(f"{name}/{model_id}: нет {cfg['env']}")
            continue
        try:
            content = _call_openai_vision(cfg, key, model_id, image_data_url,
                                          text_prompt, system_prompt, temperature, t)
            if content and content.strip():
                return content
        except urllib.error.HTTPError as e:
            err_body = e.read()[:300]
            last_error = f"{name}/{model_id} HTTP {e.code}: {err_body!r}"
            if e.code in (404, 400, 429, 403):
                continue
            raise RuntimeError(f"vision {last_error}")
        except Exception as e:
            last_error = str(e)
            continue

    detail = f" Последняя ошибка: {last_error}." if last_error else ""
    if skipped:
        detail += " Пропущено без ключа: " + "; ".join(skipped)
    raise RuntimeError(f"vision: все модели недоступны.{detail}")


def _call_openai_vision(cfg, key, model, image_data_url, text_prompt, system_prompt,
                        temperature, timeout):
    """Vision-вызов в OpenAI-совместимом формате (OpenAI и Kimi API)."""
    user_content = [
        {"type": "text", "text": text_prompt},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": cfg.get("fixed_temperature", temperature),
    }
    data = None
    for _ in range(2):  # HTTP 400 → kimi/k3 не принимает temperature ≠ 1 — повтор без него
        try:
            data = _post_json(_provider_url(cfg), payload, key, timeout)
            break
        except urllib.error.HTTPError as e:
            if e.code == 400 and "temperature" in payload:
                payload.pop("temperature")
                continue
            raise
    return data["choices"][0]["message"].get("content") or ""


def extract_json(text: str) -> str:
    """Вытащить JSON даже если модель обернула в markdown."""
    # 1. Markdown code block
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if m:
        candidate = m.group(1).strip()
        try:
            json.JSONDecoder().raw_decode(candidate)
            return candidate
        except ValueError:
            pass

    # 2. First valid JSON object anywhere in the text
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                obj, end = decoder.raw_decode(text, i)
                if isinstance(obj, dict):
                    return text[i:end]
            except ValueError:
                continue
    return text


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=[*PROVIDERS, "auto"], default="auto",
                   help="Фильтр провайдера; auto (по умолчанию) — вся цепочка ROUTING")
    p.add_argument("--brief", help="Текст брифа")
    p.add_argument("--brief-file", help="Файл с брифом")
    p.add_argument("--repair", metavar="JSON_FILE", help="Режим repair: починить невалидный IR")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--out", default=None, help="Куда сохранить (по умолчанию results/<provider>.json)")
    args = p.parse_args()

    system = build_system_prompt()

    if args.repair:
        broken = Path(args.repair).read_text(encoding="utf-8")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content":
             "The following JSON failed validation against the schema. "
             "Fix it minimally and return the corrected JSON only:\n\n" + broken},
        ]
    else:
        brief = args.brief or (Path(args.brief_file).read_text(encoding="utf-8") if args.brief_file else None)
        if not brief:
            sys.exit("Нужен --brief или --brief-file")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"## Brief\n{brief}"},
        ]

    raw = chat(args.provider, messages, args.temperature)
    out = Path(args.out) if args.out else ROOT / "results" / f"{args.provider}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(extract_json(raw), encoding="utf-8")
    print(f"Сохранено: {out}")
    print("Проверка: python spike/validate.py", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
