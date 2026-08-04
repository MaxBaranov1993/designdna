#!/usr/bin/env python3
"""Тестовый прогон генерации Design IR через Kimi или Qwen.

Использование:
    set MOONSHOT_API_KEY=sk-...        # Kimi
    set DASHSCOPE_API_KEY=sk-...       # Qwen

    python run_test.py --provider kimi --brief "Лендинг для кофейни..."
    python run_test.py --provider qwen --brief-file brief.txt --temperature 0.9 --out results/b1-qwen-t09.json
    python run_test.py --provider qwen --repair broken.json --out fixed.json

Только stdlib, зависимостей нет.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    # console.groq.com — llama-3.2-90b-vision-preview (vision), llama-3.3-70b-versatile (text)
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


def chat(provider: str, messages: list, temperature: float) -> str:
    cfg = PROVIDERS[provider]
    key = get_key(cfg)
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("fixed_temperature", temperature),
        "response_format": {"type": "json_object"},
    }
    for attempt in (True, False):  # если response_format не поддержан — повтор без него
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            cfg["url"], data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read())
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
                system_prompt: str = "", temperature: float = 0.2) -> str:
    """Вызов vision-модели с изображением (base64 data URL) + текст.
    Поддерживает OpenAI-совместимый API и Gemini API.
    Пробует несколько vision-моделей из конфига (fallback при 404)."""
    cfg = PROVIDERS[provider]
    key = get_key(cfg)

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
                                              text_prompt, system_prompt, temperature)
            else:
                content = _call_openai_vision(cfg, key, model, image_data_url,
                                              text_prompt, system_prompt, temperature)
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


def _call_openai_vision(cfg, key, model, image_data_url, text_prompt, system_prompt, temperature):
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
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        cfg["url"], data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"].get("content") or ""


def _call_gemini_vision(cfg, key, model, b64_data, mime_type, text_prompt, system_prompt, temperature):
    """Google Gemini vision вызов."""
    url = f"{cfg['url']}/models/{model}:generateContent?key={key}"
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

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    # Gemini response: candidates[0].content.parts[0].text
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini: нет candidates в ответе")
    parts_resp = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts_resp)


def extract_json(text: str) -> str:
    """Вытащить JSON даже если модель обернула в markdown."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        return m.group(1)
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


def main() -> int:
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
    out = Path(args.out) if args.out else Path("results") / f"{args.provider}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(extract_json(raw), encoding="utf-8")
    print(f"Сохранено: {out}")
    print("Проверка: python spike/validate.py", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
