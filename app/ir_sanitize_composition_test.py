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


def test_duplicate_section_heading_is_dropped_from_props() -> None:
    section = _section({"contentMaxWidth": 1120}, [
        {"type": "frame", "frame": {"layout": "auto", "direction": "column", "gap": 12}, "children": [
            {"type": "heading", "level": 2, "text": "Всё делаем за вас —  по шагам."},
            {"type": "text", "text": "Подзаголовок секции"},
        ]},
    ])
    section["props"].update({"heading": "Всё делаем за вас — по шагам.", "subheading": "Подзаголовок секции"})
    kept = _section({"contentMaxWidth": 1120}, [{"type": "text", "text": "другой текст"}])
    kept["props"]["heading"] = "Уникальный заголовок"
    out = sanitize_generated_ir({"version": "1.1", "tokens": {}, "tree": [section, kept]})
    assert "heading" not in out["tree"][0]["props"] and "subheading" not in out["tree"][0]["props"]
    assert out["tree"][1]["props"]["heading"] == "Уникальный заголовок"


def test_generated_layout_becomes_fluid_and_row_labels_hug() -> None:
    row = {"type": "frame", "frame": {"layout": "auto", "direction": "row", "gap": 10, "align": "center"}, "children": [
        {"type": "text", "text": "https://"},
        {"type": "input", "placeholder": "yourcompany.com", "frame": {"width": "fill"}},
        {"type": "button", "text": "Запустить →", "frame": {"width": "fill"}},
        {"type": "text", "text": "Довольно длинный пояснительный текст в ряду", "frame": {}},
    ]}
    form = {"type": "frame", "frame": {"layout": "auto", "direction": "column", "gap": 20, "width": 640}, "children": [row]}
    free = {"type": "frame", "frame": {"layout": "free", "height": 300}, "children": [
        {"type": "card", "frame": {"x": 10, "y": 10, "width": 500, "height": 100}},
        {"type": "text", "text": "ok", "frame": {"x": 0, "y": 0}},
    ]}
    master = {"type": "card", "frame": {"width": 840, "height": 345}, "sourceMeta": {"componentRef": {"componentKey": "list-item"}},
              "children": [{"type": "text", "text": "DAY 1", "frame": {"width": 60}}]}
    diptych = {"type": "frame", "frame": {"layout": "auto", "direction": "row", "gap": 48, "wrap": True}, "children": [
        {"type": "frame", "frame": {"layout": "auto", "direction": "column", "gap": 16, "width": 560},
         "children": [{"type": "heading", "level": 2, "text": "Колонка"}, {"type": "text", "text": "Цена"}]},
        {"type": "image", "imagePrompt": "x", "frame": {"width": 480}},
        {"type": "button", "text": "Подробнее →"},
    ]}
    out = sanitize_generated_ir({"version": "1.1", "tokens": {}, "tree": [
        _section({"contentMaxWidth": 1120}, [form, free, master, diptych])]})
    form_out, free_out, master_out, diptych_out = out["tree"][0]["children"]
    assert form_out["frame"]["width"] == "fill" and form_out["frame"]["maxWidth"] == 640
    prefix, field, button, long_text = form_out["children"][0]["children"]
    assert prefix["frame"] == {"width": "hug"}
    assert field["frame"] == {"width": "fill"}
    assert button["frame"] == {"width": "hug"}
    assert long_text["frame"] == {}  # длинный текст в ряду по-прежнему делит ширину
    assert free_out["children"][0]["frame"]["width"] == 500  # free-раскладка не трогается
    assert master_out["frame"]["width"] == 840  # точная копия мастера неприкосновенна
    # ряд без поля ввода: фиксированные ширины колонок и кнопка без ширины остаются как есть
    assert diptych_out["children"][0]["frame"]["width"] == 560
    assert diptych_out["children"][1]["frame"]["width"] == 480
    assert "frame" not in diptych_out["children"][2]
    assert diptych_out["children"][0]["children"][1] == {"type": "text", "text": "Цена"}
