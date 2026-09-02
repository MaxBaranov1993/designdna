"""cache_store после рефакторинга (план 2.7): соединение на поток, миграция
один раз, чтения без глобального lock, один хэш payload на get.

Запуск: .venv/Scripts/python -m pytest app/cache_store_perf_test.py -q
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import cache_store  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "cache.db"
    monkeypatch.setattr(cache_store, "DB_PATH", path)
    monkeypatch.delenv("DESIGNDNA_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("DESIGNDNA_CACHE_MAX_BYTES", raising=False)
    monkeypatch.delenv("DESIGNDNA_CACHE_BUSY_TIMEOUT_MS", raising=False)
    return path


@pytest.fixture()
def connect_counter(monkeypatch):
    """Считает sqlite3.connect, не ломая делегирование (тесты тоже открывают БД)."""
    original = sqlite3.connect
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(cache_store.sqlite3, "connect", counting)
    return calls


def test_hit_miss_after_refactor(db):
    assert cache_store.get("unit", "k") is None
    cache_store.put("unit", "k", {"v": 1, "текст": "да"})
    assert cache_store.get("unit", "k") == {"v": 1, "текст": "да"}
    assert cache_store.get("unit", "other") is None
    cache_store.put("unit", "k", {"v": 2})
    assert cache_store.get("unit", "k") == {"v": 2}
    info = cache_store.stats()
    assert info["hits_total"] == 1  # hits обнуляются при перезаписи
    assert info["entries_total"] == 1


def test_disk_format_unchanged(db):
    """Существующий кэш на диске остаётся читаемым: та же таблица и колонки."""
    cache_store.put("unit", "k", {"a": 1})
    with sqlite3.connect(str(db)) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(llm_cache)")}
        row = con.execute(
            "SELECT payload, integrity, byte_size FROM llm_cache WHERE kind=? AND key=?",
            ("unit", "k")).fetchone()
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
    assert {"kind", "key", "payload", "created_at", "hits",
            "accessed_at", "integrity", "byte_size"} <= cols
    blob = cache_store._canonical_bytes({"a": 1})
    assert row == (blob.decode("utf-8"), cache_store._integrity_of(blob), len(blob))
    assert version == cache_store.SCHEMA_VERSION


def test_repeated_reads_reuse_thread_connection(db, connect_counter):
    cache_store.put("unit", "k", {"v": 1})
    assert connect_counter["n"] == 1
    for _ in range(5):
        assert cache_store.get("unit", "k") == {"v": 1}
        cache_store.stats()
        assert cache_store.get("unit", "miss") is None
    cache_store.put("unit", "k2", {"v": 2})
    assert connect_counter["n"] == 1  # одно соединение на поток, без переоткрытия

    # другой поток — своё соединение, ровно одно
    def other() -> dict | None:
        cache_store.get("unit", "k")
        return cache_store.get("unit", "k")

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(other).result() == {"v": 1}
    assert connect_counter["n"] == 2


def test_migration_runs_once_per_process(db, monkeypatch):
    calls = {"n": 0}
    original = cache_store._migrate

    def counting(con):
        calls["n"] += 1
        return original(con)

    monkeypatch.setattr(cache_store, "_migrate", counting)
    cache_store.put("unit", "k", {"v": 1})
    for _ in range(10):
        cache_store.get("unit", "k")
        cache_store.stats()
    assert calls["n"] == 1

    # новый поток открывает своё соединение, но миграцию не повторяет
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda i: cache_store.get("unit", "k"), range(4)))
    assert calls["n"] == 1


def test_switching_db_path_reopens_and_remigrates(tmp_path, monkeypatch, connect_counter):
    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "a.db")
    cache_store.put("unit", "k", {"v": "a"})
    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "b.db")
    assert cache_store.get("unit", "k") is None
    cache_store.put("unit", "k", {"v": "b"})
    monkeypatch.setattr(cache_store, "DB_PATH", tmp_path / "a.db")
    assert cache_store.get("unit", "k") == {"v": "a"}
    assert connect_counter["n"] == 3


def test_get_hashes_payload_once(db, monkeypatch):
    cache_store.put("unit", "k", {"v": 1, "blob": "x" * 1000})
    calls = {"n": 0}
    original = cache_store._integrity_of

    def counting(blob):
        calls["n"] += 1
        return original(blob)

    monkeypatch.setattr(cache_store, "_integrity_of", counting)
    assert cache_store.get("unit", "k") == {"v": 1, "blob": "x" * 1000}
    assert calls["n"] == 1


def test_eight_threads_fifty_ops_no_exceptions(db, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", str(512 * 1024))
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker(tid: int) -> None:
        try:
            barrier.wait(timeout=10)  # стартуем одновременно — гонки реальны
            for i in range(50):
                key = f"k{(tid * 7 + i) % 16}"
                if i % 3 == 0:
                    cache_store.put("unit", key, {"tid": tid, "i": i, "текст": "поток"})
                else:
                    got = cache_store.get("unit", key)
                    assert got is None or got.get("текст") == "поток"
                if i % 10 == 0:
                    cache_store.stats()
        except BaseException as exc:  # noqa: BLE001 — собираем для родителя
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    assert errors == []
    info = cache_store.stats()
    assert info["entries_total"] <= 16
    assert info["evicted_integrity"] == 0


def test_concurrent_reads_do_not_take_global_lock(db):
    """Чтение не должно ждать глобальный lock: держим его и читаем из потока."""
    cache_store.put("unit", "k", {"v": 1})

    def reader():
        with cache_store._read() as con:
            return con.execute(
                "SELECT payload FROM llm_cache WHERE kind=? AND key=?", ("unit", "k")).fetchone()

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(reader).result(timeout=5)  # прогрев: соединение потока открыто
        with cache_store._lock:
            fut = pool.submit(reader)
            try:
                row = fut.result(timeout=3)
            except TimeoutError:
                pytest.fail("чтение заблокировалось на глобальном lock")
    assert row is not None


def test_stale_drop_does_not_delete_concurrent_replacement(db, monkeypatch):
    """Негодная строка удаляется только той версии, что прочитана."""
    cache_store.put("unit", "k", {"v": 1})
    with sqlite3.connect(str(db)) as con:
        con.execute("UPDATE llm_cache SET integrity=? WHERE key=?", ("0" * 64, "k"))
        con.commit()
    original_validate = cache_store._validate_row

    def replace_then_validate(row):
        # между чтением и удалением другой поток положил свежую запись
        monkeypatch.setattr(cache_store, "_validate_row", original_validate)
        cache_store.put("unit", "k", {"v": 2})
        return original_validate(row)

    monkeypatch.setattr(cache_store, "_validate_row", replace_then_validate)
    assert cache_store.get("unit", "k") is None
    assert cache_store.get("unit", "k") == {"v": 2}
    assert cache_store.stats()["evicted_integrity"] == 0
