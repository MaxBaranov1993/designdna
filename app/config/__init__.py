"""Shared runtime configuration for the DesignAI backend."""
from __future__ import annotations

from .flags import FEATURE_FLAGS, is_enabled

__all__ = ["FEATURE_FLAGS", "is_enabled"]
