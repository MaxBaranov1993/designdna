"""Хранение дизайн-систем: SQLite registry + immutable revisions (ТЗ §27, §14)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from . import document as dsdoc

# RLock обязателен: list_systems держит лок и зовёт get_revision,
# который берёт его повторно (обычный Lock здесь само-дедлочится)
_LOCK = threading.RLock()


def _db_path() -> Path:
    import os
    root = Path(os.environ.get("DESIGNDNA_DATA_DIR") or Path(__file__).resolve().parent.parent.parent / "data")
    return root / "design_systems.db"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS design_systems ("
        "system_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'draft', latest_revision INTEGER NOT NULL DEFAULT 0,"
        "source_url TEXT, updated_at TEXT NOT NULL)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS design_system_revisions ("
        "system_id TEXT NOT NULL, revision INTEGER NOT NULL, content_hash TEXT NOT NULL,"
        "document TEXT NOT NULL, created_at TEXT NOT NULL,"
        "PRIMARY KEY (system_id, revision))")
    con.execute(
        "CREATE TABLE IF NOT EXISTS design_system_meta ("
        "project_id TEXT PRIMARY KEY, default_system_id TEXT, default_revision INTEGER)")
    return con


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def save_draft(document: dict) -> dict:
    with _LOCK:
        with _conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO design_systems (system_id, project_id, name, status, latest_revision, source_url, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (document["id"], document.get("projectId") or "default", document["name"],
                 "draft", int(document.get("revision") or 0),
                 (document.get("sourceRefs") or [{}])[0].get("url") if document.get("sourceRefs") else None, _now()))
    return {"systemId": document["id"], "status": "draft"}


def publish(document: dict) -> dict:
    """Валидация → immutable revision; идемпотентность по contentHash (§31)."""
    errors = dsdoc.validate_document(document)
    if errors:
        return {"ok": False, "errors": errors}
    with _LOCK:
        with _conn() as con:
            existing = con.execute(
                "SELECT revision, document FROM design_system_revisions WHERE system_id=? AND content_hash=?",
                (document["id"], dsdoc.content_hash(document))).fetchone()
            if existing:
                # тот же контент уже опубликован — возвращаем существующую ревизию
                stored = json.loads(existing[1])
                return {"ok": True, "document": stored, "summary": dsdoc.summary(stored), "duplicate": True}
            hashes = [row[0] for row in con.execute(
                "SELECT content_hash FROM design_system_revisions WHERE system_id=?", (document["id"],)).fetchall()]
            published = dsdoc.next_revision(document, hashes)
            digest = published["contentHash"]
            if digest not in hashes:
                con.execute(
                    "INSERT OR REPLACE INTO design_system_revisions (system_id, revision, content_hash, document, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (published["id"], published["revision"], digest,
                     json.dumps(published, ensure_ascii=False), _now()))
            con.execute(
                "UPDATE design_systems SET status='published', latest_revision=?, updated_at=? WHERE system_id=?",
                (published["revision"], _now(), published["id"]))
            if con.execute("SELECT 1 FROM design_systems WHERE system_id=?", (published["id"],)).fetchone() is None:
                con.execute(
                    "INSERT INTO design_systems (system_id, project_id, name, status, latest_revision, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (published["id"], published.get("projectId") or "default", published["name"], "published", published["revision"], _now()))
            return {"ok": True, "document": published,
                    "summary": dsdoc.summary(published), "duplicate": digest in hashes}


def get_revision(system_id: str, revision: int) -> dict | None:
    with _LOCK:
        with _conn() as con:
            row = con.execute(
                "SELECT document FROM design_system_revisions WHERE system_id=? AND revision=?",
                (system_id, int(revision))).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def resolve_ref(ref: dict) -> tuple[dict | None, str | None]:
    """Загрузка pinned revision + проверка contentHash (§16.2, §20)."""
    system_id = str(ref.get("systemId") or "")
    revision = int(ref.get("revision") or 0)
    document = get_revision(system_id, revision)
    if not document:
        return None, f"Ревизия {system_id}@{revision} не найдена"
    expected = str(ref.get("contentHash") or "")
    if expected and document.get("contentHash") and expected != document["contentHash"]:
        return None, "contentHash закреплённой ревизии не совпадает"
    return document, None


def list_systems(project_id: str = "default") -> list[dict]:
    out = []
    with _LOCK:
        with _conn() as con:
            rows = con.execute(
                "SELECT system_id, name, status, latest_revision, source_url, updated_at"
                " FROM design_systems WHERE project_id=? ORDER BY updated_at DESC", (project_id,)).fetchall()
            for system_id, name, status, revision, source_url, updated_at in rows:
                document = get_revision(system_id, revision)
                entry = {"systemId": system_id, "name": name, "status": status,
                         "revision": revision, "sourceUrl": source_url, "updatedAt": updated_at}
                if document:
                    entry.update({k: v for k, v in dsdoc.summary(document).items()
                                  if k in ("components", "variants", "stateCoverage", "qualityScore", "origins")})
                out.append(entry)
    return out


def set_default(system_id: str | None, project_id: str = "default") -> dict:
    with _LOCK:
        with _conn() as con:
            if system_id is None:
                con.execute("UPDATE design_system_meta SET default_system_id=NULL, default_revision=NULL WHERE project_id=?", (project_id,))
                return {"defaultSystemRef": None}
            row = con.execute("SELECT latest_revision FROM design_systems WHERE system_id=? AND project_id=?",
                              (system_id, project_id)).fetchone()
            if not row:
                raise ValueError(f"Система {system_id} не найдена в проекте")
            revision = int(row[0])
            document = get_revision(system_id, revision)
            con.execute(
                "INSERT OR REPLACE INTO design_system_meta (project_id, default_system_id, default_revision) VALUES (?,?,?)",
                (project_id, system_id, revision))
            return {"defaultSystemRef": {"systemId": system_id, "revision": revision,
                                         "contentHash": (document or {}).get("contentHash") or ""}}


def get_default(project_id: str = "default") -> dict | None:
    with _LOCK:
        with _conn() as con:
            row = con.execute("SELECT default_system_id, default_revision FROM design_system_meta WHERE project_id=?",
                              (project_id,)).fetchone()
    if not row or not row[0]:
        return None
    return {"systemId": row[0], "revision": int(row[1] or 0)}
