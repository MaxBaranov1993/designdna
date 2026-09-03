"""sanitize_generated_ir: обёртка документа и артборд 1440; ir_render: список
семейств без @font-face для повтора рендера с подменой."""
from __future__ import annotations

import ir_render
from ir.migrate import GENERATED_ARTBOARD_WIDTH, sanitize_generated_ir


def _doc() -> dict:
    return {"version": "1.1", "tokens": {}, "tree": [{"type": "section", "children": []}]}


def test_unwraps_single_wrapped_document():
    out = sanitize_generated_ir({"designIR": _doc()})
    assert out["tree"] and out["version"] == "1.1"
    assert "designIR" not in out


def test_keeps_root_when_tree_present():
    out = sanitize_generated_ir(_doc())
    assert out["tree"] == _doc()["tree"]


def test_ambiguous_wrapper_is_left_alone():
    out = sanitize_generated_ir({"a": _doc(), "b": _doc()})
    assert "tree" not in out


def test_generated_artboard_defaults_to_1440_and_keeps_explicit():
    assert sanitize_generated_ir(_doc())["frame"]["width"] == GENERATED_ARTBOARD_WIDTH
    explicit = dict(_doc(), frame={"width": 1200, "layout": "free"})
    assert sanitize_generated_ir(explicit)["frame"] == {"width": 1200, "layout": "free"}


def test_undeclared_families_parsed_from_readiness_errors():
    problems = [
        'шрифт "roboto slab" недоступен офлайн: добавьте локальный шрифт (meta.fontFaces, /fonts/<имя>) вместо внешнего каталога',
        "render attempted network access: https://x",
        'шрифт "Golos Text" недоступен офлайн: …',
    ]
    assert ir_render._undeclared_families(problems) == {"roboto slab", "Golos Text"}
    assert ir_render._undeclared_families([]) == set()
