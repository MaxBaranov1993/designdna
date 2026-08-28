"""Timeline render: паритет Python-солвера с движком, экспорт и мини-рендер."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server import app
from ir.timeline import build, preset_operations, apply_change_set, build_change_set
from timeline_render import (
    easing_progress,
    export_css,
    export_waapi,
    render_timeline_video,
    solve_layer,
    solve_track,
)

DESIGN_IR = {
    "version": "1.1",
    "frame": {"width": 320, "height": 240},
    "tree": [
        {
            "id": "hero-1",
            "sourceKey": "src-hero-1",
            "type": "hero",
            "variant": "center",
            "props": {"heading": "Продукт"},
            "frame": {"width": 320, "height": 240},
            "children": [
                {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Начать"},
            ],
        },
    ],
}


def _timeline(duration: int = 500, fps: int = 12) -> dict:
    return build(DESIGN_IR, {"width": 320, "height": 240, "fps": fps, "duration": duration})


def _animated_timeline() -> dict:
    timeline = _timeline(duration=2000, fps=30)
    operations = preset_operations("fade-in-up", ["layer-hero-1"], {"start": 0, "duration": 600})
    operations += preset_operations("cta-pulse", ["layer-hero-1-1"], {"start": 800, "duration": 600})
    change_set = build_change_set(timeline, "тест", operations)
    return apply_change_set(timeline, change_set)


# --------------------------------------------------------------------------
# Паритет с frontend/src/engine/timeline.ts (те же утверждения, что в
# engine.regression.test.mjs) — расхождение сломало бы совпадение ролика и превью.

def test_solver_holds_and_interpolates_like_engine() -> None:
    track = {"keyframes": [{"t": 1000, "value": 10}, {"t": 2000, "value": 20}]}
    assert solve_track(track, 0, 0) == 10
    assert solve_track(track, 999, 0) == 10
    assert solve_track(track, 2000, 0) == 20
    assert solve_track(track, 9999, 0) == 20
    linear = {"keyframes": [{"t": 0, "value": 0, "easing": "linear"}, {"t": 1000, "value": 100}]}
    assert solve_track(linear, 250, 0) == 25
    assert solve_track(linear, 500, 0) == 50
    assert solve_track(None, 500, 1) == 1
    assert solve_track({"keyframes": []}, 500, 7) == 7


def test_solver_easings_match_engine() -> None:
    for easing in ("linear", "ease", "ease-in", "ease-out", "ease-in-out"):
        assert easing_progress(easing, None, 0) == 0
        assert easing_progress(easing, None, 1) == 1
        prev = 0.0
        for step in range(1, 10):
            value = easing_progress(easing, None, step / 10)
            assert value >= prev - 1e-9, easing
            prev = value
    assert abs(easing_progress("ease-in-out", None, 0.5) - 0.5) < 1e-3
    assert easing_progress("ease-in", None, 0.25) < 0.25
    # кастомный cubic-bezier(0,0,1,1) — линейный
    assert abs(easing_progress("cubic-bezier", [0, 0, 1, 1], 0.5) - 0.5) < 1e-2


def test_solve_layer_visibility_and_clamps() -> None:
    timeline = _animated_timeline()
    layer = next(l for l in timeline["layers"] if l["id"] == "layer-hero-1")
    inside = solve_layer(layer, 300)
    assert inside["visible"] is True
    assert 0 < inside["opacity"] < 1
    assert inside["y"] > 0, "fade-in-up двигает слой снизу вверх"


# --------------------------------------------------------------------------
# Экспорт веб-анимации


def test_export_css_contains_keyframes_per_layer() -> None:
    css = export_css(_animated_timeline())
    assert '@keyframes tl-layer-hero-1-transform' in css
    assert '@keyframes tl-layer-hero-1-opacity' in css
    assert '[data-timeline-layer="layer-hero-1"]' in css
    assert "animation-fill-mode: both" in css


def test_export_waapi_offsets_are_sorted_and_in_range() -> None:
    recipe = export_waapi(_animated_timeline())
    assert recipe["duration"] == 2000 and recipe["fps"] == 30
    assert {layer["id"] for layer in recipe["layers"]} == {"layer-hero-1", "layer-hero-1-1"}
    for layer in recipe["layers"]:
        offsets = [kf["offset"] for kf in layer["keyframes"]]
        assert offsets == sorted(offsets)
        assert 0 <= offsets[0] and offsets[-1] <= 1
    # JSON-сериализуемость рецепта (его забирает продуктовый код)
    json.dumps(recipe)


def test_export_endpoints() -> None:
    timeline = _animated_timeline()
    with TestClient(app) as client:
        css_resp = client.post("/api/timeline/export", json={"timeline": timeline, "mode": "css"})
        assert css_resp.status_code == 200, css_resp.text
        assert "timeline.css" in css_resp.json()["files"]
        waapi_resp = client.post("/api/timeline/export", json={"timeline": timeline, "mode": "waapi"})
        assert waapi_resp.status_code == 200
        json.loads(waapi_resp.json()["files"]["timeline.waapi.json"])


# --------------------------------------------------------------------------
# Реальный мини-рендер: 320×240 @ 30 fps, 2 секунды = 60 кадров


def test_render_timeline_video_produces_mp4(tmp_path: Path) -> None:
    timeline = _animated_timeline()
    output = tmp_path / "timeline.mp4"
    result = render_timeline_video(timeline, DESIGN_IR, output)
    assert output.is_file() and result["bytes"] > 0
    assert result["frames"] == 60 and result["fps"] == 30
    assert result["width"] == 320 and result["height"] == 240


def test_render_endpoint_validates_input() -> None:
    timeline = _animated_timeline()
    with TestClient(app) as client:
        # чужой/пустой IR: hash-связка таймлайна не сходится — 409
        resp = client.post("/api/timeline/render", json={"timeline": timeline, "ir": {"version": "1.1", "tree": []}})
        assert resp.status_code == 409
        # нечётная ширина композиции — 422 (h264 требует чётные размеры)
        odd = build(DESIGN_IR, {"width": 321, "height": 240, "fps": 12, "duration": 500})
        resp = client.post("/api/timeline/render", json={"timeline": odd, "ir": DESIGN_IR})
        assert resp.status_code == 422
