"""Продакшен LLM-клиент DesignAI Web (ранее жил в spike/run_test.py).

Только stdlib. Поддерживает OpenAI-совместимые API и Gemini (текст + vision).
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
    # Kimi: локальная OAuth-авторизация kimi CLI (coding plan), ключ из
    # ~/.kimi-code/credentials/kimi-code.json
    "kimi": {
        "url": "https://api.kimi.com/coding/v1/chat/completions",
        "oauth_credentials": "~/.kimi-code/credentials/kimi-code.json",
        "model": "k3",
        "fixed_temperature": 1,  # k3 принимает только temperature=1
    },
    # Qwen: Alibaba Bailian Token Plan, ключ в env BAILIAN_TOKEN_PLAN_API_KEY
    "qwen": {
        "url": "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        "env": "BAILIAN_TOKEN_PLAN_API_KEY",
        "model": "qwen3.7-max",
        "vision_models": ["qwen-vl-max-latest", "qwen-vl-max", "qwen2.5-vl-72b-instruct", "qwen-vl-plus"],
    },
    # Groq: бесплатный tier, OpenAI-совместимый API, ключ GROQ_API_KEY
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
        "vision_models": ["llama-3.2-90b-vision-preview", "llama-3.2-11b-vision-preview"],
    },
    # Google Gemini: бесплатный tier, ключ GEMINI_API_KEY (aistudio.google.com)
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta",
        "env": "GEMINI_API_KEY",
        "model": "gemini-2.0-flash",
        "vision_models": ["gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "api_format": "gemini",
    },
    # xAI Grok: ключ XAI_API_KEY (console.x.ai), OpenAI-совместимый, vision через grok-2-vision
    "xai": {
        "url": "https://api.x.ai/v1/chat/completions",
        "env": "XAI_API_KEY",
        "model": "grok-3-beta",
        "vision_models": ["grok-2-vision", "grok-2-vision-1212", "grok-vision-beta"],
    },
    # GLM (Zhipu AI): ключ GLM_API_KEY (open.bigmodel.cn), OpenAI-совместимый, vision через glm-4v
    "glm": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "env": "GLM_API_KEY",
        "model": "glm-4-plus",
        "vision_models": ["glm-4v", "glm-4v-plus"],
    },
}


def get_key(cfg: dict) -> str:
    if "oauth_credentials" in cfg:
        cred_path = Path(os.path.expanduser(cfg["oauth_credentials"]))
        cred = json.loads(cred_path.read_text(encoding="utf-8"))
        return cred["access_token"]
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


def _gemini_messages(messages: list, temperature: float) -> dict:
    """OpenAI-сообщения → payload Gemini generateContent (текст)."""
    payload = {"contents": [], "generationConfig": {
        "temperature": temperature, "responseMimeType": "application/json"}}
    for m in messages:
        if m["role"] == "system":
            payload["system_instruction"] = {"parts": [{"text": m["content"]}]}
        else:
            role = "model" if m["role"] == "assistant" else "user"
            payload["contents"].append({"role": role, "parts": [{"text": m["content"]}]})
    return payload


def _gemini_text(data: dict, provider: str) -> str:
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"{provider}: нет candidates в ответе Gemini")
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def chat(provider: str, messages: list, temperature: float, timeout: int | None = None) -> str:
    cfg = PROVIDERS[provider]
    key = get_key(cfg)
    t = timeout or TIMEOUT
    temp = cfg.get("fixed_temperature", temperature)

    if cfg.get("api_format") == "gemini":
        data = _post_json(f"{cfg['url']}/models/{cfg['model']}:generateContent",
                          _gemini_messages(messages, temp), key, t)
        content = _gemini_text(data, provider)
        if not content.strip():
            raise RuntimeError(f"{provider}: пустой ответ Gemini")
        return content

    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temp,
        "response_format": {"type": "json_object"},
    }
    for attempt in (True, False):  # если response_format не поддержан — повтор без него
        try:
            data = _post_json(cfg["url"], payload, key, t)
            break
        except urllib.error.HTTPError as e:
            if attempt and e.code == 400:
                payload.pop("response_format", None)
                continue
            raise RuntimeError(f"{provider} HTTP {e.code}: {e.read()[:300]!r}")
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip():
        raise RuntimeError(f"{provider}: пустой content (reasoning: {str(msg.get('reasoning_content'))[:100]!r})")
    return content


def chat_vision(provider: str, image_data_url: str, text_prompt: str,
                system_prompt: str = "", temperature: float = 0.2,
                timeout: int | None = None) -> str:
    """Вызов vision-модели с изображением (base64 data URL) + текст.
    Поддерживает OpenAI-совместимый API и Gemini API.
    Пробует несколько vision-моделей из конфига (fallback при 404)."""
    cfg = PROVIDERS[provider]
    key = get_key(cfg)
    t = timeout or TIMEOUT

    vision_models = cfg.get("vision_models", [cfg.get("vision_model", cfg["model"])])
    if isinstance(vision_models, str):
        vision_models = [vision_models]

    api_format = cfg.get("api_format", "openai")

    # извлекаем base64 и mime из data URL
    mime_type = "image/jpeg"
    b64_data = image_data_url
    if image_data_url.startswith("data:"):
        header, b64_data = image_data_url.split(",", 1)
        if "png" in header:
            mime_type = "image/png"
        elif "webp" in header:
            mime_type = "image/webp"

    last_error = None
    for model in vision_models:
        try:
            if api_format == "gemini":
                content = _call_gemini_vision(cfg, key, model, b64_data, mime_type,
                                              text_prompt, system_prompt, temperature, t)
            else:
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
    """OpenAI-совместимый vision вызов (Groq, Qwen, OpenAI, etc)."""
    user_content = [
        {"type": "image_url", "image_url": {"url": image_data_url}},
        {"type": "text", "text": text_prompt},
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


def _call_gemini_vision(cfg, key, model, b64_data, mime_type, text_prompt, system_prompt,
                        temperature, timeout):
    """Google Gemini vision вызов."""
    url = f"{cfg['url']}/models/{model}:generateContent"
    parts = [
        {"inline_data": {"mime_type": mime_type, "data": b64_data}},
        {"text": text_prompt},
    ]
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

    data = _post_json(url, payload, key, timeout)
    return _gemini_text(data, "Gemini")


def extract_json(text: str) -> str:
    """Вытащить JSON даже если модель обернула в markdown."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        return m.group(1)
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


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
