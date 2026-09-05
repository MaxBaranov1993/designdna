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


def test_expansion_that_pushes_sibling_outside_parent_is_rejected():
    master = _master()
    root = master["tree"][0]
    root["frame"]["width"] = 110
    root["children"][1]["frame"] = {"x": 30, "y": 20, "width": 80, "height": 24}
    component = {"masterIr": master, "fidelity": {"gate": {"passed": True}}}
    original = copy.deepcopy(master)

    result = polish.polish_component(component)

    assert not result["changed"]
    assert component["masterIr"] == original
    assert "no-safe-fix" in component["fidelity"]["polish"]["rejected"]


def test_escape_is_reported_by_lint():
    master = _master()
    master["tree"][0]["children"][1]["frame"]["x"] = 250
    defects = polish.static_lint(master)
    assert any(d["path"] == "period" and d["kind"] == "escape" for d in defects)


def test_hidden_viewport_clone_and_duplicate_kinds_are_not_counted():
    master = _master()
    clone = copy.deepcopy(master["tree"][0]["children"][0])
    clone["responsive"] = {"desktop": {"visible": False}}
    master["tree"][0]["children"].append(clone)
    defects = polish.static_lint(master)
    keys = [(d["path"], d["kind"]) for d in defects]
    assert len(keys) == len(set(keys))
    assert keys.count(("price", "overflow")) == 1


def test_candidate_with_new_defect_rolls_back(monkeypatch):
    component = {"masterIr": _master(), "fidelity": {"gate": {"passed": True}}}
    original = copy.deepcopy(component["masterIr"])
    calls = {"count": 0}

    def lint(_master_ir, **_kwargs):
        calls["count"] += 1
        before = [{"path": "price", "kind": "overflow", "px": 5, "viewport": "desktop"}]
        return before if calls["count"] == 1 else [
            {"path": "period", "kind": "escape", "px": 2, "viewport": "desktop"}]

    monkeypatch.setattr(polish, "lint_master", lint)
    result = polish.polish_component(component)
    assert not result["changed"] and component["masterIr"] == original
    assert {"new-defect", "escape"} <= set(component["fidelity"]["polish"]["rejected"])
