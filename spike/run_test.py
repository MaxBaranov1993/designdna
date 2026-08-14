#!/usr/bin/env python3
"""CLI-обёртка LLM-клиента. Сам клиент — app/llm_client.py (продакшен-модуль).

Использование:
    set CODEX_API_KEY=...
    python spike/run_test.py --provider codex --brief "Лендинг для кофейни..."
    python spike/run_test.py --provider codex --repair broken.json --out fixed.json
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from llm_client import (  # noqa: E402,F401 — реэкспорт: spike-скрипты импортируют run_test
    PROVIDERS, TIMEOUT, get_key, build_system_prompt, chat, chat_vision,
    extract_json, main,
)

if __name__ == "__main__":
    sys.exit(main())
