"""Пути и переменные окружения DesignDNA в одном месте.

Раньше каталог данных вычислялся в двух десятках мест по одному и тому же
рецепту `Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")`. Здесь
рецепт один; модули берут свои константы отсюда при импорте, а код, которому
нужен путь в момент вызова (реестр ДС, шрифты), зовёт функции напрямую.

Переменные окружения, которые задают раскладку (в упакованном приложении их
выставляет desktop/lib/runtime-paths.mjs):

| Переменная               | Значение                                                        |
| ------------------------ | --------------------------------------------------------------- |
| DESIGNDNA_APP_DIR        | каталог app/ (в упакованном приложении resources/app)           |
| DESIGNDNA_RUNTIME_ROOT   | корень с app/ и schema/ (репозиторий или resources)             |
| DESIGNDNA_DATA_DIR       | данные: базы SQLite, blobs, fonts, renders, traces              |

Прочие переменные читают модули-владельцы, здесь они только перечислены,
чтобы агент видел полный список без grep по коду (см. ENV_VARS).
"""
from __future__ import annotations

import os
from pathlib import Path

_APP_DIR_DEFAULT = Path(__file__).resolve().parent.parent  # <…>/app

ENV_VARS: dict[str, str] = {
    "DESIGNDNA_APP_DIR": "каталог app/ с промптами, схемами рендера и пакетом инструкций агентов",
    "DESIGNDNA_RUNTIME_ROOT": "корень, где лежат app/ и schema/",
    "DESIGNDNA_DATA_DIR": "каталог данных пользователя: SQLite, blobs, fonts, renders, traces",
    "DESIGNDNA_HOST_PID": "pid Electron для вотчдога Python-воркера",
    "DESIGNDNA_SERVER_URL": "адрес HTTP-сервера для MCP-сервера (по умолчанию http://127.0.0.1:8420)",
    "DESIGNDNA_CODEX": "путь к бинарю Codex CLI для Python-пути",
    "DESIGNDNA_CLAUDE": "путь к бинарю Claude Code для Python-пути",
    "DESIGNDNA_CACHE_TTL_SECONDS": "TTL записей cache.db",
    "DESIGNDNA_CACHE_MAX_BYTES": "бюджет cache.db в байтах",
    "DESIGNDNA_CACHE_BUSY_TIMEOUT_MS": "busy_timeout cache.db",
    "DESIGNDNA_PROVIDER_CONCURRENCY": "лимиты слотов провайдеров в Electron, например claude=2,codex=2",
    "DESIGNAI_FLAG_<NAME>": "переопределение feature-флага (0/1), см. config/flags.py",
    "LLM_TIMEOUT_S": "таймаут HTTP-вызова модели",
    "LLM_CLI_TIMEOUT_S": "таймаут вызова Claude Code / Codex из Python",
    "LLM_CLI_PROVIDER": "какой CLI отвечает без ключа OpenAI: codex или claude",
    "OPENAI_API_KEY": "dev/тесты: прямой HTTP-путь OpenAI Responses (в продукте не используется)",
    "OPENAI_RESPONSES_URL": "dev/тесты: адрес OpenAI Responses",
    "OPENROUTER_API_KEY": "ключ OpenRouter для Seedance (видео)",
    "OPENROUTER_HTTP_REFERER": "заголовок Referer для OpenRouter",
    "DESIGNAI_UI_BASE": "адрес сервера для браузерных UI-тестов",
    "DESIGNDNA_CDP": "адрес CDP для проверок в Electron",
}

SECRET_ENV_VARS = frozenset({"OPENAI_API_KEY", "OPENROUTER_API_KEY"})


def app_dir() -> Path:
    """Каталог app/: промпты, схемы рендера, пакет инструкций агентов."""
    return Path(os.environ.get("DESIGNDNA_APP_DIR") or _APP_DIR_DEFAULT)


def runtime_root() -> Path:
    """Корень, где лежат app/ и schema/."""
    return Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or app_dir().parent)


def data_dir() -> Path:
    """Каталог данных пользователя."""
    return Path(os.environ.get("DESIGNDNA_DATA_DIR") or runtime_root() / "data")


def fonts_dir() -> Path:
    return data_dir() / "fonts"


def blobs_dir() -> Path:
    return data_dir() / "blobs"


def renders_dir() -> Path:
    return data_dir() / "renders"


def traces_dir() -> Path:
    return data_dir() / "traces"


def schema_dir() -> Path:
    return runtime_root() / "schema"


def describe() -> dict:
    """Раскладка путей и имена заданных переменных окружения. Значения секретов не раскрываются."""
    configured = sorted(name for name in ENV_VARS if not name.endswith("<NAME>") and os.environ.get(name))
    configured += sorted(name for name in os.environ if name.startswith("DESIGNAI_FLAG_"))
    return {
        "appDir": str(app_dir()),
        "runtimeRoot": str(runtime_root()),
        "dataDir": str(data_dir()),
        "schemaDir": str(schema_dir()),
        "fontsDir": str(fonts_dir()),
        "blobsDir": str(blobs_dir()),
        "rendersDir": str(renders_dir()),
        "tracesDir": str(traces_dir()),
        "configuredEnv": configured,
    }
