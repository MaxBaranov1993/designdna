"""Persistent project and taste memory store for the local DesignAI dev app."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ir

ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent)
DATA_ROOT = Path(os.environ.get("DESIGNDNA_DATA_DIR") or ROOT / "data")
DB_PATH = DATA_ROOT / "projects.db"
DEFAULT_USER_ID = "local-user"
DEFAULT_PROJECT_ID = "default"

_lock = threading.Lock()

BUSY_TIMEOUT_MS = 5_000
EMPTY_RAW = "{}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def revision_of_raw(text: str) -> str:
    """SHA-256 of the exact UTF-8 JSON text stored in sqlite."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stored_text(payload: dict[str, Any]) -> str:
    """JSON text actually written to sqlite (and hashed for revision / dryRun).

    Python default separators and insertion-order keys; not migrated, not sorted.
    """
    return json.dumps(payload, ensure_ascii=False)


def payload_revision(payload: dict[str, Any] | None) -> str:
    """Revision a put would assign if this object were stored as-is."""
    body = payload if isinstance(payload, dict) else {}
    return revision_of_raw(stored_text(body))


EMPTY_REVISION = revision_of_raw(EMPTY_RAW)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(
        str(DB_PATH), timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_MS)}")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS projects ("
        "user_id TEXT NOT NULL, project_id TEXT NOT NULL, payload TEXT NOT NULL, "
        "version TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY (user_id, project_id))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS taste_profiles ("
        "user_id TEXT NOT NULL, project_id TEXT NOT NULL, profile TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, "
        "PRIMARY KEY (user_id, project_id))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS taste_events ("
        "user_id TEXT NOT NULL, project_id TEXT NOT NULL, event_hash TEXT NOT NULL, "
        "kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, "
        "PRIMARY KEY (user_id, project_id, event_hash))"
    )
    return con


@contextmanager
def _tx(immediate: bool = False):
    """One connection, one transaction. BEGIN IMMEDIATE for cross-process writers."""
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield con
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        con.close()


@contextmanager
def _db():
    with _tx(immediate=False) as con:
        yield con


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _strings(values: list[Any], limit: int = 12) -> list[str]:
    out: list[str] = []
    for value in values:
        if not isinstance(value, (str, int, float)):
            continue
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _collect_node_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for page in payload.get("pages") or []:
        graph = page.get("graph") if isinstance(page, dict) else None
        for node in (graph or {}).get("nodes") or []:
            if isinstance(node, dict):
                data = node.get("data")
                if isinstance(data, dict):
                    nodes.append({"type": node.get("type"), "data": data})
    return nodes


def build_taste_profile(payload: dict[str, Any]) -> dict[str, Any]:
    prompts: list[str] = []
    colors: list[Any] = []
    fonts: list[Any] = []
    radii: list[Any] = []
    style_tags: list[str] = []
    component_kinds: Counter[str] = Counter()

    for node in _collect_node_data(payload):
        data = node["data"]
        for key in ("text", "ownPrompt", "prompt", "brief"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                prompts.append(value.strip())
        tokens = data.get("tokens")
        if isinstance(tokens, dict):
            colors.extend(_walk_token_values(tokens, "color"))
            fonts.extend(_walk_token_values(tokens, "font"))
            radii.extend(_walk_token_values(tokens, "radius"))
        for key in ("ir",):
            ir = data.get(key)
            if isinstance(ir, dict):
                _sample_ir(ir, colors, fonts, radii, style_tags, component_kinds)
        for variant in data.get("variants") or []:
            if isinstance(variant, dict):
                _sample_ir(variant, colors, fonts, radii, style_tags, component_kinds)
        for block in data.get("blocks") or []:
            if isinstance(block, dict):
                kind = block.get("kind") or block.get("name")
                if isinstance(kind, str) and kind:
                    component_kinds[kind] += 1
                ir = block.get("ir")
                if isinstance(ir, dict):
                    _sample_ir(ir, colors, fonts, radii, style_tags, component_kinds)

    return {
        "version": "taste-profile-v2",
        "updated_at": _now(),
        "prompt_count": len(prompts),
        "recent_prompts": prompts[-8:],
        "style": {
            "colors": _strings(colors, 10),
            "fonts": _strings(fonts, 6),
            "radii": _strings(radii, 6),
            "tags": _strings(style_tags, 12),
        },
        "components": [name for name, _ in component_kinds.most_common(10)],
        "outcomes": {"accepted": 0, "rejected": 0, "promoted": 0},
        "accepted_rules": [],
        "rejected_rules": [],
    }


def _walk_token_values(tokens: dict[str, Any], needle: str) -> list[Any]:
    values: list[Any] = []
    for key, value in tokens.items():
        if needle in str(key).lower():
            if isinstance(value, dict):
                values.extend(value.values())
            elif isinstance(value, list):
                values.extend(value)
            else:
                values.append(value)
    return values


def _sample_ir(
    ir: dict[str, Any],
    colors: list[Any],
    fonts: list[Any],
    radii: list[Any],
    style_tags: list[str],
    component_kinds: Counter[str],
) -> None:
    meta = ir.get("meta")
    if isinstance(meta, dict):
        tags = meta.get("styleTags") or meta.get("style_tags") or meta.get("tags")
        if isinstance(tags, list):
            style_tags.extend(str(t) for t in tags if str(t).strip())
        kind = meta.get("kind") or meta.get("name")
        if isinstance(kind, str) and kind:
            component_kinds[kind] += 1
    tokens = ir.get("tokens")
    if isinstance(tokens, dict):
        colors.extend(_walk_token_values(tokens, "color"))
        fonts.extend(_walk_token_values(tokens, "font"))
        radii.extend(_walk_token_values(tokens, "radius"))
    for obj in _walk(ir.get("tree")):
        if isinstance(obj.get("type"), str):
            component_kinds[obj["type"]] += 1
        style = obj.get("style")
        if isinstance(style, dict):
            colors.extend([style.get("color"), style.get("background"), style.get("borderColor")])
            fonts.append(style.get("fontFamily"))
            radii.append(style.get("borderRadius"))


def _persist_on(
    con: sqlite3.Connection,
    payload: dict[str, Any],
    user_id: str,
    project_id: str,
    *,
    text: str | None = None,
) -> dict[str, Any]:
    store = text if text is not None else stored_text(payload)
    digest = revision_of_raw(store)
    size = len(store.encode("utf-8"))
    row = con.execute(
        "SELECT payload, updated_at FROM projects WHERE user_id=? AND project_id=?",
        (user_id, project_id),
    ).fetchone()
    if row and isinstance(row[0], str) and revision_of_raw(row[0]) == digest:
        return {"ok": True, "bytes": size, "updated_at": row[1], "unchanged": True,
                "revision": digest}
    profile = build_taste_profile(payload)
    existing_profile = con.execute(
        "SELECT profile FROM taste_profiles WHERE user_id=? AND project_id=?",
        (user_id, project_id),
    ).fetchone()
    if existing_profile:
        try:
            previous = json.loads(existing_profile[0])
        except (TypeError, ValueError):
            previous = {}
        for key in ("outcomes", "accepted_rules", "rejected_rules"):
            if key in previous:
                profile[key] = previous[key]
    now = _now()
    con.execute(
        "INSERT OR REPLACE INTO projects (user_id, project_id, payload, version, updated_at) VALUES (?,?,?,?,?)",
        (user_id, project_id, store, str(payload.get("version", "unknown")), now),
    )
    con.execute(
        "INSERT OR REPLACE INTO taste_profiles (user_id, project_id, profile, updated_at) VALUES (?,?,?,?)",
        (user_id, project_id, json.dumps(profile, ensure_ascii=False), now),
    )
    _record_prompt_events(con, payload, user_id, project_id)
    return {"ok": True, "bytes": size, "updated_at": now, "taste": profile, "revision": digest,
            "unchanged": False}


def save_project(payload: dict[str, Any], user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    with _lock:
        with _tx(immediate=True) as con:
            return _persist_on(con, payload, user_id, project_id)


def inspect_project(user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    """Read the stored row. revision is SHA-256 of the raw payload column."""
    with _lock:
        with _tx(immediate=False) as con:
            row = con.execute(
                "SELECT payload, updated_at FROM projects WHERE user_id=? AND project_id=?",
                (user_id, project_id),
            ).fetchone()
    if not row:
        return {"status": "missing", "payload": {}, "updated_at": "", "revision": EMPTY_REVISION}
    raw = row[0]
    if not isinstance(raw, str):
        return {"status": "corrupt", "payload": None, "updated_at": row[1], "revision": None,
                "errors": ["stored project is corrupt"]}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"status": "corrupt", "payload": None, "updated_at": row[1], "revision": None,
                "errors": ["stored project is corrupt"]}
    if not isinstance(parsed, dict):
        return {"status": "corrupt", "payload": None, "updated_at": row[1], "revision": None,
                "errors": ["stored project is corrupt"]}
    migrated = ir.migrate_project_payload(parsed)
    return {
        "status": "ok",
        "payload": migrated,
        "updated_at": row[1],
        "revision": revision_of_raw(raw),
    }


def commit_project(
    payload: dict[str, Any],
    expected_revision: str,
    *,
    dry_run: bool = False,
    user_id: str = DEFAULT_USER_ID,
    project_id: str = DEFAULT_PROJECT_ID,
) -> dict[str, Any]:
    """Cross-process compare-and-swap on one BEGIN IMMEDIATE connection.

    expected_revision is SHA-256 of the exact raw stored JSON (get.revision).
    dryRun returns the revision that would be stored for this payload text
    (json.dumps(..., ensure_ascii=False)) without writing.
    """
    if not isinstance(payload, dict):
        return {"ok": False, "stale": False, "errors": ["(root): project must be an object"]}
    expected = str(expected_revision or "")
    store = stored_text(payload)
    predicted = revision_of_raw(store)
    with _lock:
        with _tx(immediate=True) as con:
            row = con.execute(
                "SELECT payload, updated_at FROM projects WHERE user_id=? AND project_id=?",
                (user_id, project_id),
            ).fetchone()
            if not row:
                current_rev = EMPTY_REVISION
                updated_at = ""
            else:
                raw = row[0]
                if not isinstance(raw, str):
                    return {"ok": False, "stale": False, "corrupt": True,
                            "errors": ["stored project is corrupt"]}
                try:
                    parsed = json.loads(raw)
                except (TypeError, ValueError):
                    return {"ok": False, "stale": False, "corrupt": True,
                            "errors": ["stored project is corrupt"]}
                if not isinstance(parsed, dict):
                    return {"ok": False, "stale": False, "corrupt": True,
                            "errors": ["stored project is corrupt"]}
                current_rev = revision_of_raw(raw)
                updated_at = row[1]
            if expected != current_rev:
                return {
                    "ok": False,
                    "stale": True,
                    "revision": current_rev,
                    "updated_at": updated_at,
                    "dryRun": bool(dry_run),
                }
            if dry_run:
                return {
                    "ok": True,
                    "stale": False,
                    "dryRun": True,
                    "revision": predicted,
                    "updated_at": updated_at,
                }
            result = _persist_on(con, payload, user_id, project_id, text=store)
            return {
                "ok": True,
                "stale": False,
                "dryRun": False,
                "revision": result["revision"],
                "updated_at": result["updated_at"],
                "unchanged": bool(result.get("unchanged")),
            }


def _record_prompt_events(con: sqlite3.Connection, payload: dict[str, Any], user_id: str, project_id: str) -> None:
    created_at = _now()
    rows: dict[str, tuple[str, str, str, str, str, str]] = {}
    for node in _collect_node_data(payload):
        data = node["data"]
        for key in ("text", "ownPrompt", "prompt", "brief"):
            value = data.get(key)
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text:
                continue
            body = {"nodeType": node.get("type"), "field": key, "text": text}
            body_text = json.dumps(body, ensure_ascii=False, sort_keys=True)
            digest = revision_of_raw(body_text)
            if digest not in rows:
                rows[digest] = (user_id, project_id, digest, "prompt", body_text, created_at)
    if rows:
        con.executemany(
            "INSERT OR IGNORE INTO taste_events (user_id, project_id, event_hash, kind, payload, created_at) "
            "VALUES (?,?,?,?,?,?)",
            rows.values(),
        )


def load_project(user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any] | None:
    record = inspect_project(user_id, project_id)
    if record.get("status") != "ok":
        return None
    return {"payload": record["payload"], "updated_at": record["updated_at"]}


def load_taste_profile(user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    with _lock:
        with _db() as con:
            row = con.execute(
                "SELECT profile FROM taste_profiles WHERE user_id=? AND project_id=?",
                (user_id, project_id),
            ).fetchone()
    if not row:
        return {"version": "taste-profile-v2", "prompt_count": 0, "recent_prompts": [], "style": {}, "components": [], "outcomes": {"accepted": 0, "rejected": 0, "promoted": 0}}
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return {"version": "taste-profile-v2", "prompt_count": 0, "recent_prompts": [], "style": {}, "components": [], "outcomes": {"accepted": 0, "rejected": 0, "promoted": 0}}


def record_taste_outcome(kind: str, payload: dict[str, Any], user_id: str = DEFAULT_USER_ID,
                         project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    """Record an explicit decision, never raw prompts or reference assets."""
    if kind not in ("accepted", "rejected", "promoted"):
        raise ValueError("Taste outcome must be accepted, rejected or promoted")
    safe = {
        "systemId": str(payload.get("systemId") or "")[:120],
        "compiledContextHash": str(payload.get("compiledContextHash") or "")[:100],
        "archetypeId": str(payload.get("archetypeId") or "")[:120],
        "ruleIds": [str(value)[:160] for value in (payload.get("ruleIds") or [])[:20]],
        "style": {
            key: [str(value)[:80] for value in values[:12]]
            for key, values in (payload.get("style") or {}).items()
            if key in ("colors", "fonts", "radii", "tags") and isinstance(values, list)
        },
    }
    body = {"kind": kind, **safe}
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    with _lock:
        with _tx(immediate=True) as con:
            con.execute(
                "INSERT OR IGNORE INTO taste_events (user_id, project_id, event_hash, kind, payload, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, project_id, digest, kind, json.dumps(safe, ensure_ascii=False), _now()),
            )
            row = con.execute("SELECT profile FROM taste_profiles WHERE user_id=? AND project_id=?", (user_id, project_id)).fetchone()
            try:
                profile = json.loads(row[0]) if row else {}
            except (TypeError, ValueError):
                profile = {}
            profile.setdefault("version", "taste-profile-v2")
            profile["version"] = "taste-profile-v2"
            outcomes = profile.setdefault("outcomes", {"accepted": 0, "rejected": 0, "promoted": 0})
            outcomes[kind] = int(outcomes.get(kind) or 0) + 1
            target = "rejected_rules" if kind == "rejected" else "accepted_rules"
            profile[target] = list(dict.fromkeys((profile.get(target) or []) + safe["ruleIds"]))[-30:]
            if kind in ("accepted", "promoted"):
                style = profile.setdefault("style", {})
                for key, values in safe["style"].items():
                    style[key] = list(dict.fromkeys((style.get(key) or []) + values))[-12:]
            profile["updated_at"] = _now()
            con.execute(
                "INSERT OR REPLACE INTO taste_profiles (user_id, project_id, profile, updated_at) VALUES (?,?,?,?)",
                (user_id, project_id, json.dumps(profile, ensure_ascii=False), profile["updated_at"]),
            )
    return {"ok": True, "profile": profile, "eventHash": digest}


def build_prompt_memory_hint(user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> str:
    profile = load_taste_profile(user_id, project_id)
    if not profile.get("prompt_count"):
        return ""
    style = profile.get("style") if isinstance(profile.get("style"), dict) else {}
    lines = [
        "## Project Taste Memory",
        "Use this as soft guidance, not as a hard override. Keep the user's explicit request first.",
    ]
    prompts = profile.get("recent_prompts") or []
    if prompts:
        lines.append("Recent user directions: " + " | ".join(str(p)[:140] for p in prompts[-5:]))
    for label, key in (("Preferred colors", "colors"), ("Preferred fonts", "fonts"), ("Preferred radius", "radii"), ("Style tags", "tags")):
        vals = style.get(key) if isinstance(style, dict) else None
        if vals:
            lines.append(f"{label}: " + ", ".join(str(v) for v in vals[:8]))
    components = profile.get("components") or []
    if components:
        lines.append("Repeated component patterns: " + ", ".join(str(v) for v in components[:8]))
    accepted = profile.get("accepted_rules") or []
    rejected = profile.get("rejected_rules") or []
    if accepted:
        lines.append("Accepted identity rules: " + ", ".join(str(v) for v in accepted[:12]))
    if rejected:
        lines.append("Avoid previously rejected identity rules: " + ", ".join(str(v) for v in rejected[:12]))
    return "\n".join(lines)
