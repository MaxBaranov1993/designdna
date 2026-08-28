"""Sol-only LLM transport for DesignDNA.

The desktop and Python fallback paths share one contract: OpenAI Responses,
fixed ``gpt-5.6-sol``, and explicit ``medium|high|max`` reasoning effort.
Legacy provider/model selections are migrated and surfaced in ``dropped``.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent)
TIMEOUT = int(os.environ.get("LLM_TIMEOUT_S", "120"))
SOL_MODEL = "gpt-5.6-sol"
SOL_EFFORTS = ("medium", "high", "max")
OPENAI_URL = "https://api.openai.com/v1/responses"
PROVIDERS = {"openai": {"url": OPENAI_URL, "env": "OPENAI_API_KEY"}}

_ROLES = (
    "prompt_enhancer", "planner", "motion_director", "timeline_director", "generator", "reskin",
    "repair", "style_analysis", "vision", "vision_fast", "vision_pixel_qa",
    "judge", "quality_judge", "quality_repair", "edit", "derive", "optimizer",
    "tokens", "components", "clone", "blockparse", "source_semantics",
    "source_vision_audit", "reproduce", "a11y", "docs", "mechanics", "taste",
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
    """Return the immutable Sol route; env overrides cannot restore providers."""
    return list(ROUTING.get(role, ROUTING["mechanics"]))


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
        if self.reasoning_effort is not None and self.reasoning_effort not in SOL_EFFORTS:
            issues.append("reasoning_effort: expected medium|high|max")
        if self.timeout_s is not None and (not isinstance(self.timeout_s, int) or not 1 <= self.timeout_s <= 600):
            issues.append("timeout_s: expected an integer in 1..600")
        if not isinstance(self.request_id, str) or not _REQUEST_ID_RE.fullmatch(self.request_id):
            issues.append("request_id: expected [A-Za-z0-9-]{1,64}")
        if self.stream:
            issues.append("stream: streaming is not supported by this transport")
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
            "model": SOL_MODEL,
            "input": items,
            "reasoning": {"effort": effort},
            "store": False,
        }
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
        if self.provider not in (None, "", "auto", "openai"):
            dropped.append({"field": "provider", "reason": f"{self.provider} migrated to openai"})
        if self.model not in (None, "", SOL_MODEL, f"openai/{SOL_MODEL}"):
            dropped.append({"field": "model", "reason": f"{self.model} replaced by {SOL_MODEL}"})
        for field, value in (
            ("temperature", self.temperature), ("topP", self.top_p),
            ("reasoning.budgetTokens", self.reasoning_budget_tokens),
            ("stop", self.stop), ("seed", self.seed),
        ):
            if value is not None:
                dropped.append({"field": field, "reason": "not part of the fixed Sol Responses contract"})
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


def _extract_response(data: dict) -> tuple[str, list[dict] | None]:
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


def chat_envelope(request: ChatRequest, role: str = "mechanics") -> dict:
    """Execute one fixed Sol Responses request and return transport diagnostics."""
    payload, dropped = request.to_responses_payload()
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OpenAI is not connected: set OPENAI_API_KEY")
    data = _post_json(os.environ.get("OPENAI_RESPONSES_URL", OPENAI_URL), payload, key, request.timeout_s or TIMEOUT)
    content, tool_calls = _extract_response(data)
    return {
        "content": content,
        "tool_calls": tool_calls,
        "transport": {
            "provider": "openai",
            "model": SOL_MODEL,
            "request_id": request.request_id,
            "dropped": dropped,
        },
    }


def chat(provider: str | None, messages: list, temperature: float, timeout: int | None = None,
         role: str = "mechanics", model: str | None = None,
         reasoning_effort: str | None = None) -> str:
    request = ChatRequest(
        messages=messages,
        provider=provider,
        model=model,
        temperature=temperature,
        timeout_s=timeout,
        reasoning_effort=reasoning_effort,
    )
    return chat_envelope(request, role=role)["content"]


def chat_vision(provider: str | None, image_data_url: str, text_prompt: str,
                system_prompt: str = "", temperature: float = 0.2,
                timeout: int | None = None, role: str = "vision") -> str:
    request = ChatRequest(
        provider=provider,
        system=system_prompt,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]}],
        temperature=temperature,
        timeout_s=timeout,
    )
    return chat_envelope(request, role=role)["content"]


def load(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def build_system_prompt(mode: str = "generate") -> str:
    template = load("spike/system-prompt.md").split("---", 1)[-1]
    return (
        template.replace("{{SCHEMA}}", load("schema/design-ir.schema.json"))
        .replace("{{BLOCKS}}", load("app/prompts/BLOCKS.md"))
        .replace("{{DESIGN}}", load("app/prompts/DESIGN.md") if mode == "generate" else "")
        .replace("{{BRIEF}}", "")
        .replace("{{STYLE_HINT}}", "")
        .replace("{{MODE}}", mode)
        .strip()
    )


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
