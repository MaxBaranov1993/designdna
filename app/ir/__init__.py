"""ir-core: Design IR schema, migration, validation and identity utilities."""
from __future__ import annotations

from .schema import CURRENT_SCHEMA_VERSION, LATEST_SCHEMA_VERSION, load_aux_schema, load_schema
from .migrate import migrate_ir, ensure_current, migrate_project_payload, sanitize_generated_ir
from .validate import (
    validate_change_set,
    validate_ir,
    validate_parser_envelope,
    ValidationError,
    format_errors,
)
from .composition import (
    CompositionContract,
    LayoutAxis,
    NodeProvenance,
    SemanticChangeSet,
    SourceRecord,
    validate_change_set_semantics,
    validate_v2_semantics,
)
from .parser_contract import (
    PARSER_CONTRACT_VERSION,
    LayoutEvidence,
    ParserDiagnostic,
    ParserSourceEnvelope,
    ViewportMeasurement,
    build_parser_envelope,
    normalize_source_ref,
    stable_source_id,
    validate_parser_envelope_semantics,
)
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
from .normalize import preview as preview_normalization
from .tailwind_projection import project as project_tailwind
from .responsive import (
    viewport_for_width,
    clamp_width,
    ensure_fluid_layout,
    materialize as materialize_responsive,
)
from .interaction import (
    INTERACTION_VERSION,
    build as build_interaction,
    validate as validate_interaction,
    replay as replay_interaction,
    sanitize_value as sanitize_interaction_value,
    diff as diff_interaction_scene,
    apply_patch as apply_interaction_patch,
)
from .motion import (
    MOTION_VERSION,
    build as build_motion,
    validate as validate_motion,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "LATEST_SCHEMA_VERSION",
    "load_aux_schema",
    "load_schema",
    "migrate_ir",
    "ensure_current",
    "migrate_project_payload",
    "sanitize_generated_ir",
    "validate_ir",
    "validate_change_set",
    "validate_parser_envelope",
    "ValidationError",
    "format_errors",
    "CompositionContract",
    "LayoutAxis",
    "NodeProvenance",
    "SemanticChangeSet",
    "SourceRecord",
    "validate_change_set_semantics",
    "validate_v2_semantics",
    "PARSER_CONTRACT_VERSION",
    "LayoutEvidence",
    "ParserDiagnostic",
    "ParserSourceEnvelope",
    "ViewportMeasurement",
    "build_parser_envelope",
    "normalize_source_ref",
    "stable_source_id",
    "validate_parser_envelope_semantics",
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
    "preview_normalization",
    "project_tailwind",
    "viewport_for_width",
    "clamp_width",
    "ensure_fluid_layout",
    "materialize_responsive",
    "INTERACTION_VERSION",
    "build_interaction",
    "validate_interaction",
    "replay_interaction",
    "sanitize_interaction_value",
    "diff_interaction_scene",
    "apply_interaction_patch",
    "MOTION_VERSION",
    "build_motion",
    "validate_motion",
]
