"""Единый источник путей и переменных окружения: значения по умолчанию, переопределения, описание без секретов."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402

APP = Path(__file__).resolve().parent


def test_defaults_follow_the_repository_layout(monkeypatch):
    for name in ("DESIGNDNA_APP_DIR", "DESIGNDNA_RUNTIME_ROOT", "DESIGNDNA_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert settings.app_dir() == APP
    assert settings.runtime_root() == APP.parent
    assert settings.data_dir() == APP.parent / "data"
    assert settings.fonts_dir() == APP.parent / "data" / "fonts"
    assert settings.renders_dir() == APP.parent / "data" / "renders"
    assert settings.traces_dir() == APP.parent / "data" / "traces"
    assert settings.schema_dir() == APP.parent / "schema"


def test_environment_overrides_are_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("DESIGNDNA_APP_DIR", str(tmp_path / "resources" / "app"))
    monkeypatch.setenv("DESIGNDNA_RUNTIME_ROOT", str(tmp_path / "resources"))
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path / "userdata" / "data"))
    assert settings.app_dir() == tmp_path / "resources" / "app"
    assert settings.runtime_root() == tmp_path / "resources"
    assert settings.data_dir() == tmp_path / "userdata" / "data"
    assert settings.blobs_dir() == tmp_path / "userdata" / "data" / "blobs"
    monkeypatch.delenv("DESIGNDNA_DATA_DIR")
    assert settings.data_dir() == tmp_path / "resources" / "data", "без DATA_DIR данные лежат под runtime root"


def test_describe_lists_paths_and_env_names_without_secret_values(monkeypatch, tmp_path):
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-value")
    monkeypatch.setenv("DESIGNAI_FLAG_VIDEOEDITOR", "0")
    described = settings.describe()
    assert described["dataDir"] == str(tmp_path)
    assert "DESIGNDNA_DATA_DIR" in described["configuredEnv"]
    assert "OPENROUTER_API_KEY" in described["configuredEnv"]
    assert "DESIGNAI_FLAG_VIDEOEDITOR" in described["configuredEnv"]
    assert "sk-or-secret-value" not in json.dumps(described)
    assert set(settings.SECRET_ENV_VARS) <= set(settings.ENV_VARS)


def test_store_modules_derive_their_paths_from_settings(monkeypatch, tmp_path):
    """Модули берут константы при импорте, но реестр ДС и шрифты читают путь в момент вызова."""
    import project_store
    import cache_store
    import llm_trace
    from design_system import store as ds_store

    assert project_store.DATA_ROOT == settings.data_dir() or project_store.DATA_ROOT == Path(project_store.DB_PATH).parent
    assert cache_store.DATA_ROOT == Path(cache_store.DB_PATH).parent
    assert llm_trace.trace_dir() == llm_trace.DATA_ROOT / "traces"
    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    assert ds_store._db_path() == tmp_path / "design_systems.db"
