"""Motion IR types and validators (stage 5 implementation).

Planned public types:
    MotionIR { version, composition, scenes, tracks, markers, assets, renderSettings }
    Track { id, type, targetSourceKey, clips }
    Clip { start, duration, event, keyframes, locked }
"""
from __future__ import annotations


class MotionIR(dict):
    """Placeholder container for Motion IR documents."""

    @classmethod
    def empty(cls, composition: str = "16:9") -> "MotionIR":
        return cls({
            "version": "0.1.0-stub",
            "composition": composition,
            "scenes": [],
            "tracks": [],
            "markers": [],
            "assets": [],
            "renderSettings": {"fps": 30, "format": "mp4"},
        })
