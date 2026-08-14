"""Deterministic migration between Design IR schema versions."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from .hash import content_hash
from .schema import CURRENT_SCHEMA_VERSION
from .source_key import deduplicate_source_keys
from .responsive import ensure_fluid_layout

DEFAULT_VIEWPORT_HEIGHTS = {"desktop": 900, "tablet": 1024, "mobile": 844}


def repair_for_schema(ir: dict) -> dict:
    """In-place repair of known-safe schema drift from the editor/page compose.

    Sections do not allow `name`; viewport metas require numeric `height`.
    """
    if not isinstance(ir, dict):
        return ir
    frame = ir.get("frame") if isinstance(ir.get("frame"), dict) else {}
    frame_h = frame.get("height")
    fallback_h = frame_h if isinstance(frame_h, (int, float)) and frame_h >= 1 else None
    responsive = ir.get("responsive")
    if isinstance(responsive, dict):
        viewports = responsive.get("viewports")
        if isinstance(viewports, dict):
            for name, meta in viewports.items():
                if not isinstance(meta, dict):
                    continue
                height = meta.get("height")
                if not isinstance(height, (int, float)) or height < 1:
                    meta["height"] = float(fallback_h or DEFAULT_VIEWPORT_HEIGHTS.get(str(name), 900))
    for section in ir.get("tree") or []:
        if isinstance(section, dict):
            section.pop("name", None)
    return ir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_ir(ir: dict, source: str | None = None) -> dict:
    """Return a migrated copy of `ir` to the current schema version.

    - If the document already reports the current version, it is still
      canonicalized (contentHash, sourceKey deduplication and conservative
      responsive fallbacks for generated card rows).
    - If the document is missing `version` or reports `1.0`, it is upgraded
      to 1.1 and provenance is recorded.
    - The original dict is never mutated.
    """
    if not isinstance(ir, dict):
        raise ValueError("IR must be a dict")

    out = copy.deepcopy(ir)
    original_version = str(out.get("version", "1.0"))
    is_legacy = original_version != CURRENT_SCHEMA_VERSION

    # Ensure version is set to current.
    out["version"] = CURRENT_SCHEMA_VERSION

    # Initialize provenance if missing.
    provenance = out.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        out["provenance"] = provenance
    if is_legacy:
        provenance["migratedFrom"] = original_version
        provenance["migratedAt"] = _now()
    if source:
        provenance["importedFrom"] = source
    if not provenance.get("createdAt"):
        provenance["createdAt"] = _now()

    # Ensure a stable element identity graph.
    out = deduplicate_source_keys(out)
    out = ensure_fluid_layout(out)
    repair_for_schema(out)

    # Recompute content hash excluding preview/runtime fields.
    out["contentHash"] = content_hash(out)

    return out


def ensure_current(ir: dict | None, source: str | None = None) -> dict | None:
    """Convenience helper: migrate only if the input is a non-empty dict."""
    if not isinstance(ir, dict) or not ir:
        return ir
    return migrate_ir(ir, source=source)


def migrate_project_payload(payload: dict) -> dict:
    """Walk a saved project payload and migrate every IR node to current version.

    IR documents live inside node data under keys such as `ir`, `variants`,
    `blocks`, and inside `channels`. The payload structure itself (pages, graph,
    nodes, edges) is left untouched.
    """
    payload = copy.deepcopy(payload)

    def _migrate_value(value):
        if isinstance(value, dict):
            if value.get("version") in ("1.0", "1.1") and "tree" in value and "tokens" in value:
                return migrate_ir(value, source="project-load")
            return {k: _migrate_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_migrate_value(v) for v in value]
        return value

    return _migrate_value(payload)
