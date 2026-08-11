"""Продакшен LLM-клиент DesignAI Web (ранее жил в spike/run_test.py).

Только stdlib. Все текстовые и vision-вызовы проходят через OpenRouter.
Таймауты: LLM_TIMEOUT_S (по умолчанию 120с), раньше было 600с.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    # Единственный транспорт продукта. Модель выбирается из ROUTING по роли.
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env": "OPENROUTER_API_KEY",
        "model": None,
    },
}

# Роутинг моделей через OpenRouter (роль ноды → [основная, fallback]).
# Любую роль можно переопределить env: OPENROUTER_MODELS_<ROLE> (через запятую).
# Current quality-first routing:
# - Claude owns taste, composition, design generation, reskin and judging.
# - Gemini is a multimodal fallback for visual import/reproduction.
# - Qwen is reserved for mechanical IR/JSON/schema repair.
# - Kimi is intentionally not a default route; test it only via env overrides.
ROUTING = {
    # канонические роли владельца (конфиг от 2026-08-05)
    "prompt_enhancer": ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5"],
    "planner":    ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    "generator":  ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "openai/gpt-5.6-sol"],
    "reskin":     ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "openai/gpt-5.6-sol"],
    "repair":     ["qwen/qwen3-coder-plus", "anthropic/claude-sonnet-5"],
    "style_analysis": ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    "vision":     ["anthropic/claude-opus-5", "google/gemini-3.6-flash", "openai/gpt-5.6-sol", "qwen/qwen3.8-max"],
    "vision_fast": ["google/gemini-3.6-flash", "qwen/qwen3.8-max", "anthropic/claude-sonnet-5"],
    "vision_pixel_qa": ["anthropic/claude-opus-5", "openai/gpt-5.6-sol", "google/gemini-3.6-flash"],
    "judge":      ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    # Премиальный Quality Pass: независимая оценка и адресная починка.
    "quality_judge": ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "openai/gpt-5.6-sol-pro"],
    "quality_repair": ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "qwen/qwen3-coder-plus"],
    # дополнительные роли из таблицы 2026-08-04
    "edit":       ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    "derive":     ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    "optimizer":  ["qwen/qwen3-coder-plus", "anthropic/claude-sonnet-5"],
    "tokens":     ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    "components": ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5", "google/gemini-3.6-flash"],
    "clone":      ["anthropic/claude-sonnet-5", "qwen/qwen3-coder-plus"],
    "blockparse": ["anthropic/claude-sonnet-5", "qwen/qwen3-coder-plus"],
    # Source Import geometry stays deterministic; Sonnet labels only ambiguous
    # rendered containers. Opus is an escalation, not the pixel/layout engine.
    "source_semantics": ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5"],
    "source_vision_audit": ["anthropic/claude-opus-5", "openai/gpt-5.6-sol", "google/gemini-3.6-flash"],
    "reproduce":  ["anthropic/claude-opus-5", "google/gemini-3.6-flash", "qwen/qwen3.8-max"],
    "a11y":       ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
    "docs":       ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5"],
    # legacy-роли (старые вызовы и env-оверрайды)
    "mechanics":  ["qwen/qwen3-coder-plus", "anthropic/claude-sonnet-5"],
    "taste":      ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"],
}


def routing_models(role: str) -> list:
    env_key = "OPENROUTER_MODELS_" + role.upper()
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


def get_key(cfg: dict) -> str:
    key = os.environ.get(cfg.get("env", ""))
    if not key:
        raise RuntimeError(f"Нет ключа: set {cfg.get('env', '?')}=...")
    return key


def load(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def build_system_prompt(mode: str = "generate") -> str:
    template = load("spike/system-prompt.md")
    template = template.split("---", 1)[-1]  # убрать шапку-описание
    return (
        template.replace("{{SCHEMA}}", load("schema/design-ir.schema.json"))
        .replace("{{BLOCKS}}", load("docs/BLOCKS.md"))
        .replace("{{BRIEF}}", "")
        .replace("{{STYLE_HINT}}", "")
        .replace("{{MODE}}", mode)
        .strip()
    )


def _post_json(url: str, payload: dict, key: str | None, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _chat_openai_once(cfg, key, model, messages, temp, t) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "response_format": {"type": "json_object"},
    }
    data = None
    for attempt in (True, False):  # если response_format не поддержан — повтор без него
        try:
            data = _post_json(cfg["url"], payload, key, t)
            break
        except urllib.error.HTTPError as e:
            if attempt and e.code == 400:
                payload.pop("response_format", None)
                continue
            raise
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip():
        raise RuntimeError(f"пустой content (reasoning: {str(msg.get('reasoning_content'))[:100]!r})")
    return content


def chat(provider: str, messages: list, temperature: float, timeout: int | None = None,
         role: str = "mechanics", model: str | None = None) -> str:
    """Вызов OpenRouter. role выбирает цепочку ROUTING, model — явный override."""
    if model is not None:
        _check_model_slug(model)
    if provider != "openrouter":
        raise ValueError("Поддерживается только provider=openrouter")
    cfg = PROVIDERS["openrouter"]
    key = get_key(cfg)
    t = timeout or TIMEOUT
    temp = temperature

    # явный model > цепочка ROUTING
    if model:
        models = [model]
    else:
        models = routing_models(role) if cfg["model"] is None else [cfg["model"]]
    for m in models:  # валидны все пути разрешения: явный, cfg, ROUTING/env
        _check_model_slug(m)
    last_error = None
    for model in models:
        try:
            return _chat_openai_once(cfg, key, model, messages, temp, t)
        except urllib.error.HTTPError as e:
            last_error = f"{model} HTTP {e.code}: {e.read()[:300]!r}"
            if e.code in (404, 429, 500, 502, 503) and model != models[-1]:
                continue  # fallback на следующую модель цепочки
            raise RuntimeError(f"{provider} {last_error}")
    raise RuntimeError(f"{provider}: все модели цепочки недоступны. Последняя ошибка: {last_error}")


def chat_vision(provider: str, image_data_url: str, text_prompt: str,
                system_prompt: str = "", temperature: float = 0.2,
                timeout: int | None = None, role: str = "vision") -> str:
    """Vision-вызов через OpenRouter с fallback-моделями роли."""
    if provider != "openrouter":
        raise ValueError("Поддерживается только provider=openrouter")
    cfg = PROVIDERS["openrouter"]
    key = get_key(cfg)
    t = timeout or TIMEOUT

    vision_models = routing_models(role)
    if isinstance(vision_models, str):
        vision_models = [vision_models]
    for m in vision_models:
        _check_model_slug(m)

    last_error = None
    for model in vision_models:
        try:
            content = _call_openai_vision(cfg, key, model, image_data_url,
                                          text_prompt, system_prompt, temperature, t)
            if content and content.strip():
                return content
        except urllib.error.HTTPError as e:
            err_body = e.read()[:300]
            last_error = f"{model} HTTP {e.code}: {err_body!r}"
            if e.code in (404, 400, 429, 403):
                continue
            raise RuntimeError(f"{provider} vision {last_error}")
        except Exception as e:
            last_error = str(e)
            continue

    raise RuntimeError(f"{provider} vision: все модели недоступны. Последняя ошибка: {last_error}")


def _call_openai_vision(cfg, key, model, image_data_url, text_prompt, system_prompt,
                        temperature, timeout):
    """OpenRouter vision-вызов в OpenAI-совместимом формате."""
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
    data = _post_json(cfg["url"], payload, key, timeout)
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
