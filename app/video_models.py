"""Video account choices from Codex's local model catalogue; no project/network reads."""
import json
import os
import re
from pathlib import Path

EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}


def catalogue():
    models = []
    source = "defaults"
    try:
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        cached = json.loads((home / "models_cache.json").read_text(encoding="utf-8"))
        for item in cached.get("models", []):
            ident = item.get("slug", "")
            levels = [level["effort"] for level in item.get("supported_reasoning_levels", []) if level.get("effort") in EFFORTS]
            if item.get("visibility") == "hide" or not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", ident) or not levels:
                continue
            models.append({"provider": "codex", "id": ident, "label": item.get("display_name") or ident,
                           "efforts": levels, "defaultEffort": item.get("default_reasoning_level") if item.get("default_reasoning_level") in levels else levels[0]})
        if models:
            source = "codex-cache"
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        models = []
    if not models:
        models = [{"provider": "codex", "id": ident, "label": label, "efforts": ["medium", "high", "max"], "defaultEffort": "medium"}
                  for ident, label in [("gpt-5.6-sol", "GPT-5.6 Sol"), ("gpt-6-astra", "GPT-6 Astra")]]
    models.append({"provider": "claude", "id": "opus", "label": "Claude Opus", "efforts": ["medium", "high", "max"], "defaultEffort": "medium"})
    return {"models": models, "source": source}


def validate_selection(provider, model, effort):
    if provider not in {"codex", "claude"}:
        return
    if not model:
        return  # Keep saved requests without an explicit selection compatible.
    choice = next((item for item in catalogue()["models"] if item["provider"] == provider and item["id"] == model), None)
    if not choice:
        raise ValueError("Модель отсутствует в каталоге выбранного аккаунта. Выберите модель заново.")
    if effort not in choice["efforts"]:
        raise ValueError("Эта модель не поддерживает выбранный уровень рассуждения.")
