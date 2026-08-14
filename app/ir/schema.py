"""Schema loading and versioning utilities for Design IR."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(os.environ.get("DESIGNDNA_RUNTIME_ROOT") or Path(__file__).resolve().parent.parent.parent)
SCHEMA_DIR = ROOT / "schema"

CURRENT_SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}


@lru_cache(maxsize=4)
def load_schema(version: str = CURRENT_SCHEMA_VERSION) -> dict:
    """Load a cached JSON schema for the requested Design IR version.

    If a dedicated file for the version exists (e.g. design-ir-1.0.schema.json),
    it is used. Otherwise the canonical design-ir.schema.json is returned.
    """
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported Design IR schema version: {version!r}")
    dedicated = SCHEMA_DIR / f"design-ir-{version}.schema.json"
    if dedicated.exists():
        return json.loads(dedicated.read_text(encoding="utf-8"))
    canonical = SCHEMA_DIR / "design-ir.schema.json"
    return json.loads(canonical.read_text(encoding="utf-8"))
