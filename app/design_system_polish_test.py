from __future__ import annotations

import copy

from design_system import polish


def _master() -> dict:
    return {"version": "1.1", "tokens": {}, "tree": [{
        "type": "frame", "sourceKey": "root",
        "frame": {"x": 0, "y": 0, "width": 300, "height": 100, "layout": "free"},
        "children": [
            {"type": "text", "sourceKey": "price", "text": "$3K",
             "frame": {"x": 10, "y": 20, "width": 18, "height": 24},
             "style": {"fontSize": 24, "overflow": "hidden"}},
            {"type": "text", "sourceKey": "period", "text": "/ month",
             "frame": {"x": 24, "y": 20, "width": 80, "height": 24},
             "style": {"fontSize": 16}},
        ],
    }]}


def test_lint_finds_overflow_clip_and_overlap():
    defects = polish.static_lint(_master())
    kinds = {item["kind"] for item in defects}
    assert {"overflow", "clip", "overlap"} <= kinds
    assert all({"path", "kind", "px", "viewport"} <= set(item) for item in defects)


def test_autofix_expands_text_and_honours_fidelity_gate():
    component = {"masterIr": _master(), "fidelity": {"gate": {"passed": True}},
                 "sourceRef": {}}
    before = copy.deepcopy(component["masterIr"])
    result = polish.polish_component(component)
    assert result["changed"] and len(result["defectsAfter"]) < len(result["defectsBefore"])
    assert component["masterIr"]["tree"][0]["children"][0]["frame"]["width"] > 18
    assert component["polish"]["before"] == before

    rejected = {"masterIr": _master(), "fidelity": {"gate": {"passed": False}}}
    result = polish.polish_component(rejected)
    assert not result["changed"] and rejected["masterIr"] == _master()


def test_rollback_restores_exact_master():
    component = {"masterIr": _master(), "fidelity": {"gate": {"passed": True}},
                 "sourceRef": {}}
    original = copy.deepcopy(component["masterIr"])
    assert polish.polish_component(component)["changed"]
    assert polish.rollback_component(component)
    assert component["masterIr"] == original
    assert "polish" not in component and "polish" not in component["fidelity"]
