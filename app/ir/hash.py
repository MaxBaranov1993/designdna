"""Canonical hashing for Design IR identity and change detection."""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Fields that are visual QA evidence or runtime state, not canonical design data.
# provenance included: migrate_ir stamps wall-clock createdAt on documents that
# arrive without it (frontend-composed pages), so hashing provenance made two
# migrations of one document disagree and broke interaction/motion hash binding.
_PREVIEW_KEYS = frozenset({
    "sourcePreview",
    "preview",
    "previews",
    "contentHash",
    "provenance",
})


def _strip_preview(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_preview(v)
            for k, v in value.items()
            if k not in _PREVIEW_KEYS
        }
    if isinstance(value, list):
        return [_strip_preview(v) for v in value]
    return value


def canonical_json(ir: dict) -> str:
    """Return a deterministic JSON representation of the IR.

    Excludes preview/runtime fields so that identical designs produce identical
    hashes even when screenshots differ.
    """
    stripped = _strip_preview(ir)
    return json.dumps(stripped, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(ir: dict) -> str:
    """SHA-256 of the canonical JSON representation."""
    return hashlib.sha256(canonical_json(ir).encode("utf-8")).hexdigest()
