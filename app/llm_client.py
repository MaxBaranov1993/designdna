"""Продакшен LLM-клиент DesignAI Web (ранее жил в spike/run_test.py).

Только stdlib. Текстовые и vision-вызовы идут напрямую в OpenAI API и Kimi API
(OpenAI-совместимый формат), без OpenRouter. Модель задаётся композитным
slug'ом «provider/model»; записи цепочки без ключа в env пропускаются —
работает тот аккаунт, который подключён.
Таймауты: LLM_TIMEOUT_S (по умолчанию 120с), раньше было 600с.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
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
}

# Роутинг моделей по ролям (роль ноды → [основная, fallback]).
# Каждая запись — композитный slug «provider/model» (разбор по первому '/').
# Если у записи нет ключа провайдера в env — она пропускается: так цепочка
# сама выбирает подключённый аккаунт (только Kimi → Kimi, только OpenAI → OpenAI).
# Любую роль можно переопределить env: LLM_MODELS_<ROLE> (через запятую).
# Текущий роутинг: все роли — openai/gpt-5.6-sol с запасным kimi/k3
# (обе модели vision-capable).
STRONG = CHEAP = VISION = ["openai/gpt-5.6-sol", "kimi/k3", "glm/glm-5.3"]
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


def _provider_url(cfg: dict) -> str:
    """URL chat/completions провайдера; Kimi допускает оверрайд базы через env."""
    base = os.environ.get(cfg.get("base_env", ""), "")
    if base:
        return base.rstrip("/") + "/chat/completions"
    return cfg["url"]


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
    for _ in range(3):  # HTTP 400 → выбрасываем неподдержанный параметр и повторяем
        try:
            data = _post_json(_provider_url(cfg), payload, key, t)
            break
        except urllib.error.HTTPError as e:
            if e.code == 400 and "response_format" in payload:
                payload.pop("response_format")
                continue
            if e.code == 400 and "temperature" in payload:
                # kimi/k3 принимает только temperature=1 — полагаемся на дефолт сервера
                payload.pop("temperature")
                continue
            raise
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip():
        raise RuntimeError(f"пустой content (reasoning: {str(msg.get('reasoning_content'))[:100]!r})")
    return content


def chat(provider: str | None, messages: list, temperature: float, timeout: int | None = None,
         role: str = "mechanics", model: str | None = None) -> str:
    """Прямой вызов OpenAI/Kimi. role выбирает цепочку ROUTING, model — явный
    override, provider — необязательный фильтр (None/"auto" = вся цепочка).
    Записи цепочки без ключа провайдера в env пропускаются."""
    if model is not None:
        _check_model_slug(model)
    t = timeout or TIMEOUT
    temp = temperature

    chain = _resolve_chain(role, model, provider)
    skipped = []
    last_error = None
    for name, model_id, cfg in chain:
        key = os.environ.get(cfg["env"], "")
        if not key:
            skipped.append(f"{name}/{model_id}: нет {cfg['env']}")
            continue  # аккаунт провайдера не подключён — следующая запись
        try:
            return _chat_openai_once(cfg, key, model_id, messages, temp, t)
        except urllib.error.HTTPError as e:
            last_error = f"{name}/{model_id} HTTP {e.code}: {e.read()[:300]!r}"
            if e.code in (404, 429, 500, 502, 503) and (name, model_id, cfg) != chain[-1]:
                continue  # fallback на следующую модель цепочки
            raise RuntimeError(last_error)
    detail = f" Последняя ошибка: {last_error}." if last_error else ""
    if skipped:
        detail += " Пропущено без ключа: " + "; ".join(skipped)
    raise RuntimeError(f"все модели цепочки недоступны.{detail}")


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
