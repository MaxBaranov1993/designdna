"""Stable element identity (`sourceKey`) utilities for Design IR."""
from __future__ import annotations

import re
from typing import Any

_MAX_KEY_LEN = 500
_SUFFIX_RE = re.compile(r"#(\d+)$")


def stable_key(raw: str) -> str:
    """Normalize a raw key: trim, truncate, avoid empty strings."""
    key = str(raw).strip()
    if not key:
        key = "element"
    return key[:_MAX_KEY_LEN]


def _next_suffix(base: str, seen: set[str]) -> str:
    """Find the smallest integer suffix that makes `base` unique in `seen`."""
    n = 1
    candidate = f"{base}#{n:03d}"
    while candidate in seen:
        n += 1
        candidate = f"{base}#{n:03d}"
    return candidate


def _deduplicate_node_keys(node: Any, seen: set[str]) -> Any:
    if isinstance(node, dict):
        key = node.get("sourceKey")
        if isinstance(key, str) and key:
            normalized = stable_key(key)
            if normalized in seen:
                normalized = _next_suffix(normalized, seen)
            node["sourceKey"] = normalized
            seen.add(normalized)
        for value in node.values():
            _deduplicate_node_keys(value, seen)
    elif isinstance(node, list):
        for item in node:
            _deduplicate_node_keys(item, seen)
    return node


def deduplicate_source_keys(ir: dict) -> dict:
    """Return `ir` with deterministic, unique sourceKeys within the document.

    Collisions are resolved with a zero-padded integer suffix (#001, #002, ...).
    The root document itself is not assigned a sourceKey.
    """
    seen: set[str] = set()
    return _deduplicate_node_keys(ir, seen)


def resolve_collision(key: str, seen: set[str]) -> str:
    """Resolve a single collision against an external set of used keys."""
    key = stable_key(key)
    if key not in seen:
        return key
    return _next_suffix(key, seen)


def prefix_block_key(block_name: str, key: str) -> str:
    """Prefix a source key with its block name during Page composition.

    Preserves the original key after the slash so reverse-mapping stays possible.
    """
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", str(block_name)).strip("-") or "block"
    key = stable_key(key)
    # Avoid double-prefixing.
    if key.startswith(f"{name}/"):
        return key
    return f"{name}/{key}"
