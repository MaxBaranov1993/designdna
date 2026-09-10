"""Frame секции-композиции после санитайзера: рельс контента, раскладка — в дочернем frame."""
from copy import deepcopy

from ir import sanitize_generated_ir


def _section(frame, children):
    return {"id": "offer", "type": "composition", "variant": "offer-form",
            "props": {"background": "background", "density": "airy"}, "frame": frame, "children": children}


def _ir(section):
    return {"version": "1.1", "tokens": {}, "tree": [section]}


def test_layout_on_the_section_moves_into_a_child_frame() -> None:
    children = [{"type": "text", "text": "eyebrow"}, {"type": "heading", "level": 1, "text": "Title"}]
    original = _ir(_section({"layout": "auto", "direction": "column", "gap": 28, "padding": [104, 24, 72, 24],
                             "align": "center", "width": "fill", "contentMaxWidth": 1040}, children))
    snapshot = deepcopy(original)
    out = sanitize_generated_ir(original)
    section = out["tree"][0]
    assert section["frame"] == {"contentMaxWidth": 1040}
    assert len(section["children"]) == 1
    wrapper = section["children"][0]
    assert wrapper["type"] == "frame"
    assert wrapper["frame"] == {"layout": "auto", "direction": "column", "gap": 28, "align": "center", "width": "fill"}
    assert [child["type"] for child in wrapper["children"]] == ["text", "heading"]
    assert original == snapshot  # вход не мутируется


def test_row_layout_keeps_direction_and_wrap() -> None:
    out = sanitize_generated_ir(_ir(_section({"direction": "row", "gap": 24, "wrap": True, "justify": "center"},
                                             [{"type": "card"}, {"type": "card"}])))
    section = out["tree"][0]
    assert "frame" not in section
    assert section["children"][0]["frame"] == {"layout": "auto", "direction": "row", "gap": 24, "justify": "center",
                                               "wrap": True, "width": "fill"}


def test_rail_only_free_and_frameless_sections_are_untouched() -> None:
    rail = _section({"contentMaxWidth": 1120, "contentGutter": 24}, [{"type": "text", "text": "a"}])
    free = _section({"layout": "free", "height": 480, "direction": "column"},
                    [{"type": "text", "text": "a", "frame": {"x": 10, "y": 10}}])
    bare = {k: v for k, v in _section({}, [{"type": "text", "text": "a"}]).items() if k != "frame"}
    out = sanitize_generated_ir({"version": "1.1", "tokens": {}, "tree": [rail, free, bare]})
    assert out["tree"][0]["frame"] == {"contentMaxWidth": 1120, "contentGutter": 24}
    assert out["tree"][0]["children"][0]["type"] == "text"
    assert out["tree"][1]["frame"] == {"layout": "free", "height": 480, "direction": "column"}
    assert out["tree"][1]["children"][0]["type"] == "text"
    assert "frame" not in out["tree"][2] and out["tree"][2]["children"][0]["type"] == "text"


def test_stray_width_without_layout_is_dropped_without_wrapping() -> None:
    out = sanitize_generated_ir(_ir(_section({"width": "fill", "padding": [64, 24], "contentMaxWidth": 900},
                                             [{"type": "text", "text": "a"}])))
    section = out["tree"][0]
    assert section["frame"] == {"contentMaxWidth": 900}
    assert section["children"] == [{"type": "text", "text": "a"}]


def test_semantic_sections_keep_their_frames() -> None:
    hero = {"id": "hero", "type": "hero", "variant": "split", "props": {"heading": "Hi"},
            "frame": {"layout": "auto", "direction": "row", "gap": 24}}
    out = sanitize_generated_ir({"version": "1.1", "tokens": {}, "tree": [hero]})
    assert out["tree"][0]["frame"] == {"layout": "auto", "direction": "row", "gap": 24}


def test_design_brief_density_words_map_to_section_density() -> None:
    """Арт-направление говорит airy/balanced/dense, схема секции ждёт tight/normal/airy."""
    sections = [
        _section({"contentMaxWidth": 1120}, [{"type": "text", "text": "a"}]),
        _section({"contentMaxWidth": 1120}, [{"type": "text", "text": "b"}]),
        _section({"contentMaxWidth": 1120}, [{"type": "text", "text": "c"}]),
        _section({"contentMaxWidth": 1120}, [{"type": "text", "text": "d"}]),
    ]
    for section, density in zip(sections, ("balanced", "dense", "airy", "wild")):
        section["props"]["density"] = density
    out = sanitize_generated_ir({"version": "1.1", "tokens": {}, "tree": sections})
    assert [section["props"]["density"] for section in out["tree"]] == ["normal", "tight", "airy", "wild"]
