"""Interaction IR types and sanitizers (stage 4 implementation).

Planned public types:
    InteractionIR { version, source, scenes, events, variables, privacyReport }
    InteractionEvent { id, time, type, targetSourceKey, payload, resultingSceneId }
    SceneState { id, baseDesignIrHash, patch, viewport, thumbnail }
"""
from __future__ import annotations


class InteractionIR(dict):
    """Placeholder container for Interaction IR documents."""

    @classmethod
    def empty(cls, source: str = "") -> "InteractionIR":
        return cls({
            "version": "0.1.0-stub",
            "source": source,
            "scenes": [],
            "events": [],
            "variables": {},
            "privacyReport": {"sanitized": [], "warnings": []},
        })
