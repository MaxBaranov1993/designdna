"""Кэш результатов reproduce/clone (sqlite, stdlib).

Повторный запрос того же сайта/скриншота отдаётся из базы без траты токенов:
владелец площадки платит за обработку один раз, дальше — из имеющихся сессий.

Bounded desktop-safe SQLite cache:
  - canonical UTF-8 JSON payload bytes + SHA-256 integrity + byte_size
  - created_at / accessed_at, TTL expiry, deterministic LRU under a byte budget
  - WAL + busy_timeout; old llm_cache rows migrate in one transaction

Env (invalid or out-of-range values fall back to the documented defaults):
  DESIGNDNA_CACHE_TTL_SECONDS      default 2592000 (30 days), allowed 1..315360000
  DESIGNDNA_CACHE_MAX_BYTES        default 536870912 (512 MiB), allowed 1..68719476736
  DESIGNDNA_CACHE_BUSY_TIMEOUT_MS  default 5000, allowed 1..60000
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")
DB_PATH = DATA_ROOT / "cache.db"

SCHEMA_VERSION = 2

DEFAULT_TTL_SECONDS = 2_592_000          # 30 days
DEFAULT_MAX_BYTES = 536_870_912          # 512 MiB
DEFAULT_BUSY_TIMEOUT_MS = 5_000

TTL_SECONDS_RANGE = (1, 315_360_000)     # 1s .. 10 years
MAX_BYTES_RANGE = (1, 68_719_476_736)    # 1 byte .. 64 GiB
BUSY_TIMEOUT_MS_RANGE = (1, 60_000)

_lock = threading.Lock()


def _log(msg: str) -> None:
    print(f"[cache_store] {msg}", file=sys.stderr)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _env_int(name: str, default: int, bounds: tuple[int, int]) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        _log(f"{name} invalid; using default {default}")
        return default
    low, high = bounds
    if value < low or value > high:
        _log(f"{name} out of range; using default {default}")
        return default
    return value


def ttl_seconds() -> int:
    return _env_int("DESIGNDNA_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS, TTL_SECONDS_RANGE)


def max_bytes() -> int:
    return _env_int("DESIGNDNA_CACHE_MAX_BYTES", DEFAULT_MAX_BYTES, MAX_BYTES_RANGE)


def busy_timeout_ms() -> int:
    return _env_int("DESIGNDNA_CACHE_BUSY_TIMEOUT_MS", DEFAULT_BUSY_TIMEOUT_MS, BUSY_TIMEOUT_MS_RANGE)


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _integrity_of(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _parse_ts(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _meta_get(con: sqlite3.Connection, key: str) -> int:
    row = con.execute("SELECT v FROM llm_cache_meta WHERE k=?", (key,)).fetchone()
    return int(row[0]) if row else 0


def _meta_add(con: sqlite3.Connection, key: str, delta: int = 1) -> None:
    con.execute(
        "INSERT INTO llm_cache_meta(k, v) VALUES(?, ?) "
        "ON CONFLICT(k) DO UPDATE SET v = llm_cache_meta.v + excluded.v",
        (key, int(delta)))


def _migrate(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache ("
        " kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,"
        " created_at TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (kind, key))")
    cols = {r[1] for r in con.execute("PRAGMA table_info(llm_cache)")}
    for name, decl in (
        ("hits", "INTEGER NOT NULL DEFAULT 0"),
        ("accessed_at", "TEXT NOT NULL DEFAULT ''"),
        ("integrity", "TEXT NOT NULL DEFAULT ''"),
        ("byte_size", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in cols:
            con.execute(f"ALTER TABLE llm_cache ADD COLUMN {name} {decl}")
    con.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache_meta ("
        " k TEXT PRIMARY KEY, v INTEGER NOT NULL)")
    version = int(con.execute("PRAGMA user_version").fetchone()[0] or 0)
    if version >= SCHEMA_VERSION:
        return
    rows = con.execute(
        "SELECT kind, key, payload, created_at, hits, accessed_at, integrity, byte_size "
        "FROM llm_cache").fetchall()
    for kind, key, payload, created_at, hits, accessed_at, integrity, byte_size in rows:
        try:
            loaded = json.loads(payload)
        except (ValueError, TypeError):
            con.execute("DELETE FROM llm_cache WHERE kind=? AND key=?", (kind, key))
            _meta_add(con, "evicted_integrity")
            continue
        if not isinstance(loaded, dict):
            con.execute("DELETE FROM llm_cache WHERE kind=? AND key=?", (kind, key))
            _meta_add(con, "evicted_integrity")
            continue
        blob = _canonical_bytes(loaded)
        text = blob.decode("utf-8")
        digest = _integrity_of(blob)
        accessed = accessed_at or created_at or _now_iso()
        con.execute(
            "UPDATE llm_cache SET payload=?, hits=?, accessed_at=?, integrity=?, byte_size=? "
            "WHERE kind=? AND key=?",
            (text, int(hits or 0), accessed, digest, len(blob), kind, key))
    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    timeout = max(busy_timeout_ms() / 1000.0, 0.001)
    con = sqlite3.connect(str(DB_PATH), timeout=timeout, isolation_level="DEFERRED")
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms())}")
        con.execute("PRAGMA synchronous=NORMAL")
        _migrate(con)
        return con
    except Exception:
        with contextlib.suppress(sqlite3.Error):
            con.rollback()
        con.close()
        raise


@contextmanager
def _session():
    con = _conn()
    try:
        with con:
            yield con
    finally:
        con.close()


def key_image(image_data_url: str) -> str:
    return hashlib.sha256(image_data_url.encode("utf-8")).hexdigest()


def key_url(url: str) -> str:
    return hashlib.sha256(url.strip().lower().rstrip("/").encode("utf-8")).hexdigest()


def _total_bytes(con: sqlite3.Connection) -> int:
    row = con.execute("SELECT COALESCE(SUM(byte_size), 0) FROM llm_cache").fetchone()
    return int(row[0] or 0)


def _evict_expired(con: sqlite3.Connection, now: datetime) -> int:
    cutoff = now - timedelta(seconds=ttl_seconds())
    rows = con.execute("SELECT kind, key, created_at FROM llm_cache").fetchall()
    # удаление — одним executemany: поштучные DELETE делали eviction
    # O(N) круглых путей SQLite на каждую запись кэша
    doomed: list[tuple[str, str]] = []
    for kind, key, created_at in rows:
        created = _parse_ts(created_at)
        if created is None or created <= cutoff:
            doomed.append((kind, key))
    if doomed:
        con.executemany("DELETE FROM llm_cache WHERE kind=? AND key=?", doomed)
        _meta_add(con, "evicted_expired", len(doomed))
    return len(doomed)


_LRU_BATCH = 256


def _evict_lru(con: sqlite3.Connection, keep_kind: str, keep_key: str, budget: int) -> int:
    removed = 0
    while True:
        over = _total_bytes(con) - budget
        if over <= 0:
            break
        rows = con.execute(
            "SELECT kind, key, byte_size FROM llm_cache "
            "WHERE NOT (kind=? AND key=?) "
            "ORDER BY accessed_at ASC, created_at ASC, kind ASC, key ASC "
            "LIMIT ?",
            (keep_kind, keep_key, _LRU_BATCH)).fetchall()
        if not rows:
            break
        # режем ровно до покрытия перерасхода: батч из O(k log N) запросов
        # схлопывается в сортировку + executemany
        doomed: list[tuple[str, str]] = []
        covered = 0
        for kind, key, size in rows:
            doomed.append((kind, key))
            covered += int(size or 0)
            if covered >= over:
                break
        con.executemany("DELETE FROM llm_cache WHERE kind=? AND key=?", doomed)
        removed += len(doomed)
        if covered < over and len(rows) < _LRU_BATCH:
            break  # кроме защищаемой записи удалять больше нечего
    if removed:
        _meta_add(con, "evicted_lru", removed)
    return removed


def get(kind: str, key: str) -> dict | None:
    with _lock:
        with _session() as con:
            row = con.execute(
                "SELECT payload, created_at, integrity, byte_size FROM llm_cache "
                "WHERE kind=? AND key=?",
                (kind, key)).fetchone()
            if not row:
                return None
            payload_text, created_at, integrity, byte_size = row

            def drop(counter: str) -> None:
                con.execute("DELETE FROM llm_cache WHERE kind=? AND key=?", (kind, key))
                _meta_add(con, counter)

            created = _parse_ts(created_at)
            if created is None or created <= _now() - timedelta(seconds=ttl_seconds()):
                drop("evicted_expired")
                return None
            if not isinstance(payload_text, str):
                drop("evicted_integrity")
                return None
            blob = payload_text.encode("utf-8")
            if int(byte_size or 0) != len(blob):
                drop("evicted_integrity")
                return None
            if str(integrity or "") != _integrity_of(blob):
                drop("evicted_integrity")
                return None
            try:
                loaded = json.loads(payload_text)
            except (ValueError, TypeError):
                drop("evicted_integrity")
                return None
            if not isinstance(loaded, dict):
                drop("evicted_integrity")
                return None
            replay = _canonical_bytes(loaded)
            if replay != blob or _integrity_of(replay) != integrity:
                drop("evicted_integrity")
                return None
            con.execute(
                "UPDATE llm_cache SET hits = hits + 1, accessed_at=? WHERE kind=? AND key=?",
                (_now_iso(), kind, key))
            return loaded


def put(kind: str, key: str, payload: dict) -> None:
    if not isinstance(payload, dict):
        _log(f"отказ записи ({kind}): payload is not an object")
        return
    blob = _canonical_bytes(payload)
    digest = _integrity_of(blob)
    size = len(blob)
    budget = max_bytes()
    with _lock:
        with _session() as con:
            if size > budget:
                # Do not cache oversized bytes; drop any stale row for this key
                # so a later get cannot return the previous payload.
                con.execute("DELETE FROM llm_cache WHERE kind=? AND key=?", (kind, key))
                _evict_expired(con, _now())
                return
            now = _now_iso()
            text = blob.decode("utf-8")
            con.execute(
                "INSERT OR REPLACE INTO llm_cache "
                "(kind, key, payload, created_at, accessed_at, hits, integrity, byte_size) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (kind, key, text, now, now, 0, digest, size))
            _evict_expired(con, _now())
            _evict_lru(con, kind, key, budget)
            remaining = con.execute(
                "SELECT byte_size FROM llm_cache WHERE kind=? AND key=?", (kind, key)).fetchone()
            if remaining and int(remaining[0]) > budget:
                con.execute("DELETE FROM llm_cache WHERE kind=? AND key=?", (kind, key))


def put_gated(kind: str, key: str, payload: dict, fidelity_report: dict | None = None) -> bool:
    """Fail-closed запись результатов Source Import.

    Кэш прогревается только когда fidelity report содержит все обязательные
    метрики и проходит gate (origin <= 2px, paint >= 95, similarity >= 85, без
    необъяснённых lost visuals). Флаг вызывающего кода (payload["rasterFallback"])
    обхода не даёт: проверяется фактический IR payload — запись без метрик
    разрешена только когда весь блок представлен исключительно явными locked
    raster fallback слоями (editable:false, sourceMeta.reason == raster-fallback).
    Флаг fidelity_report["raster_fallback"] обхода тоже не даёт: если отчёт
    заявляет raster fallback, а фактический payload["ir"] строгой проверки
    is_raster_fallback не проходит — запись отклоняется.
    Отказ ничего не пишет и возвращает False — вызывающий код всё равно отдаёт
    IR в ответе.
    """
    try:
        from fidelity_harness import evaluate_gate, is_raster_fallback
    except Exception as e:
        _log(f"отказ записи ({kind}): fidelity harness недоступен: {e}")
        return False
    ir = payload.get("ir") if isinstance(payload, dict) else None
    if is_raster_fallback(ir):
        put(kind, key, payload)
        return True
    if isinstance(fidelity_report, dict) and fidelity_report.get("raster_fallback"):
        _log(f"отказ записи ({kind}): report заявляет raster_fallback, "
             "но фактический IR строгой проверки не проходит")
        return False
    gate = evaluate_gate(fidelity_report)
    if not gate.get("passed"):
        _log(f"отказ записи ({kind}): fidelity gate не пройден: "
             + "; ".join(gate.get("reasons") or ["нет отчёта"]))
        return False
    put(kind, key, payload)
    return True


def stats() -> dict:
    """Сколько запросов отдано из кэша (≈ сэкономленные LLM-вызовы)."""
    with _lock:
        with _session() as con:
            total = con.execute("SELECT COALESCE(SUM(hits), 0) FROM llm_cache").fetchone()[0]
            rows = con.execute(
                "SELECT kind, COUNT(*), COALESCE(SUM(hits), 0), COALESCE(SUM(byte_size), 0) "
                "FROM llm_cache GROUP BY kind").fetchall()
            entries = con.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
            bytes_total = _total_bytes(con)
            evicted_expired = _meta_get(con, "evicted_expired")
            evicted_integrity = _meta_get(con, "evicted_integrity")
            evicted_lru = _meta_get(con, "evicted_lru")
    return {
        "hits_total": int(total or 0),
        "by_kind": {k: {"entries": n, "hits": h, "bytes": b} for k, n, h, b in rows},
        "entries_total": int(entries or 0),
        "bytes_total": int(bytes_total),
        "max_bytes": max_bytes(),
        "ttl_seconds": ttl_seconds(),
        "busy_timeout_ms": busy_timeout_ms(),
        "evicted_expired": int(evicted_expired),
        "evicted_integrity": int(evicted_integrity),
        "evicted_lru": int(evicted_lru),
    }
