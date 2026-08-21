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
        with _conn() as con:
            total = con.execute("SELECT COALESCE(SUM(hits), 0) FROM llm_cache").fetchone()[0]
            rows = con.execute(
                "SELECT kind, COUNT(*), COALESCE(SUM(hits), 0) FROM llm_cache GROUP BY kind").fetchall()
    return {"hits_total": int(total),
            "by_kind": {k: {"entries": n, "hits": h} for k, n, h in rows}}
