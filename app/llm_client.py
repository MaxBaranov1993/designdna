"""Production LLM client for the user-owned GPT Codex connection.

Only stdlib is required. Text and vision use the user's Codex Desktop login
or an explicit OpenAI-compatible CODEX_API_KEY.
"""
import json
import os
import random
import re
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from email.utils import parsedate_to_datetime

from ai_scheduler import AIRequestError, GLOBAL_AI_QUEUE

ROOT = Path(__file__).resolve().parent.parent

# таймаут одного LLM-вызова; генерация IR обычно 10-60с
TIMEOUT = int(os.environ.get("LLM_TIMEOUT_S", "120"))
RETRY_ATTEMPTS = max(1, int(os.environ.get("AI_RETRY_ATTEMPTS", "4")))
RETRY_BASE_S = max(0.05, float(os.environ.get("AI_RETRY_BASE_S", "0.75")))
RETRY_MAX_S = max(RETRY_BASE_S, float(os.environ.get("AI_RETRY_MAX_S", "12")))
TRANSIENT_HTTP_CODES = {429, 502, 503}


def _retry_after_seconds(error: urllib.error.HTTPError) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return max(0.0, parsed.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


def _with_transient_retry(operation, timeout: float):
    """Retry provider throttling/outages inside one caller deadline."""
    deadline = time.monotonic() + max(0.001, timeout)
    last_error = None
    for attempt in range(RETRY_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AIRequestError("таймаут", "deadline AI-запроса истёк") from last_error
        try:
            return operation(max(1, int(remaining)))
        except urllib.error.HTTPError as exc:
            if exc.code not in TRANSIENT_HTTP_CODES:
                raise
            last_error = exc
            if attempt + 1 >= RETRY_ATTEMPTS:
                raise AIRequestError("лимит провайдера", f"HTTP {exc.code} после {RETRY_ATTEMPTS} попыток") from exc
            exponential = min(RETRY_MAX_S, RETRY_BASE_S * (2 ** attempt))
            jittered = random.uniform(exponential * 0.5, exponential * 1.5)
            delay = max(jittered, _retry_after_seconds(exc) or 0.0)
            if delay >= deadline - time.monotonic():
                raise AIRequestError("таймаут", "Retry-After выходит за deadline AI-запроса") from exc
            time.sleep(delay)
        except (TimeoutError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.URLError) and not isinstance(exc.reason, TimeoutError):
                raise
            raise AIRequestError("таймаут", "таймаут соединения с AI-провайдером") from exc
    raise AIRequestError("лимит провайдера", "временная ошибка AI-провайдера") from last_error


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

CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
CHATGPT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
PROVIDERS = {
    "codex": {
        # CODEX_BASE_URL may be a base URL or a full /chat/completions URL.
        "url": os.environ.get("CODEX_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        "env": "CODEX_API_KEY",
        "model": None,
        "label": "GPT Codex",
    },
}

# Every role resolves to the same user-owned Codex connection. Role-specific
# CODEX_MODELS_<ROLE> overrides keep the existing role semantics without a
# silent vendor fallback.
_CODEX_ROLES = (
    "prompt_enhancer", "planner", "motion_director", "generator", "reskin",
    "repair", "style_analysis", "vision", "vision_fast", "vision_pixel_qa",
    "judge", "quality_judge", "quality_repair", "edit", "derive", "optimizer",
    "tokens", "components", "clone", "blockparse", "source_semantics",
    "source_vision_audit", "reproduce", "a11y", "docs", "mechanics", "taste",
)
ROUTING = {role: [CODEX_DEFAULT_MODEL] for role in _CODEX_ROLES}


def routing_models(role: str) -> list:
    env_key = "CODEX_MODELS_" + role.upper()
    if os.environ.get(env_key):
        return [m.strip() for m in os.environ[env_key].split(",") if m.strip()]
    role_model = os.environ.get("CODEX_MODEL_" + role.upper(), "").strip()
    if role_model:
        return [role_model]
    default_model = os.environ.get("CODEX_MODEL", "").strip()
    if default_model:
        return [default_model]
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


def _codex_auth_path() -> Path:
    configured = os.environ.get("CODEX_AUTH_FILE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex" / "auth.json"


def _load_codex_auth() -> dict | None:
    """Load the ChatGPT-managed token only in memory; never persist or log it."""
    try:
        raw = json.loads(_codex_auth_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    tokens = raw.get("tokens") if isinstance(raw, dict) else None
    if not isinstance(tokens, dict):
        return None
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    auth_mode = str(raw.get("auth_mode") or "").strip().lower()
    if auth_mode and auth_mode not in {"chatgpt", "chatgpt-managed"}:
        return None
    account_id = tokens.get("account_id")
    return {
        "auth_mode": "chatgpt",
        "access_token": access_token.strip(),
        "account_id": account_id.strip() if isinstance(account_id, str) else "",
    }


def _chatgpt_auth_allowed(cfg: dict) -> bool:
    """Do not use the user's auth file for local mock endpoints."""
    mode = os.environ.get("CODEX_AUTH_MODE", "auto").strip().lower()
    if mode in {"off", "disabled", "api_key", "apikey"}:
        return False
    parsed = urllib.parse.urlsplit(str(cfg.get("url", "")).strip())
    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return False
    # An explicit auth-file path opts in for a custom remote gateway.
    if os.environ.get("CODEX_AUTH_FILE", "").strip():
        return True
    return host in {"api.openai.com", "chatgpt.com"}


def _codex_connection(cfg: dict) -> dict:
    """Resolve request auth without exposing credentials in metadata."""
    env_name = cfg.get("env", "CODEX_API_KEY")
    explicit_key = os.environ.get(env_name, "").strip()
    if explicit_key:
        return {"auth_mode": "api_key", "key": explicit_key, "account_id": ""}
    if _chatgpt_auth_allowed(cfg):
        auth = _load_codex_auth()
        if auth:
            return {
                "auth_mode": "chatgpt",
                "key": auth["access_token"],
                "account_id": auth.get("account_id", ""),
            }
    raise RuntimeError(
        "Нет Codex credentials: задайте CODEX_API_KEY или войдите в Codex Desktop "
        f"(ожидается {_codex_auth_path()})."
    )


def _legacy_get_explicit_key(cfg: dict) -> str:
    key = os.environ.get(cfg.get("env", ""))
    if not key:
        raise RuntimeError(f"Нет ключа: set {cfg.get('env', '?')}=...")
    return key


# Resolve either explicit API-key auth or the live Codex Desktop auth file.
def get_key(cfg: dict) -> str:
    return _codex_connection(cfg)["key"]


def load(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def build_system_prompt(mode: str = "generate") -> str:
    template = load("spike/system-prompt.md")
    template = template.split("---", 1)[-1]  # убрать шапку-описание
    return (
        template.replace("{{SCHEMA}}", load("schema/design-ir.schema.json"))
        .replace("{{BLOCKS}}", load("app/prompts/BLOCKS.md"))
        .replace("{{BRIEF}}", "")
        .replace("{{STYLE_HINT}}", "")
        .replace("{{MODE}}", mode)
        .strip()
    )


def chat_endpoint(cfg: dict) -> str:
    """Resolve a configurable Codex base URL to chat completions."""
    url = str(cfg.get("url", "")).strip().rstrip("/")
    if not url:
        raise RuntimeError("CODEX_BASE_URL is not configured")
    return url if url.endswith("/chat/completions") else f"{url}/chat/completions"


def public_config() -> dict:
    """Return safe provider metadata; never expose credentials."""
    cfg = PROVIDERS["codex"]
    connection = None
    try:
        connection = _codex_connection(cfg)
    except RuntimeError:
        pass
    parsed = urllib.parse.urlsplit(
        CHATGPT_CODEX_BASE_URL if connection and connection["auth_mode"] == "chatgpt"
        else str(cfg.get("url", ""))
    )
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    return {
        "id": "codex",
        "label": "GPT Codex",
        "configured": connection is not None,
        "authMode": connection["auth_mode"] if connection else None,
        "baseUrlHost": host or "custom",
        "model": routing_models("generator")[0],
    }


def _post_json(url: str, payload: dict, key: str | None, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _responses_content(content):
    """Translate Chat Completions content parts to Responses input parts."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append({"type": "input_text", "text": part})
            continue
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in {"text", "input_text"}:
            parts.append({"type": "input_text", "text": str(part.get("text", ""))})
        elif kind in {"image_url", "input_image"}:
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if url:
                parts.append({"type": "input_image", "image_url": url})
    return parts


def _responses_payload(model: str, messages: list) -> dict:
    instructions = []
    inputs = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if role == "system":
            instructions.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
            continue
        if role not in {"user", "assistant", "developer"}:
            role = "user"
        inputs.append({"role": role, "content": _responses_content(content)})
    payload = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": "\n\n".join(instructions),
        "input": inputs,
    }
    effort = os.environ.get("CODEX_REASONING_EFFORT", "medium").strip()
    if effort:
        payload["reasoning"] = {"effort": effort}
    if os.environ.get("CODEX_JSON_MODE", "1").strip().lower() not in {"0", "false", "off"}:
        payload["text"] = {"format": {"type": "json_object"}}
    return payload


def _response_output_text(data) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("output_text")
    if isinstance(direct, str):
        return direct
    response = data.get("response")
    if isinstance(response, dict):
        found = _response_output_text(response)
        if found:
            return found
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    pieces = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)


def _parse_responses_stream(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return _response_output_text(json.loads(stripped)).strip()
        except ValueError:
            pass
    deltas = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        item = line[5:].strip()
        if not item or item == "[DONE]":
            continue
        try:
            event = json.loads(item)
        except ValueError:
            continue
        if event.get("type") == "error":
            detail = event.get("error") or event.get("message") or "unknown error"
            raise RuntimeError(f"Codex Responses error: {str(detail)[:300]}")
        if event.get("type") == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                deltas.append(delta)
        elif not deltas and event.get("type") in {"response.output_text.done", "response.completed"}:
            fallback = _response_output_text(event)
            if fallback:
                deltas.append(fallback)
    return "".join(deltas).strip()


def _post_codex_responses(payload: dict, key: str, account_id: str, timeout: int) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "codex_cli_rs",
        "originator": "codex_cli_rs",
        "openai-beta": "responses=experimental",
        "session_id": str(uuid.uuid4()),
    }
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    req = urllib.request.Request(
        f"{CHATGPT_CODEX_BASE_URL}/responses", data=body, headers=headers
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _chat_codex_responses_once(key, account_id, model, messages, timeout) -> str:
    payload = _responses_payload(model, messages)
    for attempt in range(3):
        try:
            content = _parse_responses_stream(
                _post_codex_responses(payload, key, account_id, timeout)
            )
            if not content:
                raise RuntimeError("пустой content в Codex Responses")
            return content
        except urllib.error.HTTPError as error:
            if error.code != 400:
                raise
            # Older Codex gateways may not expose structured JSON output yet.
            if attempt == 0 and "text" in payload:
                payload.pop("text", None)
                continue
            if attempt == 1 and "reasoning" in payload:
                payload.pop("reasoning", None)
                continue
            raise
    raise RuntimeError("Codex Responses: не удалось получить ответ")


def _call_codex_vision(key, account_id, model, image_data_url, text_prompt,
                       system_prompt, timeout):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ],
    })
    return _chat_codex_responses_once(key, account_id, model, messages, timeout)


def _chat_openai_once(cfg, key, model, messages, temp, t) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "response_format": {"type": "json_object"},
    }
    data = None
    for attempt in range(3):
        try:
            data = _post_json(chat_endpoint(cfg), payload, key, t)
            break
        except urllib.error.HTTPError as e:
            if e.code == 400 and attempt == 0:
                # Some Codex-compatible endpoints expose JSON mode under a
                # different name; keep the request usable without it.
                payload.pop("response_format", None)
                continue
            if e.code == 400 and attempt == 1:
                # Reasoning-first Codex deployments may reject temperature.
                payload.pop("temperature", None)
                continue
            raise
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip():
        raise RuntimeError(f"пустой content (reasoning: {str(msg.get('reasoning_content'))[:100]!r})")
    return content


def chat(provider: str, messages: list, temperature: float, timeout: int | None = None,
         role: str = "mechanics", model: str | None = None,
         priority: str = "normal") -> str:
    """Call the user-owned GPT Codex endpoint."""
    if model is not None:
        _check_model_slug(model)
    if provider != "codex":
        raise ValueError("Поддерживается только provider=codex")
    cfg = PROVIDERS["codex"]
    connection = _codex_connection(cfg)
    key = connection["key"]
    auth_mode = connection["auth_mode"]
    account_id = connection.get("account_id", "")
    t = timeout or TIMEOUT
    temp = temperature

    # явный model > цепочка ROUTING
    if model:
        models = [model]
    else:
        models = routing_models(role) if cfg["model"] is None else [cfg["model"]]
    for m in models:  # валидны все пути разрешения: явный, cfg, ROUTING/env
        _check_model_slug(m)
    def perform(remaining: float) -> str:
        last_error = None
        for selected_model in models:
            try:
                def request(request_timeout: int) -> str:
                    if auth_mode == "chatgpt":
                        return _chat_codex_responses_once(
                            key, account_id, selected_model, messages, request_timeout
                        )
                    return _chat_openai_once(
                        cfg, key, selected_model, messages, temp, request_timeout
                    )

                return _with_transient_retry(request, remaining)
            except AIRequestError:
                raise
            except urllib.error.HTTPError as e:
                last_error = f"{selected_model} HTTP {e.code}: {e.read()[:300]!r}"
                if e.code in (404, 500) and selected_model != models[-1]:
                    continue
                raise RuntimeError(f"{provider} {last_error}")
        raise RuntimeError(f"{provider}: все модели цепочки недоступны. Последняя ошибка: {last_error}")

    return GLOBAL_AI_QUEUE.run(perform, timeout=t, priority=priority)


def chat_vision(provider: str, image_data_url: str, text_prompt: str,
                system_prompt: str = "", temperature: float = 0.2,
                timeout: int | None = None, role: str = "vision",
                priority: str = "normal") -> str:
    """Vision call through the same user-owned Codex endpoint."""
    if provider != "codex":
        raise ValueError("Поддерживается только provider=codex")
    cfg = PROVIDERS["codex"]
    connection = _codex_connection(cfg)
    key = connection["key"]
    auth_mode = connection["auth_mode"]
    account_id = connection.get("account_id", "")
    t = timeout or TIMEOUT

    vision_models = routing_models(role)
    if isinstance(vision_models, str):
        vision_models = [vision_models]
    for m in vision_models:
        _check_model_slug(m)

    def perform(remaining: float) -> str:
        last_error = None
        for selected_model in vision_models:
            try:
                def request(request_timeout: int) -> str:
                    if auth_mode == "chatgpt":
                        return _call_codex_vision(
                            key, account_id, selected_model, image_data_url,
                            text_prompt, system_prompt, request_timeout,
                        )
                    return _call_openai_vision(
                        cfg, key, selected_model, image_data_url, text_prompt,
                        system_prompt, temperature, request_timeout,
                    )

                content = _with_transient_retry(request, remaining)
                if content and content.strip():
                    return content
            except AIRequestError:
                raise
            except urllib.error.HTTPError as e:
                err_body = e.read()[:300]
                last_error = f"{selected_model} HTTP {e.code}: {err_body!r}"
                if e.code in (404, 400, 403) and selected_model != vision_models[-1]:
                    continue
                raise RuntimeError(f"{provider} vision {last_error}")
            except Exception as e:
                last_error = str(e)
                if selected_model == vision_models[-1]:
                    raise
        raise RuntimeError(f"{provider} vision: все модели недоступны. Последняя ошибка: {last_error}")

    return GLOBAL_AI_QUEUE.run(perform, timeout=t, priority=priority)


def _call_openai_vision(cfg, key, model, image_data_url, text_prompt, system_prompt,
                        temperature, timeout):
    """Vision request in the OpenAI-compatible chat format."""
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
    data = _post_json(chat_endpoint(cfg), payload, key, timeout)
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
    p.add_argument("--provider", choices=PROVIDERS, required=True)
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
