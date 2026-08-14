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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
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
def _db():
    con = _conn()
    try:
        yield con
        con.commit()
    finally:
        con.close()


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
        "version": "taste-profile-v1",
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


def save_project(payload: dict[str, Any], user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    profile = build_taste_profile(payload if isinstance(payload, dict) else {})
    now = _now()
    with _lock:
        with _db() as con:
            con.execute(
                "INSERT OR REPLACE INTO projects (user_id, project_id, payload, version, updated_at) VALUES (?,?,?,?,?)",
                (user_id, project_id, json.dumps(payload, ensure_ascii=False), str(payload.get("version", "unknown")), now),
            )
            con.execute(
                "INSERT OR REPLACE INTO taste_profiles (user_id, project_id, profile, updated_at) VALUES (?,?,?,?)",
                (user_id, project_id, json.dumps(profile, ensure_ascii=False), now),
            )
            _record_prompt_events(con, payload, user_id, project_id)
    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return {"ok": True, "bytes": size, "updated_at": now, "taste": profile}


def _record_prompt_events(con: sqlite3.Connection, payload: dict[str, Any], user_id: str, project_id: str) -> None:
    for node in _collect_node_data(payload):
        data = node["data"]
        for key in ("text", "ownPrompt", "prompt", "brief"):
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            body = {"nodeType": node.get("type"), "field": key, "text": value.strip()}
            digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            con.execute(
                "INSERT OR IGNORE INTO taste_events (user_id, project_id, event_hash, kind, payload, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, project_id, digest, "prompt", json.dumps(body, ensure_ascii=False), _now()),
            )


def load_project(user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any] | None:
    with _lock:
        with _db() as con:
            row = con.execute(
                "SELECT payload, updated_at FROM projects WHERE user_id=? AND project_id=?",
                (user_id, project_id),
            ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    payload = ir.migrate_project_payload(payload)
    return {"payload": payload, "updated_at": row[1]}


def load_taste_profile(user_id: str = DEFAULT_USER_ID, project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    with _lock:
        with _db() as con:
            row = con.execute(
                "SELECT profile FROM taste_profiles WHERE user_id=? AND project_id=?",
                (user_id, project_id),
            ).fetchone()
    if not row:
        return {"version": "taste-profile-v1", "prompt_count": 0, "recent_prompts": [], "style": {}, "components": []}
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return {"version": "taste-profile-v1", "prompt_count": 0, "recent_prompts": [], "style": {}, "components": []}


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
    return "\n".join(lines)
