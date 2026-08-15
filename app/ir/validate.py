"""Design IR validation with structured, actionable diagnostics."""
from __future__ import annotations

import jsonschema
from referencing import Registry, Resource

from .composition import validate_change_set_semantics, validate_v2_semantics
from .parser_contract import validate_parser_envelope_semantics
from .schema import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    load_aux_schema,
    load_schema,
)


class ValidationError(tuple):
    """Structured validation diagnostic."""

    def __new__(cls, path: str, message: str, severity: str = "error"):
        return super().__new__(cls, (path, message, severity))

    @property
    def path(self) -> str:
        return self[0]

    @property
    def message(self) -> str:
        return self[1]

    @property
    def severity(self) -> str:
        return self[2]

    def __repr__(self) -> str:
        return f"ValidationError(path={self.path!r}, message={self.message!r}, severity={self.severity!r})"


_validators: dict[str, jsonschema.Draft7Validator] = {}
_aux_validators: dict[str, jsonschema.Draft7Validator] = {}


def _get_registry() -> Registry:
    registry = Registry()
    for supported_version in SUPPORTED_SCHEMA_VERSIONS:
        schema = load_schema(supported_version)
        schema_id = schema.get("$id")
        if schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    return registry


def _get_validator(version: str = CURRENT_SCHEMA_VERSION) -> jsonschema.Draft7Validator:
    if version not in _validators:
        schema = load_schema(version)
        _validators[version] = jsonschema.Draft7Validator(
            schema,
            registry=_get_registry(),
            format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
        )
    return _validators[version]


def _get_aux_validator(name: str) -> jsonschema.Draft7Validator:
    if name not in _aux_validators:
        _aux_validators[name] = jsonschema.Draft7Validator(
            load_aux_schema(name),
            registry=_get_registry(),
            format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
        )
    return _aux_validators[name]


def validate_ir(ir: dict, version: str | None = None) -> list[ValidationError]:
    """Validate an IR document and return structured diagnostics.

    If `version` is None, the document's own `version` field is used, falling
    back to the current schema version. Errors are returned sorted by path.
    """
    if not isinstance(ir, dict):
        return [ValidationError("(root)", "IR must be an object", "error")]

    doc_version = str(ir.get("version", CURRENT_SCHEMA_VERSION))
    if doc_version not in SUPPORTED_SCHEMA_VERSIONS:
        return [
            ValidationError(
                "version",
                f"Unsupported Design IR version {doc_version!r}; supported: {SUPPORTED_SCHEMA_VERSIONS}",
                "error",
            )
        ]

    target_version = version or doc_version or CURRENT_SCHEMA_VERSION
    validator = _get_validator(target_version)
    errors: list[ValidationError] = [
        ValidationError(
            "/".join(str(p) for p in error.absolute_path) or "(root)",
            error.message,
            "error",
        )
        for error in validator.iter_errors(ir)
    ]
    if target_version == "2.0" and not errors:
        errors.extend(
            ValidationError(f"composition/{message.split(':', 1)[0]}", message, "error")
            for message in validate_v2_semantics(ir)
        )
    return sorted(errors, key=lambda e: (e.path, e.message))


def validate_change_set(value: dict) -> list[ValidationError]:
    """Validate a SemanticChangeSet with schema and typed invariants."""
    if not isinstance(value, dict):
        return [ValidationError("(root)", "Change set must be an object", "error")]
    validator = _get_aux_validator("semantic-change-set")
    errors: list[ValidationError] = [
        ValidationError(
            "/".join(str(p) for p in error.absolute_path) or "(root)",
            error.message,
            "error",
        )
        for error in validator.iter_errors(value)
    ]
    if not errors:
        errors.extend(
            ValidationError(message.split(":", 1)[0], message, "error")
            for message in validate_change_set_semantics(value)
        )
    return sorted(errors, key=lambda e: (e.path, e.message))


def validate_parser_envelope(value: dict) -> list[ValidationError]:
    """Validate the persisted Parser v2 sidecar contract."""
    if not isinstance(value, dict):
        return [ValidationError("(root)", "Parser envelope must be an object", "error")]
    validator = _get_aux_validator("parser-source-envelope")
    errors = [
            ValidationError(
                "/".join(str(p) for p in error.absolute_path) or "(root)",
                error.message,
                "error",
            )
            for error in validator.iter_errors(value)
        ]
    if not errors:
        errors.extend(
            ValidationError(message.split(":", 1)[0], message, "error")
            for message in validate_parser_envelope_semantics(value)
        )
    return sorted(errors, key=lambda e: (e.path, e.message))


def format_errors(errors: list[ValidationError]) -> list[str]:
    """Format diagnostics as human-readable strings."""
    return [f"{e.path}: {e.message}" for e in errors]
