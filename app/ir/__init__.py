"""ir-core: Design IR schema, migration, validation and identity utilities."""
from __future__ import annotations

from .schema import CURRENT_SCHEMA_VERSION, load_schema
from .migrate import migrate_ir, ensure_current, migrate_project_payload
from .validate import validate_ir, ValidationError, format_errors
from .hash import content_hash, canonical_json
from .source_key import stable_key, resolve_collision, prefix_block_key
from .style_dna import (
    extract_primitives,
    build_semantic,
    build_style_dna,
    bind_element_styles,
    apply_tokens,
    extract_from_signals,
    enrich_ir,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "load_schema",
    "migrate_ir",
    "ensure_current",
    "migrate_project_payload",
    "validate_ir",
    "ValidationError",
    "format_errors",
    "content_hash",
    "canonical_json",
    "stable_key",
    "resolve_collision",
    "prefix_block_key",
    "extract_primitives",
    "build_semantic",
    "build_style_dna",
    "bind_element_styles",
    "apply_tokens",
    "extract_from_signals",
    "enrich_ir",
]
