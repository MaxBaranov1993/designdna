"""Responsive engine stub for Design IR (stage 3 implementation).

Planned responsibilities:
- materialize responsive overrides for a given viewport width
- breakpoint range resolution (mobile < 640, tablet 640-1023, desktop >= 1024)
- override source annotation (shared / desktop / tablet / mobile)
"""
from __future__ import annotations

BREAKPOINTS = {
    "mobile": (0, 639),
    "tablet": (640, 1023),
    "desktop": (1024, float("inf")),
}


def viewport_for_width(width: int) -> str:
    """Return the canonical viewport name for a pixel width."""
    for name, (lo, hi) in BREAKPOINTS.items():
        if lo <= width <= hi:
            return name
    return "desktop"
