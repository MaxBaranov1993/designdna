"""OpenAI Responses transport for DesignDNA (Sol and Astra).

The desktop and Python fallback paths share one contract: OpenAI Responses,
``gpt-5.6-sol`` or ``gpt-6-astra``, and ``medium|high|max`` reasoning effort.
Legacy provider/model selections are migrated and surfaced in ``dropped``.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
import urllib.request

import cli_llm
import uuid
from collections.abc import Callable
from pathlib import Path

import cancel_token


ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent)
TIMEOUT = int(os.environ.get("LLM_TIMEOUT_S", "120"))
SOL_MODEL = "gpt-5.6-sol"
ASTRA_MODEL = "gpt-6-astra"
OPENAI_MODELS = (SOL_MODEL, ASTRA_MODEL)
SOL_EFFORTS = ("medium", "high", "max")
OPENAI_URL = "https://api.openai.com/v1/responses"
PROVIDERS = {"openai": {"url": OPENAI_URL, "env": "OPENAI_API_KEY"}}

_ROLES = (
    "prompt_enhancer", "planner", "motion_director", "timeline_director", "generator", "reskin",
    "repair", "style_analysis", "vision", "vision_fast", "vision_pixel_qa",
    "judge", "quality_judge", "quality_repair", "edit", "derive", "optimizer",
    "tokens", "components", "clone", "blockparse", "source_semantics",
    "source_vision_audit", "reproduce", "a11y", "docs", "mechanics", "taste",
    "art-direction", "graphics",
)
ROUTING = {role: [f"openai/{SOL_MODEL}"] for role in _ROLES}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def load_dotenv(path: Path | None = None) -> int:
    """Load previously unset KEY=VALUE pairs from the repository .env."""
    target = path or (ROOT / ".env")
    if not target.exists():
        return 0
    loaded = 0
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
            loaded += 1
    return loaded


load_dotenv()


def routing_models(role: str) -> list[str]:
    """Return the default route for calls without an explicit model selection."""
    return list(ROUTING.get(role, ROUTING["mechanics"]))


def openai_model(provider: str | None, model: str | None = None) -> str:
    """Resolve a UI choice without creating another credential or endpoint."""
    if provider == "astra":
        return ASTRA_MODEL
    bare = str(model or "").removeprefix("openai/")
    return bare if bare in OPENAI_MODELS else SOL_MODEL


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    return "\n".join(str(part.get("text", "")) for part in value if isinstance(part, dict) and part.get("type") == "text")


def _responses_content(content, role: str):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            parts.append({"type": "output_text" if role == "assistant" else "input_text", "text": str(part.get("text", ""))})
        elif part.get("type") == "image_url" and role == "user":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if url:
                item = {"type": "input_image", "image_url": str(url)}
                if isinstance(image, dict) and image.get("detail"):
                    item["detail"] = image["detail"]
                parts.append(item)
    return parts


def _responses_input(messages: list[dict]) -> tuple[str, list[dict]]:
    instructions = []
    items = []
    for message in messages:
        role = str(message.get("role") or "")
        if role == "system":
            text = _text(message.get("content"))
            if text:
                instructions.append(text)
            continue
        if role == "tool":
            call_id = message.get("tool_call_id") or message.get("toolCallId")
            items.append({"type": "function_call_output", "call_id": str(call_id or ""), "output": _text(message.get("content"))})
            continue
        content = _responses_content(message.get("content"), role)
        if content:
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls") or message.get("toolCalls") or []:
            function = call.get("function") or call
            arguments = function.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            items.append({
                "type": "function_call",
                "call_id": str(call.get("id") or ""),
                "name": str(function.get("name") or ""),
                "arguments": arguments,
            })
    return "\n\n".join(instructions), items


def _responses_tools(tools: list[dict] | None) -> list[dict]:
    result = []
    for tool in tools or []:
        function = tool.get("function") or tool
        result.append({
            "type": "function",
            "name": str(function.get("name") or ""),
            "description": str(function.get("description") or ""),
            "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            "strict": False,
        })
    return result


@dataclasses.dataclass
class ChatRequest:
    messages: list
    provider: str | None = None
    model: str | None = None
    system: str = ""
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    reasoning_budget_tokens: int | None = None
    response_format: str | None = None
    response_json_schema: dict | None = None
    stop: list[str] | str | None = None
    seed: int | None = None
    tools: list | None = None
    tool_choice: str | dict | None = None
    parallel_tool_calls: bool | None = None
    metadata: dict | None = None
    provider_options: dict | None = None
    timeout_s: int | None = None
    request_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    stream: bool = False

    def validate(self) -> list[str]:
        issues = []
        if not isinstance(self.messages, list) or not self.messages:
            issues.append("messages: expected a non-empty list")
        elif any(not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"} for message in self.messages):
            issues.append("messages: invalid role or message")
        allowed_efforts = cli_llm._EFFORTS if self.provider == "codex" else SOL_EFFORTS
        if self.reasoning_effort is not None and self.reasoning_effort not in allowed_efforts:
            issues.append("reasoning_effort: expected medium|high|max")
        if self.timeout_s is not None and (not isinstance(self.timeout_s, int) or not 1 <= self.timeout_s <= 600):
            issues.append("timeout_s: expected an integer in 1..600")
        if not isinstance(self.request_id, str) or not _REQUEST_ID_RE.fullmatch(self.request_id):
            issues.append("request_id: expected [A-Za-z0-9-]{1,64}")
        if not isinstance(self.stream, bool):
            issues.append("stream: expected a boolean")
        if self.max_output_tokens is not None and (not isinstance(self.max_output_tokens, int) or self.max_output_tokens <= 0):
            issues.append("max_output_tokens: expected a positive integer")
        if self.provider_options:
            unknown = sorted(set(self.provider_options) - {"openai"})
            if unknown:
                issues.append(f"provider_options: retired providers are not supported: {unknown}")
        return issues

    def check(self) -> "ChatRequest":
        issues = self.validate()
        if issues:
            raise ValueError("invalid ChatRequest: " + "; ".join(issues))
        return self

    def assert_supported(self, provider: str) -> None:
        if provider != "openai":
            raise ValueError(f"retired provider is not supported: {provider}")

    def to_responses_payload(self) -> tuple[dict, list[dict]]:
        self.check()
        instructions, items = _responses_input(self.messages)
        if self.system:
            instructions = f"{self.system}\n\n{instructions}".strip()
        effort = self.reasoning_effort or "medium"
        payload = {
            "model": openai_model(self.provider, self.model),
            "input": items,
            "reasoning": {"effort": effort},
            "store": False,
        }
        if self.stream:
            payload["stream"] = True
        if instructions:
            payload["instructions"] = instructions
        if self.max_output_tokens is not None:
            payload["max_output_tokens"] = self.max_output_tokens
        wire_tools = _responses_tools(self.tools)
        if wire_tools:
            payload["tools"] = wire_tools
        if self.tool_choice is not None:
            payload["tool_choice"] = ({"type": "function", "name": self.tool_choice.get("name")} if isinstance(self.tool_choice, dict) else self.tool_choice)
        if self.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = self.parallel_tool_calls
        if self.metadata:
            payload["metadata"] = self.metadata
        if self.response_format == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
        elif self.response_format == "json_schema" and self.response_json_schema:
            payload["text"] = {"format": {"type": "json_schema", **self.response_json_schema}}

        dropped = []
        if self.provider not in (None, "", "auto", "openai", "astra"):
            dropped.append({"field": "provider", "reason": f"{self.provider} migrated to openai"})
        if self.model and str(self.model).removeprefix("openai/") != payload["model"]:
            dropped.append({"field": "model", "reason": f"{self.model} replaced by {payload['model']}"})
        for field, value in (
            ("temperature", self.temperature), ("topP", self.top_p),
            ("reasoning.budgetTokens", self.reasoning_budget_tokens),
            ("stop", self.stop), ("seed", self.seed),
        ):
            if value is not None:
                dropped.append({"field": field, "reason": "not part of the OpenAI Responses contract"})
        return payload, dropped

    def to_openai_payload(self, provider: str = "openai", model: str = SOL_MODEL, json_mode: bool = False):
        """Compatibility alias retained for internal callers during migration."""
        self.assert_supported(provider)
        return self.to_responses_payload()


def _post_json(url: str, payload: dict, key: str | None, timeout: int, extra_headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _post_stream(
    url: str,
    payload: dict,
    key: str | None,
    timeout: int,
    on_delta: Callable[[str], None] | None = None,
    extra_headers: dict | None = None,
) -> dict:
    """Consume a Responses SSE stream and return its completed response object."""
    body = json.dumps({**payload, "stream": True}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=body, headers=headers)
    completed: dict | None = None
    event_name = ""
    data_lines: list[str] = []

    def dispatch() -> None:
        nonlocal completed, event_name, data_lines
        if not data_lines:
            event_name = ""
            return
        raw_data = "\n".join(data_lines)
        data_lines = []
        if raw_data == "[DONE]":
            event_name = ""
            return
        event = json.loads(raw_data)
        event_type = str(event.get("type") or event_name)
        event_name = ""
        cancel_token.check()
        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta and on_delta:
                on_delta(delta)
        elif event_type == "response.completed":
            response = event.get("response")
            if isinstance(response, dict):
                completed = response
        elif event_type in {"error", "response.failed", "response.incomplete"}:
            error = event.get("error")
            if not isinstance(error, dict):
                response = event.get("response")
                error = response.get("error") if isinstance(response, dict) else None
            message = error.get("message") if isinstance(error, dict) else event.get("message")
            raise RuntimeError(str(message or f"OpenAI stream failed: {event_type}"))

    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                dispatch()
            elif line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        dispatch()
    if completed is None:
        raise RuntimeError("OpenAI stream ended before response.completed")
    return completed


def _extract_response(data: dict) -> tuple[str, list[dict] | None]:
    if data.get("status") and data["status"] != "completed":
        reason = (data.get("error") or {}).get("message") or (data.get("incomplete_details") or {}).get("reason") or data["status"]
        raise RuntimeError(f"OpenAI response is not completed: {reason}")
    texts = []
    tool_calls = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    texts.append(str(part["text"]))
        elif item.get("type") == "function_call":
            arguments = item.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            json.loads(arguments)
            tool_calls.append({
                "id": str(item.get("call_id") or item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "arguments": arguments,
            })
    content = "\n".join(texts) or str(data.get("output_text") or "")
    if not content.strip() and not tool_calls:
        raise RuntimeError("OpenAI returned an empty response")
    return content, tool_calls or None


def chat_envelope(
    request: ChatRequest,
    role: str = "mechanics",
    on_delta: Callable[[str], None] | None = None,
) -> dict:
    """Execute the selected AI route and return transport diagnostics."""
    # Кооперативная отмена (cancel_token): отменённый запрос не начинает
    # следующий LLM-вызов — покрывает генератор, quality-pass и импорт разом.
    cancel_token.check()
    payload, dropped = request.to_responses_payload()
    key = os.environ.get("OPENAI_API_KEY", "")
    # Консольный транспорт (аккаунты Codex / Claude Code, без API-ключей):
    # явный provider codex|claude — всегда через CLI; без ключа OpenAI — через
    # первый доступный CLI. Стриминга у CLI нет: on_delta получит ответ целиком.
    cli_provider = request.provider if request.provider in ("codex", "claude") else None
    if not cli_provider and not key and request.provider not in ("openai", "astra") and not request.model:
        cli_provider = cli_llm.default_provider()
    if cli_provider:
        messages = list(request.messages or [])
        if request.system:
            messages = [{"role": "system", "content": request.system}, *messages]
        content = cli_llm.chat(
            cli_provider, messages,
            model=(request.model or ("opus" if request.provider == "claude" else None)) if request.provider in ("codex", "claude") else None,
            effort=request.reasoning_effort,
            # HTTP-таймаут (120 с) для CLI слишком короток: берём больший из двух
            timeout=max(request.timeout_s or TIMEOUT, cli_llm.DEFAULT_TIMEOUT),
        )
        if on_delta and content:
            on_delta(content)
        return {
            "content": content,
            "tool_calls": None,
            "transport": {
                "provider": cli_provider, "model": request.model or "cli-default",
                "request_id": request.request_id, "dropped": [item for item in dropped if item["field"] not in ("provider", "model")], "streamed": False,
            },
        }
    if not key:
        if request.provider in ("openai", "astra") or request.model:
            raise RuntimeError(f"{payload['model']}: добавьте OpenAI API key в Agents → Connections (OPENAI_API_KEY).")
        raise RuntimeError("Нет подключённого AI-аккаунта: установите Codex CLI или Claude Code и войдите, либо задайте OPENAI_API_KEY")
    streamed = bool(request.stream or on_delta)
    post = _post_stream if streamed else _post_json
    if streamed:
        data = post(
            os.environ.get("OPENAI_RESPONSES_URL", OPENAI_URL), payload, key,
            request.timeout_s or TIMEOUT, on_delta=on_delta,
        )
    else:
        data = post(
            os.environ.get("OPENAI_RESPONSES_URL", OPENAI_URL), payload, key,
            request.timeout_s or TIMEOUT,
        )
    content, tool_calls = _extract_response(data)
    return {
        "content": content,
        "tool_calls": tool_calls,
        "transport": {
            "provider": "openai",
            "model": payload["model"],
            "request_id": request.request_id,
            "dropped": dropped,
            "streamed": streamed,
        },
    }


def chat(provider: str | None, messages: list, temperature: float, timeout: int | None = None,
         role: str = "mechanics", model: str | None = None,
         reasoning_effort: str | None = None,
         on_delta: Callable[[str], None] | None = None) -> str:
    request = ChatRequest(
        messages=messages,
        provider=provider,
        model=model,
        temperature=temperature,
        timeout_s=timeout,
        reasoning_effort=reasoning_effort,
        stream=on_delta is not None,
    )
    return chat_envelope(request, role=role, on_delta=on_delta)["content"]


def chat_vision(provider: str | None, image_data_url: str | list[str], text_prompt: str,
                system_prompt: str = "", temperature: float = 0.2,
                timeout: int | None = None, role: str = "vision",
                reasoning_effort: str | None = None) -> str:
    # Несколько изображений (первый экран 1:1 + страница по частям): одна
    # высокая картинка при даунскейле у vision-модели превращается в «мобильный
    # макет с нечитаемым кеглем».
    images = [image_data_url] if isinstance(image_data_url, str) else list(image_data_url)
    request = ChatRequest(
        provider=provider,
        system=system_prompt,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": text_prompt},
            *({"type": "image_url", "image_url": {"url": url}} for url in images),
        ]}],
        temperature=temperature,
        timeout_s=timeout,
        reasoning_effort=reasoning_effort,
    )
    return chat_envelope(request, role=role)["content"]


# Кэш промпт-файлов и собранных системных промптов: сервер многопоточный,
# файлы читаются на каждый LLM-вызов, поэтому ключ — (path, mtime_ns, size).
_PROMPT_FILES = (
    "app/prompts/SYSTEM.md", "schema/design-ir.schema.json",
    "app/prompts/BLOCKS.md", "app/prompts/DESIGN.md",
)
_PROMPT_LOCK = threading.Lock()
_FILE_CACHE: dict[str, tuple[tuple[int, int], str]] = {}
_PROMPT_CACHE: dict[tuple[str, tuple[tuple[int, int], ...]], str] = {}


def _file_stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def invalidate_prompt_cache() -> None:
    """Сбросить оба кэша (для тестов и горячей смены ROOT)."""
    with _PROMPT_LOCK:
        _FILE_CACHE.clear()
        _PROMPT_CACHE.clear()


def load(name: str) -> str:
    path = ROOT / name
    stamp = _file_stamp(path)
    key = str(path)
    with _PROMPT_LOCK:
        cached = _FILE_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    text = path.read_text(encoding="utf-8")
    with _PROMPT_LOCK:
        _FILE_CACHE[key] = (stamp, text)
    return text


# Few-shot эталоны: 2–3 подбираются по типу продукта из брифа. Каждый режется до
# ~6 КБ — целиком страница занимает десятки килобайт и вытесняет саму задачу.
EXEMPLARS_DIR = "app/exemplars"
EXEMPLAR_BUDGET = 6144
_EXEMPLAR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "saas-landing": (
        "saas", "b2b", "сервис", "платформ", "подписк", "dashboard", "дашборд", "crm",
        "приложен", "лендинг", "landing", "software", "инструмент", "стартап", "api",
        "аналитик", "автоматиз",
    ),
    "marketplace": (
        "marketplace", "маркетплейс", "магазин", "shop", "commerce", "каталог", "товар",
        "объявлен", "доска", "продаж", "аукцион", "аренд", "витрин", "заказ", "покупател",
    ),
    "restaurant": (
        "restaurant", "ресторан", "кафе", "cafe", "бар", "food", "еда", "кухн", "меню",
        "пекарн", "bakery", "coffee", "кофе", "бистро", "винн", "гост", "hospitality",
    ),
    "ecommerce": ("ecommerce", "e-commerce", "online store", "store", "retail"),
    "education": ("education", "school", "course", "learning", "university", "edtech"),
    "fintech": ("fintech", "finance", "bank", "payments", "cash flow", "accounting"),
    "healthcare": ("healthcare", "health", "clinic", "medical", "wellness", "patient"),
    "portfolio": ("portfolio", "agency", "studio", "designer", "photographer", "architect"),
    "real-estate": ("realestate", "real-estate", "real estate", "property", "housing"),
    "travel": ("travel", "trip", "hotel", "tour", "booking", "destination"),
}
# Ни одно слово не совпало — начинаем с двух самых разных по композиции эталонов.
_EXEMPLAR_FALLBACK = ("saas-landing", "restaurant")
_EXEMPLAR_NEIGHBORS: dict[str, tuple[str, ...]] = {
    "saas-landing": ("fintech", "education"),
    "marketplace": ("ecommerce", "real-estate"),
    "restaurant": ("travel", "ecommerce"),
    "ecommerce": ("marketplace", "portfolio"),
    "education": ("saas-landing", "healthcare"),
    "fintech": ("saas-landing", "healthcare"),
    "healthcare": ("education", "saas-landing"),
    "portfolio": ("ecommerce", "travel"),
    "real-estate": ("marketplace", "travel"),
    "travel": ("restaurant", "real-estate"),
}


def exemplar_names(product_type: str, limit: int = 3) -> list[str]:
    """Имена ближайших эталонов по типу продукта (без чтения файлов)."""
    text = str(product_type or "").casefold()
    scored = [
        (sum(1 for word in words if word in text), name)
        for name, words in _EXEMPLAR_KEYWORDS.items()
    ]
    matched = [name for score, name in sorted(scored, key=lambda s: (-s[0], s[1])) if score]
    selected = list(matched or _EXEMPLAR_FALLBACK)
    if selected:
        selected.extend(name for name in _EXEMPLAR_NEIGHBORS.get(selected[0], ()) if name not in selected)
    selected.extend(name for name in _EXEMPLAR_FALLBACK if name not in selected)
    return selected[:max(0, limit)]


def _compact(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def fit_exemplar(document: dict, budget: int = EXEMPLAR_BUDGET) -> tuple[str, int]:
    """Ужать эталон под бюджет, отбрасывая секции с конца -> (json, сколько убрано).

    Резать строку по символам нельзя: модель получила бы оборванный JSON и училась
    бы на нём. Хвост страницы (footer, cta) для few-shot наименее ценен, поэтому
    отрезаем секции целиком, сохраняя валидный документ и начало композиции.
    """
    body = _compact(document)
    if len(body) <= budget or not isinstance(document.get("tree"), list):
        return body, 0
    tree = list(document["tree"])
    dropped = 0
    while len(tree) > 1 and len(body) > budget:
        tree.pop()
        dropped += 1
        body = _compact({**document, "tree": tree})
    return body, dropped


def load_exemplars(product_type: str, limit: int = 3) -> str:
    """Few-shot блок для промпта: 2–3 эталонных IR, каждый ужат до EXEMPLAR_BUDGET.

    Отсутствующий или битый файл эталона молча пропускается: few-shot — это
    усилитель качества, а не обязательная часть контракта генерации.
    """
    chunks: list[str] = []
    for name in exemplar_names(product_type, limit):
        try:
            document = json.loads(load(f"{EXEMPLARS_DIR}/{name}.json"))
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        body, dropped = fit_exemplar(document)
        meta = document.get("meta")
        direction = meta.get("direction") if isinstance(meta, dict) else None
        label = name
        if isinstance(direction, dict) and direction.get("name"):
            label += f" · направление «{direction['name']}»"
        note = f"\n(последние {dropped} секций опущены ради размера промпта)" if dropped else ""
        chunks.append(f"### exemplar: {label}\n```json\n{body}\n```{note}")
    return "\n\n".join(chunks)


def build_system_prompt(
    mode: str = "generate",
    *,
    design_brief: dict | str = "",
    exemplars: str = "",
    policy: str = "",
) -> str:
    """Собрать system-промпт генератора.

    `design_brief` (DesignBrief со стадии арт-дирекции) и `exemplars` по умолчанию
    пустые — вызов без них полностью совместим со старой сигнатурой и кэшируется
    по (mode, сигнатуры промпт-файлов). С непустым контекстом промпт собирается
    каждый раз: ключом был бы весь бриф.
    """
    if isinstance(design_brief, dict):
        design_brief = json.dumps(design_brief, ensure_ascii=False, indent=2)
    signature = tuple(_file_stamp(ROOT / name) for name in _PROMPT_FILES)
    key = (mode, signature)
    cacheable = not design_brief and not exemplars and not policy
    if cacheable:
        with _PROMPT_LOCK:
            cached = _PROMPT_CACHE.get(key)
        if cached is not None:
            return cached
    template = load("app/prompts/SYSTEM.md")
    prompt = (
        template.replace("{{SCHEMA}}", load("schema/design-ir.schema.json"))
        .replace("{{BLOCKS}}", load("app/prompts/BLOCKS.md"))
        .replace("{{DESIGN}}", load("app/prompts/DESIGN.md") if mode == "generate" else "")
        .replace("{{DESIGN_BRIEF}}", design_brief or "")
        .replace("{{POLICY}}", policy)
        .replace("{{EXEMPLARS}}", exemplars or "")
        .replace("{{BRIEF}}", "")
        .replace("{{STYLE_HINT}}", "")
        .replace("{{MODE}}", mode)
        .strip()
    )
    if cacheable:
        with _PROMPT_LOCK:
            # Старые сигнатуры больше не нужны — держим только актуальный вариант mode.
            for stale in [k for k in _PROMPT_CACHE if k[0] == mode and k != key]:
                del _PROMPT_CACHE[stale]
            _PROMPT_CACHE[key] = prompt
    return prompt


def extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if fenced:
        candidate = fenced.group(1).strip()
        try:
            json.JSONDecoder().raw_decode(candidate)
            return candidate
        except ValueError:
            pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character in "{[":
            try:
                _, end = decoder.raw_decode(text, index)
                return text[index:end]
            except ValueError:
                continue
    return text.strip()


def main() -> int:
    print(json.dumps({"provider": "openai", "model": SOL_MODEL, "efforts": list(SOL_EFFORTS)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
