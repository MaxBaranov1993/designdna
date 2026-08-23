"""AI-режиссёр таймлайна: детерминированный разбор промптов и эндпоинт."""
from __future__ import annotations

from fastapi.testclient import TestClient

from server import app
from ir.timeline import revert_change_set, validate
from timeline_director import direct, plan_from_prompt

DESIGN_IR = {
    "version": "1.1",
    "frame": {"width": 1440},
    "tree": [
        {
            "id": "hero-1",
            "sourceKey": "src-hero-1",
            "type": "hero",
            "variant": "center",
            "props": {"heading": "Продукт"},
            "children": [
                {"id": "hero-cta", "sourceKey": "src-hero-cta", "type": "button", "text": "Начать"},
            ],
        },
        {"id": "features-1", "type": "feature-grid", "variant": "cards", "props": {}},
        {"id": "footer-1", "type": "footer", "variant": "simple", "props": {}},
    ],
}


def _timeline() -> dict:
    from ir.timeline import build
    return build(DESIGN_IR, {"duration": 9000})


def test_default_plan_covers_all_sections() -> None:
    timeline = _timeline()
    steps = plan_from_prompt(timeline, "сделай красиво")
    presets = [step["preset"] for step in steps]
    assert "fade-in-up" in presets and "zoom-spotlight" in presets


def test_keyword_plan_maps_to_presets() -> None:
    timeline = _timeline()
    steps = plan_from_prompt(timeline, "интро снизу, наезд камеры, пульс на кнопке в конце")
    presets = {step["preset"] for step in steps}
    assert {"fade-in-up", "zoom-spotlight", "cta-pulse"} <= presets
    pulse = next(step for step in steps if step["preset"] == "cta-pulse")
    assert pulse["start"] > 0.5, "пульс — в финале ролика"


def test_direct_applies_and_reverts_atomically() -> None:
    timeline = _timeline()
    applied, change_set = direct(timeline, "интро снизу, пульс на кнопке", allow_llm=False)
    assert validate(applied) == []
    hero = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1")
    assert "opacity" in hero["transform"]["properties"], "интро добавляет прозрачность"
    cta = next(layer for layer in applied["layers"] if layer["id"] == "layer-hero-1-1")
    assert "scale" in cta["transform"]["properties"], "пульс анимирует масштаб кнопки"
    reverted = revert_change_set(applied, change_set)
    assert validate(reverted) == []
    hero_after = next(layer for layer in reverted["layers"] if layer["id"] == "layer-hero-1")
    assert hero_after["transform"]["properties"] == {}


def test_assist_endpoint_returns_change_set() -> None:
    timeline = _timeline()
    with TestClient(app) as client:
        resp = client.post("/api/timeline/assist", json={
            "timeline": timeline,
            "prompt": "каскадное появление секций, наезд на последней",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["changeSet"]["atomic"] is True
        assert validate(body["timeline"]) == []
        # инверсии покрывают все прямые операции
        forward_ids = {op["id"] for op in body["changeSet"]["operations"]}
        assert all(inv["inverseOf"] in forward_ids for inv in body["changeSet"]["inverseOperations"])


def test_assist_endpoint_rejects_empty_prompt() -> None:
    timeline = _timeline()
    with TestClient(app) as client:
        resp = client.post("/api/timeline/assist", json={"timeline": timeline, "prompt": "   "})
        assert resp.status_code == 422
