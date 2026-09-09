"""Общий слой хранения: фабрика соединений, транзакции, версии схем, статус баз."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from storage import db  # noqa: E402


def test_connect_applies_shared_pragmas_and_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "x.db"
    con = db.connect(path, busy_timeout_ms=1234)
    try:
        assert path.exists()
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert int(con.execute("PRAGMA busy_timeout").fetchone()[0]) == 1234
        assert int(con.execute("PRAGMA synchronous").fetchone()[0]) == 1  # NORMAL
        assert con.isolation_level is None
    finally:
        con.close()
    deferred = db.connect(path, isolation_level="DEFERRED")
    assert deferred.isolation_level == "DEFERRED"
    deferred.close()


def test_transaction_commits_rolls_back_and_closes(tmp_path):
    path = tmp_path / "t.db"
    with db.transaction(path, immediate=True) as con:
        con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO items (value) VALUES ('a')")
        assert con.in_transaction
    with pytest.raises(RuntimeError):
        with db.transaction(path) as con:
            con.execute("INSERT INTO items (value) VALUES ('b')")
            raise RuntimeError("boom")
    with db.transaction(path) as con:
        assert [row[0] for row in con.execute("SELECT value FROM items")] == ["a"]
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("SELECT 1")  # соединение закрыто после блока


def test_ensure_schema_applies_only_pending_steps(tmp_path):
    path = tmp_path / "s.db"
    applied = []

    def step1(con):
        applied.append(1)
        con.execute("CREATE TABLE IF NOT EXISTS a (id INTEGER)")

    def step2(con):
        applied.append(2)
        con.execute("ALTER TABLE a ADD COLUMN extra TEXT")

    con = db.connect(path)
    assert db.schema_version(con, "demo") == 0
    assert db.ensure_schema(con, "demo", [step1]) == 1
    assert db.ensure_schema(con, "demo", [step1]) == 1, "повторный вызов ничего не применяет"
    assert db.ensure_schema(con, "demo", [step1, step2]) == 2
    assert applied == [1, 2]
    assert db.schema_version(con, "demo") == 2
    assert db.schema_version(con, "other") == 0
    con.close()
    # режим неявных транзакций: миграция фиксируется сразу
    deferred = db.connect(path, isolation_level="")
    assert db.ensure_schema(deferred, "second", [step1]) == 1
    assert not deferred.in_transaction
    deferred.close()
    assert db.describe(path)["schemaVersions"] == {"demo": 2, "second": 1}


def test_describe_reports_tables_sizes_and_missing_files(tmp_path):
    path = tmp_path / "d.db"
    missing = db.describe(path)
    assert missing["exists"] is False and missing["tables"] == {}
    with db.transaction(path) as con:
        con.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY)")
        con.executemany("INSERT INTO rows (id) VALUES (?)", [(i,) for i in range(5)])
    info = db.describe(path)
    assert info["exists"] and info["bytes"] > 0
    assert info["journalMode"] == "wal"
    assert info["tables"] == {"rows": 5}
    assert db.describe(path, count_rows=False)["tables"] == {"rows": None}


def test_status_covers_all_application_databases(tmp_path, monkeypatch):
    import cache_store
    import project_store
    import server

    monkeypatch.setenv("DESIGNDNA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "projects.db")
    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "cache.db")
    project_store.save_project({"pages": []})
    from design_system import store as ds_store
    ds_store.list_systems()
    cache_store.put("demo", "k", {"v": 1})
    from fastapi.testclient import TestClient
    payload = TestClient(server.app).get("/api/storage/status").json()
    assert set(payload["databases"]) == {"projects", "design_systems", "cache"}
    assert payload["databases"]["projects"]["schemaVersions"] == {"projects": 1}
    assert payload["databases"]["design_systems"]["schemaVersions"] == {"design_systems": 1}
    assert payload["databases"]["projects"]["tables"]["projects"] == 1
    assert payload["databases"]["cache"]["userVersion"] == cache_store.SCHEMA_VERSION
    assert payload["databases"]["cache"]["journalMode"] == "wal"
    assert payload["dataRoot"] == str(tmp_path)
