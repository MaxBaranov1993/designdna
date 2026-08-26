"""Focused tests for the bounded SQLite cache_store.

Запуск: .venv/Scripts/python -m pytest app/cache_store_test.py -q
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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


def _payload_size(payload: dict) -> int:
    return len(cache_store._canonical_bytes(payload))


def test_invalid_env_falls_back_to_documented_defaults(monkeypatch):
    monkeypatch.setenv("DESIGNDNA_CACHE_TTL_SECONDS", "nope")
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", "-4")
    monkeypatch.setenv("DESIGNDNA_CACHE_BUSY_TIMEOUT_MS", "0")
    assert cache_store.ttl_seconds() == cache_store.DEFAULT_TTL_SECONDS
    assert cache_store.max_bytes() == cache_store.DEFAULT_MAX_BYTES
    assert cache_store.busy_timeout_ms() == cache_store.DEFAULT_BUSY_TIMEOUT_MS


def test_legacy_migration_transactional_unicode_round_trip(db, monkeypatch):
    created = cache_store._now_iso()
    raw = json.dumps({"ёлка": "снег", "n": 1}, ensure_ascii=False)
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE llm_cache ("
        " kind TEXT, key TEXT, payload TEXT, created_at TEXT, hits INTEGER DEFAULT 0,"
        " PRIMARY KEY (kind, key))")
    con.execute(
        "INSERT INTO llm_cache (kind, key, payload, created_at, hits) VALUES (?,?,?,?,?)",
        ("unit", "legacy", raw, created, 3))
    con.commit()
    con.close()

    got = cache_store.get("unit", "legacy")
    assert got == {"ёлка": "снег", "n": 1}
    again = cache_store.get("unit", "legacy")
    assert again == got

    with sqlite3.connect(str(db)) as con:
        journal = str(con.execute("PRAGMA journal_mode").fetchone()[0] or "").lower()
        user_version = int(con.execute("PRAGMA user_version").fetchone()[0])
        row = con.execute(
            "SELECT payload, hits, integrity, byte_size, accessed_at FROM llm_cache "
            "WHERE kind=? AND key=?",
            ("unit", "legacy")).fetchone()
    assert user_version == cache_store.SCHEMA_VERSION
    assert journal == "wal"
    blob = cache_store._canonical_bytes(got)
    assert row[0] == blob.decode("utf-8")
    assert row[1] == 5  # migrated 3 + two gets
    assert row[2] == cache_store._integrity_of(blob)
    assert row[3] == len(blob)
    assert row[4]


def test_migration_failure_rolls_back_and_closes_connection(db, monkeypatch):
    created = cache_store._now_iso()
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE llm_cache ("
        " kind TEXT, key TEXT, payload TEXT, created_at TEXT, hits INTEGER DEFAULT 0,"
        " PRIMARY KEY (kind, key))")
    con.execute(
        "INSERT INTO llm_cache (kind, key, payload, created_at, hits) VALUES (?,?,?,?,?)",
        ("unit", "a", '{"a":1}', created, 0))
    con.execute(
        "INSERT INTO llm_cache (kind, key, payload, created_at, hits) VALUES (?,?,?,?,?)",
        ("unit", "b", '{"b":2}', created, 0))
    con.commit()
    con.close()

    original = cache_store._canonical_bytes
    calls = {"n": 0}

    def boom(payload):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("canonical fail")
        return original(payload)

    monkeypatch.setattr(cache_store, "_canonical_bytes", boom)
    with pytest.raises(RuntimeError, match="canonical fail"):
        cache_store.get("unit", "a")

    with sqlite3.connect(str(db)) as probe:
        user_version = int(probe.execute("PRAGMA user_version").fetchone()[0])
        rows = probe.execute("SELECT key, payload FROM llm_cache ORDER BY key").fetchall()
        busy = probe.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
    assert user_version == 0
    assert rows == [("a", '{"a":1}'), ("b", '{"b":2}')]
    assert busy == 2

    monkeypatch.setattr(cache_store, "_canonical_bytes", original)
    assert cache_store.get("unit", "a") == {"a": 1}
    assert cache_store.get("unit", "b") == {"b": 2}


def test_unicode_round_trip_and_key_helpers(db):
    payload = {"a": 1, "текст": "привет", "nested": {"ж": ["я"]}}
    cache_store.put("unit", "k1", payload)
    got = cache_store.get("unit", "k1")
    assert got == payload
    assert cache_store.get("unit", "nope") is None
    assert (cache_store.key_url("https://Example.com/X/")
            == cache_store.key_url("https://example.com/x"))
    assert cache_store.key_image("data:image/png;base64,AA") == cache_store.key_image(
        "data:image/png;base64,AA")


def test_corrupt_payload_and_hash_mismatch_fail_closed(db):
    cache_store.put("unit", "good", {"ok": True})
    cache_store.put("unit", "bad-json", {"ok": True})
    cache_store.put("unit", "bad-hash", {"ok": True})
    cache_store.put("unit", "bad-size", {"ok": True})
    with sqlite3.connect(str(db)) as con:
        con.execute("UPDATE llm_cache SET payload=? WHERE key=?", ("{not-json", "bad-json"))
        con.execute("UPDATE llm_cache SET integrity=? WHERE key=?", ("0" * 64, "bad-hash"))
        con.execute("UPDATE llm_cache SET byte_size=? WHERE key=?", (1, "bad-size"))
        con.commit()
    assert cache_store.get("unit", "bad-json") is None
    assert cache_store.get("unit", "bad-hash") is None
    assert cache_store.get("unit", "bad-size") is None
    assert cache_store.get("unit", "good") == {"ok": True}
    info = cache_store.stats()
    assert info["evicted_integrity"] >= 3
    assert cache_store.get("unit", "bad-json") is None


def test_ttl_expiry_fail_closed(db, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_CACHE_TTL_SECONDS", "10")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = {"now": t0}

    def fake_now():
        return clock["now"]

    monkeypatch.setattr(cache_store, "_now", fake_now)
    cache_store.put("unit", "fresh", {"v": 1})
    assert cache_store.get("unit", "fresh") == {"v": 1}
    clock["now"] = t0 + timedelta(seconds=11)
    assert cache_store.get("unit", "fresh") is None
    assert cache_store.stats()["evicted_expired"] >= 1


def test_byte_budget_lru_evicts_oldest_access(db, monkeypatch):
    a = {"name": "alpha", "blob": "A" * 80}
    b = {"name": "bravo", "blob": "B" * 80}
    c = {"name": "charlie", "blob": "C" * 80}
    # room for two items, not three
    budget = _payload_size(a) + _payload_size(b) + 8
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", str(budget))
    cache_store.put("unit", "a", a)
    cache_store.put("unit", "b", b)
    assert cache_store.get("unit", "a") == a  # a is more recently used than b
    cache_store.put("unit", "c", c)
    assert cache_store.get("unit", "b") is None
    assert cache_store.get("unit", "a") == a
    assert cache_store.get("unit", "c") == c
    info = cache_store.stats()
    assert info["evicted_lru"] >= 1
    assert info["bytes_total"] <= budget
    assert info["entries_total"] == 2


def test_oversized_entry_is_not_cached(db, monkeypatch):
    payload = {"blob": "X" * 200}
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", "40")
    cache_store.put("unit", "huge", payload)
    assert cache_store.get("unit", "huge") is None
    cache_store.put("unit", "tiny", {"n": 1})
    assert cache_store.get("unit", "tiny") == {"n": 1}


def test_oversized_replacement_removes_stale_row(db, monkeypatch):
    """put(kind,key,oversized) must not leave the previous small payload."""
    budget = 80
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", str(budget))
    small = {"n": 1}
    other = {"keep": True}
    huge = {"blob": "X" * 200}
    assert _payload_size(huge) > budget
    assert _payload_size(small) <= budget
    assert _payload_size(other) <= budget
    cache_store.put("unit", "tiny", small)
    cache_store.put("unit", "other", other)
    assert cache_store.get("unit", "tiny") == small
    cache_store.put("unit", "tiny", huge)
    assert cache_store.get("unit", "tiny") is None
    assert cache_store.get("unit", "other") == other
    info = cache_store.stats()
    assert info["bytes_total"] <= budget
    assert info["bytes_total"] == _payload_size(other)
    assert info["entries_total"] == 1


def test_stats_include_limits_and_counters(db, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", "100000")
    monkeypatch.setenv("DESIGNDNA_CACHE_TTL_SECONDS", "99")
    cache_store.put("alpha", "k", {"v": 1})
    cache_store.get("alpha", "k")
    cache_store.put("beta", "k", {"v": 2})
    info = cache_store.stats()
    assert info["hits_total"] == 1
    assert info["by_kind"]["alpha"]["entries"] == 1
    assert info["by_kind"]["alpha"]["hits"] == 1
    assert info["entries_total"] == 2
    assert info["bytes_total"] == _payload_size({"v": 1}) + _payload_size({"v": 2})
    assert info["max_bytes"] == 100000
    assert info["ttl_seconds"] == 99
    assert info["busy_timeout_ms"] == cache_store.DEFAULT_BUSY_TIMEOUT_MS
    assert "evicted_expired" in info
    assert "evicted_integrity" in info
    assert "evicted_lru" in info


def test_concurrent_readers_and_writers(db, monkeypatch):
    monkeypatch.setenv("DESIGNDNA_CACHE_MAX_BYTES", str(256 * 1024))
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            kind = "unit"
            key = f"k{index % 8}"
            cache_store.put(kind, key, {"i": index, "текст": "поток"})
            got = cache_store.get(kind, key)
            assert got is None or got.get("текст") == "поток"
            cache_store.stats()
        except BaseException as exc:  # noqa: BLE001 — collect for the parent thread
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(48)))
    assert errors == []
    info = cache_store.stats()
    assert info["entries_total"] <= 8
    assert info["bytes_total"] <= 256 * 1024
    leftover = threading.enumerate()
    assert all("worker" not in t.name.lower() or not t.is_alive() for t in leftover)
