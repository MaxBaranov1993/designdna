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
    _heal_legacy_registry(con)
    return con


def _heal_legacy_registry(con: sqlite3.Connection) -> None:
    """Легаси-реестр (до появления rev0-снапшотов в publish): опубликованная
    система с latest_revision=0 при существующих ревизиях >0. Такой записью
    picker пинует «v0», которого нет в revisions → resolve_ref падает
    «Ревизия …@0 не найдена» и роняет генерацию. Лечим на месте: latest
    становится MAX(published revision). Идемпотентно — на здоровых данных
    UPDATE не меняет ни одной строки."""
    broken = con.execute(
        "SELECT 1 FROM design_systems ds"
        " WHERE ds.latest_revision = 0 AND ds.status = 'published'"
        " AND EXISTS (SELECT 1 FROM design_system_revisions r"
        "             WHERE r.system_id = ds.system_id AND r.revision > 0)"
        " LIMIT 1").fetchone()
    if not broken:
        return
    con.execute(
        "UPDATE design_systems SET"
        " latest_revision = (SELECT MAX(r.revision) FROM design_system_revisions r"
        "   WHERE r.system_id = design_systems.system_id AND r.revision > 0)"
        " WHERE latest_revision = 0 AND status = 'published'")
    con.commit()


def _latest_published_revision(system_id: str) -> int:
    with _LOCK:
        with _conn() as con:
            row = con.execute(
                "SELECT MAX(revision) FROM design_system_revisions WHERE system_id=? AND revision>0",
                (system_id,)).fetchone()
    return int(row[0] or 0) if row else 0


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _source_url(document: dict) -> str | None:
    refs = document.get("sourceRefs") or []
    if refs and isinstance(refs[0], dict):
        url = refs[0].get("url")
        return str(url) if url else None
    return None


def save_draft(document: dict) -> dict:
    """Полный документ черновика пишется как revision 0 — переживает reload."""
    draft = dsdoc.migrate_draft(document)
    from .identity import ensure_identity
    ensure_identity(draft)
    draft["status"] = "draft"
    if int(draft.get("revision") or 0) > 0:
        # локальные правки после публикации остаются draft-снимком, номер published-ревизии не трогаем
        pass
    else:
        draft["revision"] = 0
    digest = dsdoc.content_hash(draft)
    draft["contentHash"] = digest
    with _LOCK:
        with _conn() as con:
            published = con.execute(
                "SELECT MAX(revision) FROM design_system_revisions WHERE system_id=? AND revision>0",
                (draft["id"],)).fetchone()
            latest_pub = int(published[0] or 0) if published else 0
            registry_status = "published" if latest_pub else "draft"
            registry_revision = latest_pub if latest_pub else 0
            con.execute(
                "INSERT OR REPLACE INTO design_systems (system_id, project_id, name, status, latest_revision, source_url, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (draft["id"], draft.get("projectId") or "default", draft["name"],
                 registry_status, registry_revision,
                 _source_url(draft), _now()))
            con.execute(
                "INSERT OR REPLACE INTO design_system_revisions (system_id, revision, content_hash, document, created_at)"
                " VALUES (?,?,?,?,?)",
                (draft["id"], 0, digest, json.dumps(draft, ensure_ascii=False), _now()))
    return {"systemId": draft["id"], "status": "draft", "document": draft}


def publish(document: dict) -> dict:
    """Валидация → immutable revision; идемпотентность по contentHash (§31)."""
    from .identity import ensure_identity
    prepared = dsdoc.prepare_for_publish(dsdoc.migrate_draft(document))
    ensure_identity(prepared)
    errors = dsdoc.validate_document(prepared)
    if errors:
        return {"ok": False, "errors": errors}
    digest = dsdoc.content_hash(prepared)
    with _LOCK:
        with _conn() as con:
            existing = con.execute(
                "SELECT revision, document FROM design_system_revisions"
                " WHERE system_id=? AND content_hash=? AND revision>0",
                (prepared["id"], digest)).fetchone()
            if existing:
                stored = json.loads(existing[1])
                return {"ok": True, "document": stored, "summary": dsdoc.summary(stored), "duplicate": True}
            row = con.execute(
                "SELECT MAX(revision) FROM design_system_revisions WHERE system_id=? AND revision>0",
                (prepared["id"],)).fetchone()
            latest = int(row[0] or 0) if row else 0
            hashes = [r[0] for r in con.execute(
                "SELECT content_hash FROM design_system_revisions WHERE system_id=? AND revision>0",
                (prepared["id"],)).fetchall()]
            published = dsdoc.next_revision(prepared, hashes, latest_revision=latest)
            published["contentHash"] = digest
            con.execute(
                "INSERT OR REPLACE INTO design_system_revisions (system_id, revision, content_hash, document, created_at)"
                " VALUES (?,?,?,?,?)",
                (published["id"], published["revision"], digest,
                 json.dumps(published, ensure_ascii=False), _now()))
            con.execute(
                "INSERT OR REPLACE INTO design_system_revisions (system_id, revision, content_hash, document, created_at)"
                " VALUES (?,?,?,?,?)",
                (published["id"], 0, digest, json.dumps({**published, "status": "published"}, ensure_ascii=False), _now()))
            if con.execute("SELECT 1 FROM design_systems WHERE system_id=?", (published["id"],)).fetchone() is None:
                con.execute(
                    "INSERT INTO design_systems (system_id, project_id, name, status, latest_revision, source_url, updated_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (published["id"], published.get("projectId") or "default", published["name"],
                     "published", published["revision"], _source_url(published), _now()))
            else:
                con.execute(
                    "UPDATE design_systems SET status='published', name=?, latest_revision=?, source_url=?, updated_at=? WHERE system_id=?",
                    (published["name"], published["revision"], _source_url(published), _now(), published["id"]))
            return {"ok": True, "document": published,
                    "summary": dsdoc.summary(published), "duplicate": False}


def restore_published(system_id: str, revision: int | None = None) -> dict:
    """Discard a post-publish draft by reloading an immutable published revision.

    Rewrites only revision 0 (working copy) so Cancel/Escape can restore
    status/revision/contentHash without save-draft demotion. Published
    revisions and the project default are left untouched.
    """
    with _LOCK:
        with _conn() as con:
            target = int(revision or 0)
            if target <= 0:
                row = con.execute(
                    "SELECT latest_revision, status FROM design_systems WHERE system_id=?",
                    (system_id,)).fetchone()
                if not row or str(row[1] or "") != "published" or int(row[0] or 0) <= 0:
                    raise ValueError("Нет опубликованной ревизии для восстановления")
                target = int(row[0])
            stored = con.execute(
                "SELECT document FROM design_system_revisions WHERE system_id=? AND revision=?",
                (system_id, target)).fetchone()
            if not stored:
                raise ValueError(f"Ревизия {system_id}@{target} не найдена")
            try:
                document = json.loads(stored[0])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Ревизия {system_id}@{target} повреждена") from exc
            from .identity import ensure_identity
            ensure_identity(document)
            if document.get("status") != "published" or int(document.get("revision") or 0) <= 0:
                raise ValueError("Восстановить можно только опубликованную ревизию")
            digest = str(document.get("contentHash") or dsdoc.content_hash(document))
            published_copy = {**document, "status": "published", "revision": int(document["revision"]),
                              "contentHash": digest}
            con.execute(
                "INSERT OR REPLACE INTO design_system_revisions"
                " (system_id, revision, content_hash, document, created_at) VALUES (?,?,?,?,?)",
                (system_id, 0, digest, json.dumps(published_copy, ensure_ascii=False), _now()))
            row = con.execute(
                "SELECT latest_revision FROM design_systems WHERE system_id=?", (system_id,)).fetchone()
            current_latest = int(row[0] or 0) if row else 0
            # Never rewind latest_revision: published history stays immutable.
            keep_latest = max(current_latest, int(document["revision"]))
            con.execute(
                "UPDATE design_systems SET status='published', name=?, latest_revision=?, source_url=?, updated_at=?"
                " WHERE system_id=?",
                (document.get("name"), keep_latest, _source_url(document), _now(), system_id))
            return {"ok": True, "document": published_copy, "summary": dsdoc.summary(published_copy)}


def get_revision(system_id: str, revision: int) -> dict | None:
    with _LOCK:
        with _conn() as con:
            row = con.execute(
                "SELECT document FROM design_system_revisions WHERE system_id=? AND revision=?",
                (system_id, int(revision))).fetchone()
    if not row:
        return None
    try:
        document = json.loads(row[0])
        if int(revision) == 0:
            document = dsdoc.migrate_draft(document)
        from .identity import ensure_identity
        return ensure_identity(document)
    except (TypeError, ValueError):
        return None


def resolve_ref(ref: dict) -> tuple[dict | None, str | None]:
    """Загрузка pinned revision + проверка contentHash (§16.2, §20)."""
    system_id = str(ref.get("systemId") or "")
    revision = int(ref.get("revision") or 0)
    document = get_revision(system_id, revision)
    exact = document is not None
    if not exact and revision <= 0:
        # Легаси-pin «v0» на систему без rev0-снапшота (реестр до миграции):
        # резолвим последнюю опубликованную ревизию, hash не сверяем — pin
        # указывал на другую логическую ревизию, ронять генерацию незачем.
        latest = _latest_published_revision(system_id)
        if latest > 0:
            document = get_revision(system_id, latest)
    if not document:
        return None, f"Ревизия {system_id}@{revision} не найдена"
    if exact:
        expected = str(ref.get("contentHash") or "")
        if expected and document.get("contentHash") and expected != document["contentHash"]:
            return None, "contentHash закреплённой ревизии не совпадает"
    return document, None


def list_systems(project_id: str = "default") -> list[dict]:
    """Список систем проекта. Ревизии подтягиваются одним JOIN — раньше на
    каждую систему открывалось отдельное соединение и парсился полный
    документ (N+1 на каждый чих UI)."""
    out = []
    with _LOCK:
        with _conn() as con:
            rows = con.execute(
                "SELECT ds.system_id, ds.name, ds.status, ds.latest_revision, ds.source_url, ds.updated_at, rev.document"
                " FROM design_systems ds"
                " LEFT JOIN design_system_revisions rev ON rev.system_id = ds.system_id AND rev.revision = ds.latest_revision"
                " WHERE ds.project_id=? ORDER BY ds.updated_at DESC", (project_id,)).fetchall()
    for system_id, name, status, revision, source_url, updated_at, document_json in rows:
        entry = {"systemId": system_id, "name": name, "status": status,
                 "revision": revision, "sourceUrl": source_url, "updatedAt": updated_at}
        if isinstance(document_json, str) and document_json:
            try:
                document = json.loads(document_json)
            except (TypeError, ValueError):
                document = None
            if isinstance(document, dict):
                entry.update({k: v for k, v in dsdoc.summary(document).items()
                              if k in ("components", "suggestions", "verifiedMasters", "variants", "stateCoverage", "qualityScore", "origins", "contentHash",
                                       "identityStatus", "identitySignatures", "identityTests", "reconstructionStatus")})
        out.append(entry)
    return out


def set_default(system_id: str | None, project_id: str = "default") -> dict:
    with _LOCK:
        with _conn() as con:
            if system_id is None:
                con.execute(
                    "INSERT OR REPLACE INTO design_system_meta (project_id, default_system_id, default_revision) VALUES (?,?,?)",
                    (project_id, None, None))
                con.execute(
                    "UPDATE design_system_meta SET default_system_id=NULL, default_revision=NULL WHERE project_id=?",
                    (project_id,))
                return {"defaultSystemRef": None}
            row = con.execute(
                "SELECT latest_revision, status FROM design_systems WHERE system_id=? AND project_id=?",
                (system_id, project_id)).fetchone()
            if not row:
                raise ValueError(f"Система {system_id} не найдена в проекте")
            revision, status = int(row[0] or 0), str(row[1] or "")
            if status != "published" or revision <= 0:
                raise ValueError("Назначить по умолчанию можно только опубликованную систему")
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
    system_id = str(row[0])
    revision = int(row[1] or 0)
    if revision <= 0:
        # Легаси-запись default-референса на «v0»: берём актуальную
        # опубликованную ревизию (реестр уже подлечен _heal_legacy_registry).
        revision = _latest_published_revision(system_id)
    document = get_revision(system_id, revision) if revision else None
    return {
        "systemId": system_id,
        "revision": revision,
        "contentHash": (document or {}).get("contentHash") or "",
    }
