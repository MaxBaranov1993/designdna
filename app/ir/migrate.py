"""Deterministic migration between Design IR schema versions."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from .hash import content_hash
from .schema import CURRENT_SCHEMA_VERSION
from .source_key import deduplicate_source_keys
from .responsive import ensure_fluid_layout


# Project loads must be a pure function of the stored JSON.  A wall-clock
# timestamp here made two reads of the same persisted revision produce
# different bytes, which correctly tripped the desktop live-session CAS guard
# after a renderer reload.  Standalone generation still uses the real clock;
# only project-payload migration supplies this stable "unknown legacy time".
_PROJECT_MIGRATION_TIME = "1970-01-01T00:00:00+00:00"

_GENERATED_META_KEYS = {
    "name", "description", "qaWarnings", "fontFaces", "activeViewport", "styleTags", "mixOf",
    "designSystemErrors", "designSystemWarnings", "designSystemRef", "compiledContextHash",
    "archetypeId", "identityScore", "identityReport", "strictRecovery", "requestedComponentKey",
    "sourceTokenLock", "sourceTokenNodeId", "exactServiceCardEmbedded",
}
_GENERATED_SIZE_ALIASES = {
    "h1": "display", "h2": "xl", "h3": "lg", "h4": "md",
    "body": "md", "caption": "sm", "small": "sm", "large": "lg",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_generated_ir(ir: dict) -> dict:
    """Repair common provider-only aliases without weakening Design IR validation.

    Provider responses frequently add descriptive metadata that is not part of
    the interchange contract, or use HTML typography names for the closed
    ``size`` enum.  Normalize only those known cases; every other schema error
    remains visible to the caller.
    """
    if not isinstance(ir, dict):
        raise ValueError("IR must be a dict")
    out = copy.deepcopy(ir)
    meta = out.get("meta")
    if isinstance(meta, dict):
        out["meta"] = {key: value for key, value in meta.items() if key in _GENERATED_META_KEYS}

    def strip_invented_src(media: object) -> None:
        """Модель не умеет давать реальные картинки: выдуманный http/относительный
        src ломается битой ссылкой в превью. Оставляем заглушку (imagePrompt),
        которую пользователь заменяет своим файлом в редакторе. Встроенные
        data:-URL и внутренние ddna:// сохраняем."""
        if not isinstance(media, dict):
            return
        src = media.get("src")
        if not isinstance(src, str):
            return
        if src.startswith(("data:", "ddna://")):
            return
        media.pop("src", None)
        if not media.get("imagePrompt"):
            media["imagePrompt"] = str(media.get("alt") or "изображение")

    def normalize_node(node: object) -> None:
        if not isinstance(node, dict):
            return
        raw_size = node.get("size")
        if isinstance(raw_size, str) and raw_size in _GENERATED_SIZE_ALIASES:
            node["size"] = _GENERATED_SIZE_ALIASES[raw_size]
        if node.get("type") == "image":
            strip_invented_src(node)
        props = node.get("props")
        if isinstance(props, dict):
            strip_invented_src(props.get("media"))
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                normalize_node(child)

    tree = out.get("tree")
    if isinstance(tree, list):
        for section in tree:
            normalize_node(section)
    return out


def migrate_ir(ir: dict, source: str | None = None, *, recorded_at: str | None = None) -> dict:
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
    migration_time = recorded_at or _now()
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
        provenance["migratedAt"] = migration_time
    if source:
        provenance["importedFrom"] = source
    if not provenance.get("createdAt"):
        provenance["createdAt"] = migration_time

    # Ensure a stable element identity graph.
    out = deduplicate_source_keys(out)
    out = ensure_fluid_layout(out)

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
                provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
                # Prefer the document's own stable creation time.  Legacy IR
                # without one receives a deterministic sentinel instead of
                # the wall clock, keeping repeated loads byte-identical.
                recorded_at = provenance.get("createdAt") or _PROJECT_MIGRATION_TIME
                return migrate_ir(value, source="project-load", recorded_at=str(recorded_at))
            return {k: _migrate_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_migrate_value(v) for v in value]
        return value

    return _migrate_value(payload)
