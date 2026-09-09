"""Единый способ открыть SQLite-базы приложения.

Раньше три хранилища открывали соединения по-разному: проекты — autocommit с
WAL и busy_timeout, кэш — отложенные транзакции с теми же прагмами, реестр
дизайн-систем — без прагм вовсе. Здесь один набор прагм, одна фабрика и
версия схемы на базу, чтобы миграции были явными шагами, а не «лечением по
месту».

Прагмы: WAL (читатели не блокируют писателя, что важно для одновременной
работы десктопа и MCP-сервера), busy_timeout вместо мгновенного SQLITE_BUSY,
synchronous=NORMAL (достаточно для локальных данных при WAL).
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BUSY_TIMEOUT_MS = 5_000
SCHEMA_TABLE = "schema_versions"
Migration = Callable[[sqlite3.Connection], None]


def connect(path: str | Path, *, isolation_level: str | None = None,
            busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """Соединение с общими прагмами. isolation_level=None — autocommit с явными
    BEGIN/COMMIT (проекты), "DEFERRED"/"" — неявные транзакции (кэш, реестр ДС)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = int(busy_timeout_ms)
    con = sqlite3.connect(str(target), timeout=max(timeout_ms / 1000.0, 0.001), isolation_level=isolation_level)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={timeout_ms}")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


@contextlib.contextmanager
def transaction(path: str | Path, *, immediate: bool = False,
                busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> Iterator[sqlite3.Connection]:
    """Одно соединение — одна транзакция; соединение закрывается всегда.
    BEGIN IMMEDIATE — для писателей из разных процессов."""
    con = connect(path, isolation_level=None, busy_timeout_ms=busy_timeout_ms)
    try:
        con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield con
        con.execute("COMMIT")
    except BaseException:
        with contextlib.suppress(sqlite3.Error):
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def schema_version(con: sqlite3.Connection, name: str) -> int:
    """Текущая версия схемы базы `name`; 0 — таблицы версий ещё нет."""
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (SCHEMA_TABLE,)).fetchone()
    if not exists:
        return 0
    row = con.execute(f"SELECT version FROM {SCHEMA_TABLE} WHERE name=?", (name,)).fetchone()
    return int(row[0]) if row else 0


def ensure_schema(con: sqlite3.Connection, name: str, migrations: Sequence[Migration]) -> int:
    """Применяет недостающие шаги миграции по порядку и записывает версию.

    Шаг i (с 1) выполняется, если текущая версия меньше i. Первый шаг обычно
    создаёт таблицы через CREATE TABLE IF NOT EXISTS, поэтому на базе, которая
    существовала до появления версий, он безопасен и лишь фиксирует версию 1.
    Возвращает итоговую версию.
    """
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} ("
        "name TEXT PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL)")
    current = schema_version(con, name)
    for index, step in enumerate(migrations, start=1):
        if index <= current:
            continue
        step(con)
        con.execute(
            f"INSERT INTO {SCHEMA_TABLE} (name, version, applied_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET version=excluded.version, applied_at=excluded.applied_at",
            (name, index, _now()))
        current = index
    if con.in_transaction and con.isolation_level is not None:
        # неявная транзакция режима DEFERRED/"" — фиксируем миграцию сразу
        con.commit()
    return current


def describe(path: str | Path, *, count_rows: bool = True) -> dict[str, Any]:
    """Описание базы без записи: размер, режим журнала, версии, таблицы и строки."""
    target = Path(path)
    info: dict[str, Any] = {"path": str(target), "exists": target.exists(), "bytes": 0, "walBytes": 0,
                            "journalMode": None, "userVersion": None, "schemaVersions": {}, "tables": {}}
    if not target.exists():
        return info
    info["bytes"] = target.stat().st_size
    wal = target.with_name(target.name + "-wal")
    info["walBytes"] = wal.stat().st_size if wal.exists() else 0
    uri = f"{target.resolve().as_uri()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.Error as exc:
        info["error"] = str(exc)
        return info
    try:
        info["journalMode"] = str(con.execute("PRAGMA journal_mode").fetchone()[0])
        info["userVersion"] = int(con.execute("PRAGMA user_version").fetchone()[0])
        tables = [str(row[0]) for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if SCHEMA_TABLE in tables:
            info["schemaVersions"] = {str(name): int(version) for name, version in
                                      con.execute(f"SELECT name, version FROM {SCHEMA_TABLE}")}
        for table in tables:
            if table == SCHEMA_TABLE:
                continue
            rows = None
            if count_rows:
                rows = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            info["tables"][table] = rows
    except sqlite3.Error as exc:
        info["error"] = str(exc)
    finally:
        con.close()
    return info


def databases() -> dict[str, Path]:
    """Актуальные пути баз по состоянию модулей-владельцев (учитывают подмены в тестах)."""
    import cache_store
    import project_store
    from design_system import store as design_system_store

    return {
        "projects": Path(project_store.DB_PATH),
        "design_systems": Path(design_system_store._db_path()),
        "cache": Path(cache_store.DB_PATH),
    }


def status(*, count_rows: bool = True) -> dict[str, Any]:
    """Сводка по всем базам приложения плюс каталог данных."""
    entries = {name: describe(path, count_rows=count_rows) for name, path in databases().items()}
    data_root = str(Path(os.environ.get("DESIGNDNA_DATA_DIR") or Path(__file__).resolve().parents[2] / "data"))
    return {"dataRoot": data_root, "databases": entries}
