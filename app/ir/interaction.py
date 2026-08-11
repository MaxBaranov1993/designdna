"""Interaction IR build, sanitization, validation and deterministic replay."""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jsonschema

from .hash import content_hash

INTERACTION_VERSION = "1.0"
ALLOWED_EVENTS = {"click", "type", "scroll", "navigate", "focus", "blur", "submit"}
ALLOWED_PATCH_ROOTS = {"tree", "tokens", "frame", "responsive", "meta"}
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "interaction-ir.schema.json"
_SENSITIVE_KEY = re.compile(r"(?:pass(?:word)?|secret|token|cookie|authorization|api[_-]?key|session|credential|first[_-]?name|last[_-]?name|full[_-]?name)", re.I)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parts = urlsplit(value.strip())
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return ""


def _redact_string(value: str) -> tuple[str, list[str]]:
    kinds: list[str] = []
    redacted = value
    if _BEARER.search(redacted) or _JWT.search(redacted):
        redacted = _BEARER.sub("[TOKEN]", redacted)
        redacted = _JWT.sub("[TOKEN]", redacted)
        kinds.append("token")
    if _EMAIL.search(redacted):
        redacted = _EMAIL.sub("[EMAIL]", redacted)
        kinds.append("email")
    if _PHONE.search(redacted):
        redacted = _PHONE.sub("[PHONE]", redacted)
        kinds.append("phone")
    return redacted, kinds


def sanitize_value(value: Any, path: str = "", report: list[dict] | None = None, key: str = "") -> Any:
    """Return a deep sanitized copy and append only redaction metadata."""
    report = report if report is not None else []
    if key and _SENSITIVE_KEY.search(key):
        report.append({"path": path, "kind": "secret-key"})
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitize_value(v, f"{path}/{k}", report, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(v, f"{path}/{i}", report) for i, v in enumerate(value)]
    if isinstance(value, str):
        cleaned, kinds = _redact_string(value)
        for kind in kinds:
            report.append({"path": path, "kind": kind})
        return cleaned
    return copy.deepcopy(value)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _unescape_pointer(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def diff(base: Any, current: Any, path: str = "") -> list[dict]:
    """Build deterministic JSON patches between two sanitized scene states."""
    if type(base) is not type(current):
        return [{"op": "replace", "path": path or "/tree", "value": copy.deepcopy(current)}]
    if isinstance(base, dict):
        ops: list[dict] = []
        for key in sorted(base.keys() - current.keys()):
            ops.append({"op": "remove", "path": f"{path}/{_escape_pointer(str(key))}"})
        for key in sorted(current.keys() - base.keys()):
            ops.append({"op": "add", "path": f"{path}/{_escape_pointer(str(key))}", "value": copy.deepcopy(current[key])})
        for key in sorted(base.keys() & current.keys()):
            if key in {"contentHash", "sourcePreview", "preview", "previews"}:
                continue
            ops.extend(diff(base[key], current[key], f"{path}/{_escape_pointer(str(key))}"))
        return ops
    if isinstance(base, list):
        if len(base) != len(current):
            return [{"op": "replace", "path": path, "value": copy.deepcopy(current)}]
        ops: list[dict] = []
        for index, (left, right) in enumerate(zip(base, current)):
            ops.extend(diff(left, right, f"{path}/{index}"))
        return ops
    if base != current:
        return [{"op": "replace", "path": path, "value": copy.deepcopy(current)}]
    return []


def _validate_patch_path(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("patch path must be an absolute JSON pointer")
    parts = [_unescape_pointer(part) for part in path[1:].split("/") if part != ""]
    if not parts or parts[0] not in ALLOWED_PATCH_ROOTS:
        raise ValueError(f"patch root is not allowed: {path}")
    return parts


def apply_patch(document: dict, patch: list[dict]) -> dict:
    """Apply safe add/replace/remove operations to a deep copy."""
    out = copy.deepcopy(document)
    for item in patch:
        op = item.get("op")
        if op not in {"add", "replace", "remove"}:
            raise ValueError(f"unsupported patch operation: {op}")
        parts = _validate_patch_path(item.get("path", ""))
        parent: Any = out
        for part in parts[:-1]:
            if isinstance(parent, list):
                index = int(part)
                if index < 0 or index >= len(parent):
                    raise ValueError(f"patch index out of range: {item['path']}")
                parent = parent[index]
            elif isinstance(parent, dict) and part in parent:
                parent = parent[part]
            else:
                raise ValueError(f"patch parent does not exist: {item['path']}")
        leaf = parts[-1]
        if isinstance(parent, list):
            index = int(leaf)
            if op == "add" and index == len(parent):
                parent.append(copy.deepcopy(item.get("value")))
            elif 0 <= index < len(parent):
                if op == "remove": parent.pop(index)
                else: parent[index] = copy.deepcopy(item.get("value"))
            else:
                raise ValueError(f"patch index out of range: {item['path']}")
        elif isinstance(parent, dict):
            if op == "remove":
                if leaf not in parent: raise ValueError(f"patch key does not exist: {item['path']}")
                del parent[leaf]
            else:
                if op == "replace" and leaf not in parent: raise ValueError(f"patch key does not exist: {item['path']}")
                parent[leaf] = copy.deepcopy(item.get("value"))
        else:
            raise ValueError(f"patch target is not a container: {item['path']}")
    return out


def load_schema() -> dict:
    import json
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(document: dict) -> list[str]:
    validator = jsonschema.Draft7Validator(load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    formatted = [f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}" for error in errors]
    if not isinstance(document, dict):
        return formatted
    scenes = document.get("scenes") if isinstance(document.get("scenes"), list) else []
    events = document.get("events") if isinstance(document.get("events"), list) else []
    scene_ids = [item.get("id") for item in scenes if isinstance(item, dict)]
    event_ids = [item.get("id") for item in events if isinstance(item, dict)]
    if len(scene_ids) != len(set(scene_ids)): formatted.append("scenes: ids must be unique")
    if len(event_ids) != len(set(event_ids)): formatted.append("events: ids must be unique")
    known_scenes = set(scene_ids)
    for index, event in enumerate(events):
        if isinstance(event, dict) and event.get("resultingSceneId") not in known_scenes:
            formatted.append(f"events/{index}/resultingSceneId: scene does not exist")
    return formatted


def build(base_ir: dict, source: dict | None, scenes: list[dict] | None, events: list[dict] | None, variables: dict | None = None) -> dict:
    """Build a sanitized Interaction IR from patches or captured snapshots."""
    base_hash = base_ir.get("contentHash") or content_hash(base_ir)
    redactions: list[dict] = []
    raw_source = copy.deepcopy(source or {})
    raw_url = raw_source.pop("url", "")
    safe_source = sanitize_value(raw_source, "/source", redactions)
    safe_source["url"] = _safe_url(raw_url)
    safe_source.setdefault("kind", "design-ir")
    safe_source.setdefault("capturedAt", _now())

    safe_scenes: list[dict] = []
    for index, raw in enumerate(scenes or []):
        scene_id = str(raw.get("id") or f"scene-{index}")
        raw_patch = raw.get("patch")
        if isinstance(raw.get("snapshot"), dict):
            raw_patch = diff(base_ir, raw["snapshot"])
        patch = sanitize_value(raw_patch or [], f"/scenes/{index}/patch", redactions)
        for item in patch:
            _validate_patch_path(item.get("path", ""))
        safe_scenes.append({
            "id": scene_id,
            "baseDesignIrHash": base_hash,
            "patch": patch,
            "viewport": raw.get("viewport") if raw.get("viewport") in {"desktop", "tablet", "mobile"} else "desktop",
        })
    if not safe_scenes:
        safe_scenes.append({"id": "scene-0", "baseDesignIrHash": base_hash, "patch": [], "viewport": "desktop"})

    scene_ids = {scene["id"] for scene in safe_scenes}
    safe_events: list[dict] = []
    for index, raw in enumerate(events or []):
        event_type = str(raw.get("type", ""))
        if event_type not in ALLOWED_EVENTS:
            raise ValueError(f"unsupported interaction event: {event_type}")
        resulting = str(raw.get("resultingSceneId") or safe_scenes[min(index + 1, len(safe_scenes) - 1)]["id"])
        if resulting not in scene_ids:
            raise ValueError(f"event points to unknown scene: {resulting}")
        safe_events.append({
            "id": str(raw.get("id") or f"event-{index}"),
            "time": max(0, int(raw.get("time") or 0)),
            "type": event_type,
            "targetSourceKey": str(raw.get("targetSourceKey") or ""),
            "payload": sanitize_value(raw.get("payload") or {}, f"/events/{index}/payload", redactions),
            "resultingSceneId": resulting,
        })
    safe_events.sort(key=lambda item: (item["time"], item["id"]))

    document = {
        "version": INTERACTION_VERSION,
        "source": safe_source,
        "scenes": safe_scenes,
        "events": safe_events,
        "variables": sanitize_value(variables or {}, "/variables", redactions),
        "privacyReport": {
            "sanitizedCount": len(redactions),
            "sanitized": redactions,
            "warnings": [],
            "safeForAi": True,
        },
    }
    errors = validate(document)
    if errors:
        raise ValueError("invalid Interaction IR: " + "; ".join(errors[:5]))
    return document


def replay(base_ir: dict, interaction: dict, scene_id: str) -> dict:
    """Materialize one scene from the canonical base IR."""
    errors = validate(interaction)
    if errors:
        raise ValueError("invalid Interaction IR: " + "; ".join(errors[:5]))
    base_hash = base_ir.get("contentHash") or content_hash(base_ir)
    scene = next((item for item in interaction["scenes"] if item["id"] == scene_id), None)
    if not scene:
        raise ValueError(f"scene not found: {scene_id}")
    if scene["baseDesignIrHash"] != base_hash:
        raise ValueError("scene baseDesignIrHash does not match the supplied Design IR")
    return apply_patch(base_ir, scene["patch"])


class InteractionIR(dict):
    @classmethod
    def empty(cls, source: str = "") -> "InteractionIR":
        return cls(build({"tree": [], "tokens": {}}, {"kind": "design-ir", "url": source}, [], []))
