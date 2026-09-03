"""qualitygate free-overlap: наложения и выход за границы во free-раскладке."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qualitygate


def _section(children, layout="free", width=1200, height=400):
    return {"version": "1.1", "tokens": {}, "tree": [{
        "id": "s", "type": "composition", "variant": "free",
        "frame": {"width": width, "height": height, "layout": layout},
        "children": children,
    }]}


def _violations(ir):
    return [v for v in qualitygate.check(ir, rules=[qualitygate.RULES_BY_ID["free-overlap"]])]


def test_overlapping_children_are_reported_once_per_pair():
    ir = _section([
        {"type": "rect", "frame": {"x": 0, "y": 0, "width": 300, "height": 200}},
        {"type": "rect", "frame": {"x": 100, "y": 50, "width": 300, "height": 200}},   # ~44% перекрытие
        {"type": "rect", "frame": {"x": 700, "y": 0, "width": 200, "height": 200}},    # отдельно
    ])
    out = _violations(ir)
    assert len(out) == 1
    assert out[0]["path"] == "tree.0.children[1].frame" and "перекрывает tree.0.children[0]" in out[0]["message"]


def test_small_intentional_overlap_is_tolerated():
    ir = _section([
        {"type": "rect", "frame": {"x": 0, "y": 0, "width": 400, "height": 300}},
        {"type": "rect", "frame": {"x": 360, "y": 260, "width": 200, "height": 100}},  # ~4% — намеренный «сдвиг»
    ])
    assert _violations(ir) == []


def test_child_outside_parent_bounds_is_reported():
    ir = _section([{"type": "image", "frame": {"x": 1000, "y": 300, "width": 400, "height": 200}}])
    out = _violations(ir)
    assert len(out) == 2
    assert any("ширину родителя" in v["message"] for v in out)
    assert any("высоту родителя" in v["message"] for v in out)


def test_auto_layout_parent_is_ignored():
    ir = _section([
        {"type": "rect", "frame": {"x": 0, "y": 0, "width": 300, "height": 200}},
        {"type": "rect", "frame": {"x": 0, "y": 0, "width": 300, "height": 200}},
    ], layout="row")
    assert _violations(ir) == []


def test_nested_free_frames_are_checked():
    ir = _section([{
        "type": "frame", "frame": {"x": 0, "y": 0, "width": 600, "height": 300, "layout": "free"},
        "children": [
            {"type": "text", "text": "a", "frame": {"x": 0, "y": 0, "width": 200, "height": 100}},
            {"type": "text", "text": "b", "frame": {"x": 20, "y": 10, "width": 200, "height": 100}},
        ],
    }])
    out = _violations(ir)
    assert len(out) == 1 and out[0]["path"].startswith("tree.0.children[0].children[1]")
