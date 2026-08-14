"""Кэш результатов reproduce/clone (sqlite, stdlib).

Повторный запрос того же сайта/скриншота отдаётся из базы без траты токенов:
владелец площадки платит за обработку один раз, дальше — из имеющихся сессий.
"""
import hashlib
import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")
DB_PATH = DATA_ROOT / "cache.db"

_lock = threading.Lock()


def _log(msg: str) -> None:
    print(f"[cache_store] {msg}", file=sys.stderr)


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache ("
        " kind TEXT, key TEXT, payload TEXT, created_at TEXT, hits INTEGER DEFAULT 0,"
        " PRIMARY KEY (kind, key))")
    cols = [r[1] for r in con.execute("PRAGMA table_info(llm_cache)")]
    if "hits" not in cols:  # миграция старых баз; не должна ронять горячий путь
        try:
            con.execute("ALTER TABLE llm_cache ADD COLUMN hits INTEGER DEFAULT 0")
        except sqlite3.Error as e:
            _log(f"миграция колонки hits не удалась: {e}")
    return con


def key_image(image_data_url: str) -> str:
    return hashlib.sha256(image_data_url.encode("utf-8")).hexdigest()


def key_url(url: str) -> str:
    return hashlib.sha256(url.strip().lower().rstrip("/").encode("utf-8")).hexdigest()


def get(kind: str, key: str) -> dict | None:
    with _lock:
        with _conn() as con:
            row = con.execute(
                "SELECT payload FROM llm_cache WHERE kind=? AND key=?", (kind, key)).fetchone()
            if row:
                try:
                    con.execute("UPDATE llm_cache SET hits = hits + 1 WHERE kind=? AND key=?",
                                (kind, key))
                    con.commit()  # счётчик фиксируем сразу, не по выходу из контекста
                except sqlite3.Error as e:
                    _log(f"UPDATE hits не удался ({kind}): {e}")  # метрика; отдача кэша важнее
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError) as e:
        _log(f"битый payload в кэше ({kind}) — cache miss: {e}")
        return None


def put(kind: str, key: str, payload: dict) -> None:
    with _lock:
        with _conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO llm_cache (kind, key, payload, created_at) VALUES (?,?,?,?)",
                (kind, key, json.dumps(payload, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat()))


def stats() -> dict:
    """Сколько запросов отдано из кэша (≈ сэкономленные LLM-вызовы)."""
    with _lock:
        with _conn() as con:
            total = con.execute("SELECT COALESCE(SUM(hits), 0) FROM llm_cache").fetchone()[0]
            rows = con.execute(
                "SELECT kind, COUNT(*), COALESCE(SUM(hits), 0) FROM llm_cache GROUP BY kind").fetchall()
    return {"hits_total": int(total),
            "by_kind": {k: {"entries": n, "hits": h} for k, n, h in rows}}
