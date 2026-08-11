"""Tailwind projection stub for Design IR (stage 2 implementation).

Planned API:
    project(ir: dict, mode: str = "exact") -> TailwindProjection

TailwindProjection {
    version: str
    irHash: str
    theme: dict
    nodes: list[dict]
    diagnostics: list[str]
}
"""
from __future__ import annotations


def project(ir: dict, mode: str = "exact") -> dict:
    """Placeholder: returns an empty projection contract."""
    return {
        "version": "0.1.0-stub",
        "irHash": ir.get("contentHash", ""),
        "mode": mode,
        "theme": {},
        "nodes": [],
        "diagnostics": ["Tailwind projection is not yet implemented (stage 2)."],
    }
