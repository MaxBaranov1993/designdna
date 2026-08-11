"""Design IR validation with structured, actionable diagnostics."""
from __future__ import annotations

import jsonschema

from .schema import CURRENT_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS, load_schema


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


def _get_validator(version: str = CURRENT_SCHEMA_VERSION) -> jsonschema.Draft7Validator:
    if version not in _validators:
        schema = load_schema(version)
        _validators[version] = jsonschema.Draft7Validator(schema)
    return _validators[version]


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
    errors = [
        ValidationError(
            "/".join(str(p) for p in error.absolute_path) or "(root)",
            error.message,
            "error",
        )
        for error in validator.iter_errors(ir)
    ]
    return sorted(errors, key=lambda e: (e.path, e.message))


def format_errors(errors: list[ValidationError]) -> list[str]:
    """Format diagnostics as human-readable strings."""
    return [f"{e.path}: {e.message}" for e in errors]
