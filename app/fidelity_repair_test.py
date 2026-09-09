"""Цикл AI-починки захвата: судья детерминированный, модель только диагност.

Главная гарантия: правка принимается ТОЛЬКО если измеренное сходство выросло.
Поэтому неудачная или враждебная гипотеза модели не может ухудшить результат —
худший исход это откат. Тесты гоняют логику без браузера и без сети: замер и
предложение внедряются как функции.
"""
from __future__ import annotations

import json


from fidelity_repair import (
    apply_operations,
    build_repair_prompt,
    nodes_in_region,
    region_rects,
    repair_block,
    validate_operations,
)


def _ir() -> dict:
    return {
        "version": "1.1",
        "tree": [{
            "type": "source-block", "sourceKey": "root",
            "frame": {"x": 0, "y": 0, "width": 800, "height": 400, "layout": "auto"},
            "children": [
                {"type": "heading", "sourceKey": "hero-title", "text": "Outreach autopilot",
                 "frame": {"x": 100, "y": 40, "width": 600, "height": 60},
                 "style": {"color": "#ffffff", "fontWeight": 800}},
                {"type": "text", "sourceKey": "hero-sub", "text": "Supporting copy",
                 "frame": {"x": 100, "y": 120, "width": 600, "height": 30},
                 "style": {"color": "#9aa2b4"}},
            ],
        }],
    }


def _report() -> dict:
    return {
        "reference_size": [800, 400],
        "pixel_similarity": 88.0,
        "region_diffs": [
            {"region": [0, 1], "mismatch_pct": 42.0},
            {"region": [2, 3], "mismatch_pct": 11.5},
            {"region": [0, 2], "mismatch_pct": 30.0},
        ],
    }


def test_worst_regions_come_first_and_map_to_pixels():
    rects = region_rects(_report(), limit=2)
    assert [r["mismatchPct"] for r in rects] == [42.0, 30.0]
    first = rects[0]
    assert first["x"] == 100 and first["y"] == 0
    assert first["width"] == 100 and first["height"] == 50


def test_nodes_in_region_uses_absolute_frames():
    rect = {"x": 100, "y": 40, "width": 200, "height": 60}
    hits = nodes_in_region(_ir(), rect)
    keys = {hit["sourceKey"] for hit in hits}
    assert "hero-title" in keys
    assert "hero-sub" not in keys, "узел вне региона не должен попадать в диагностику"
    title = next(hit for hit in hits if hit["sourceKey"] == "hero-title")
    # Кадры IR относительны родителю; в регион отдаём абсолютные.
    assert title["frame"]["x"] == 100 and title["frame"]["y"] == 40


def test_prompt_forbids_geometry_and_carries_only_region_nodes():
    rect = {"x": 100, "y": 40, "width": 200, "height": 60}
    messages = build_repair_prompt("hero", "desktop", rect, nodes_in_region(_ir(), rect), _report())
    assert "never propose coordinates" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["region"] == rect
    assert [node["sourceKey"] for node in payload["nodesInRegion"]] == ["hero-title"]


def test_validation_rejects_geometry_unknown_nodes_and_injections():
    ir = _ir()
    ops = validate_operations({"operations": [
        {"op": "restore-style", "sourceKey": "hero-title", "property": "textShadow",
         "value": "0 0 24px rgba(167,139,250,.65)"},
        # запрещено: геометрия
        {"op": "restore-style", "sourceKey": "hero-title", "property": "width", "value": 999},
        {"op": "set-frame", "sourceKey": "hero-title", "frame": {"x": 0}},
        # запрещено: несуществующий узел
        {"op": "restore-style", "sourceKey": "does-not-exist", "property": "opacity", "value": 0.5},
        # запрещено: инъекция в CSS
        {"op": "restore-style", "sourceKey": "hero-title", "property": "filter",
         "value": "url(http://evil/x.svg)"},
        {"op": "restore-style", "sourceKey": "hero-title", "property": "color", "value": "red; content:'x'"},
    ]}, ir)
    assert ops == [{"op": "restore-style", "sourceKey": "hero-title",
                    "property": "textShadow", "value": "0 0 24px rgba(167,139,250,.65)"}]


def test_apply_never_touches_geometry():
    ir = _ir()
    patched = apply_operations(ir, [
        {"op": "restore-style", "sourceKey": "hero-title", "property": "textShadow", "value": "0 0 8px #fff"},
        {"op": "pin-children", "sourceKey": "root"},
    ])
    title = patched["tree"][0]["children"][0]
    original = ir["tree"][0]["children"][0]
    assert title["style"]["textShadow"] == "0 0 8px #fff"
    assert title["frame"]["x"] == original["frame"]["x"]
    assert title["frame"]["width"] == original["frame"]["width"]
    # pin-children закрепляет детей по уже измеренным кадрам
    assert patched["tree"][0]["frame"]["layout"] == "free"
    assert title["frame"]["absolute"] is True
    # исходный IR не мутирован
    assert "textShadow" not in original.get("style", {})


def test_improvement_is_accepted():
    scores = iter([80.0, 93.0])
    def measure(_ir): return next(scores)
    def propose(_m): return json.dumps({"hypothesis": "glow lost", "operations": [
        {"op": "restore-style", "sourceKey": "hero-title", "property": "textShadow", "value": "0 0 8px #fff"}]})
    result = repair_block(_ir(), block_name="hero", viewport="desktop",
                          report_viewport={**_report(), "region_diffs": [{"region": [0, 1], "mismatch_pct": 42.0}]},
                          measure=measure, propose=propose)
    assert result["gain"] == 13.0
    assert len(result["applied"]) == 1
    assert result["ir"]["tree"][0]["children"][0]["style"]["textShadow"] == "0 0 8px #fff"


def test_a_worse_proposal_is_rolled_back():
    """Ключевая гарантия: модель не может ухудшить результат."""
    scores = iter([90.0, 61.0])
    def measure(_ir): return next(scores)
    def propose(_m): return json.dumps({"operations": [
        {"op": "restore-style", "sourceKey": "hero-title", "property": "opacity", "value": 0.1}]})
    result = repair_block(_ir(), block_name="hero", viewport="desktop",
                          report_viewport={**_report(), "region_diffs": [{"region": [0, 1], "mismatch_pct": 42.0}]},
                          measure=measure, propose=propose)
    assert result["applied"] == []
    assert len(result["rejected"]) == 1
    assert result["similarity"] == 90.0
    assert result["ir"]["tree"][0]["children"][0]["style"].get("opacity") is None


def test_a_marginal_gain_is_not_worth_a_change():
    scores = iter([90.0, 90.05])
    def measure(_ir): return next(scores)
    def propose(_m): return json.dumps({"operations": [
        {"op": "restore-style", "sourceKey": "hero-title", "property": "letterSpacing", "value": 0.2}]})
    result = repair_block(_ir(), block_name="hero", viewport="desktop",
                          report_viewport={**_report(), "region_diffs": [{"region": [0, 1], "mismatch_pct": 42.0}]},
                          measure=measure, propose=propose)
    assert result["applied"] == []


def test_broken_model_output_is_survivable():
    def measure(_ir): return 90.0
    for raw in ("not json at all", "{}", json.dumps({"operations": "nope"}), ""):
        result = repair_block(_ir(), block_name="hero", viewport="desktop",
                              report_viewport={**_report(), "region_diffs": [{"region": [0, 1], "mismatch_pct": 42.0}]},
                              measure=measure, propose=lambda _m, r=raw: r)
        assert result["applied"] == []
        assert result["similarity"] == 90.0


def test_missing_baseline_stops_the_loop():
    calls = []
    result = repair_block(_ir(), block_name="hero", viewport="desktop",
                          report_viewport=_report(),
                          measure=lambda _ir: None,
                          propose=lambda m: calls.append(m) or "{}")
    assert result["applied"] == [] and calls == []
    assert "unavailable" in result["reason"]
