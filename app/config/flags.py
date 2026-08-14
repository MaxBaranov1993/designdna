"""Feature flags for staged rollout of the CTO plan.

Flags are intentionally simple booleans. They can be overridden per process
via environment variables: DESIGNAI_FLAG_<NAME>=0 or =1.
"""
from __future__ import annotations

import os

DEFAULT_FLAGS = {
    # Stage 0: IR 1.1 foundation.
    "irV11": True,
    # Stage 2: Tailwind projection.
    "tailwindProjection": True,
    # Stage 3: fluid responsive editor.
    "fluidResponsive": True,
    # Stage 4: interaction recorder.
    "interactionRecorder": True,
    # Stage 5: motion editor.
    "motionEditor": True,
    # Stage 6: deterministic video render.
    "videoRender": True,
    # Stage 7: AI director for motion.
    "aiDirector": True,
    # Stage 8: AI-first Edit Node assist preview/apply flow.
    "editorAiAssist": True,
    # Optional generative B-roll/asset jobs through the Seedance gateway.
    "generativeVideo": True,
}


class FeatureFlags:
    """Runtime feature flag registry."""

    def __init__(self, defaults: dict[str, bool] | None = None):
        self._defaults = dict(defaults or DEFAULT_FLAGS)

    def is_enabled(self, name: str) -> bool:
        env = os.environ.get(f"DESIGNAI_FLAG_{name.upper()}")
        if env is not None:
            return env not in ("0", "false", "False", "FALSE", "no", "")
        return self._defaults.get(name, False)

    def all(self) -> dict[str, bool]:
        return {name: self.is_enabled(name) for name in self._defaults}


FEATURE_FLAGS = FeatureFlags()


def is_enabled(name: str) -> bool:
    return FEATURE_FLAGS.is_enabled(name)
