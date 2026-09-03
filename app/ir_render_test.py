"""Small contracts for the server-side Design IR renderer."""
from __future__ import annotations

import pytest

import ir_render


def test_render_png_rejects_invalid_width_before_starting_browser():
    with pytest.raises(ValueError, match="between 320 and 4096"):
        ir_render.render_png({}, width=200)
    with pytest.raises(ValueError, match="integer"):
        ir_render.render_png({}, width="wide")


def test_render_png_reports_missing_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(ir_render, "RENDERER_JS", tmp_path / "missing-engine.js")
    with pytest.raises(RuntimeError, match="frontend build"):
        ir_render.render_png({}, width=1440)

