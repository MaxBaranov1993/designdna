"""Section shell: the measured page grid a generated section must sit in."""
from __future__ import annotations

from design_system import builder, compiler
from design_system.section_shell import measure_section_shell, shell_prompt_payload

SOURCE = "https://example.test/"
MONO = "ui-monospace, Menlo, monospace"
SANS = "commissioner, sans-serif"


def _text(text: str, y: float, *, size: float, weight: int = 400, family: str = SANS, kind: str = "text", **style) -> dict:
    return {"type": kind, "text": text, "sourceKey": f"t/{text}",
            "style": {"fontFamily": family, "fontSize": size, "fontWeight": weight, "color": "#06111f", **style},
            "frame": {"absolute": True, "x": 56, "y": y, "width": 400, "height": size + 4}}


def _block(name: str, kind: str, x: float, y: float, width: float, height: float, children: list,
           padding=(68, 56, 68, 56), style: dict | None = None) -> dict:
    root = {"type": "source-block", "sourceKey": "root", "style": dict(style or {}),
            "frame": {"width": width, "height": height, "layout": "free", "padding": list(padding)},
            "children": children}
    meta = {"name": name, "pageRect": {"x": x, "y": y, "width": width, "height": height, "source": SOURCE},
            "pageBackground": "#fbf8f0"}
    return {"name": name, "kind": kind, "ir": {"version": "1.1", "meta": meta, "tokens": {}, "tree": [root]}}


def _site() -> list[dict]:
    eyebrow = {"size": 16, "weight": 700, "family": MONO, "textTransform": "uppercase", "letterSpacing": 1.28}
    card = {"type": "card", "sourceKey": "card",
            "style": {"background": "#f7f2e8", "borderColor": "#06111f29", "borderWidth": 1, "borderRadius": 8},
            "frame": {"absolute": True, "x": 56, "y": 102, "width": 340, "height": 180},
            "children": [_text("Card title", 20, size=22, weight=700), _text("Body copy of the card " * 4, 60, size=17)]}
    button = {"type": "button", "text": "Book a call", "sourceKey": "cta",
              "style": {"color": "#cbff16", "fontFamily": SANS, "fontSize": 15, "fontWeight": 820,
                        "borderColor": "#06111f", "borderWidth": 2, "borderRadius": 5},
              "frame": {"absolute": True, "x": 56, "y": 300, "width": 270, "height": 49},
              "children": [{"type": "rect", "sourceKey": "cta::bg",
                            "style": {"backgroundImage": "linear-gradient(135deg, #040a0f, #071622)"}}]}
    return [
        _block("header", "header", 130, 0, 1180, 70, [_text("Logo", 10, size=14, weight=700)], padding=(0, 56, 0, 56)),
        _block("hero", "hero", 130, 70, 1180, 420, [_text("Big display title", 34, size=54, weight=880, kind="heading"), button],
               padding=(34, 43, 40, 43)),
        _block("position", "features", 130, 490, 1180, 320, [_text("MY POSITION", 68, **eyebrow), card]),
        _block("services", "features", 130, 810, 1180, 400, [_text("WHAT I DO", 68, **eyebrow), dict(card, sourceKey="card2")]),
        _block("footer", "footer", 173, 1210, 1094, 110, [_text("Footer", 24, size=13)], padding=(24, 0, 28, 0)),
    ]


def test_shell_measures_column_rhythm_and_section_anatomy() -> None:
    shell = measure_section_shell(_site())
    assert shell["pageWidth"] == 1440, "2·x + width of centred sections recovers the capture width"
    assert shell["column"]["x"] == 130 and shell["column"]["width"] == 1180
    assert shell["contentInset"] == 56 and shell["content"] == {"x": 186, "width": 1068}
    assert shell["sectionPadding"] == {"top": 68, "bottom": 68}
    assert shell["sectionRoot"].startswith("transparent"), "section roots do not paint their own surface"
    assert shell["pageBackground"] == "#fbf8f0"
    eyebrow = shell["eyebrow"]
    assert eyebrow["fontFamily"] == "ui-monospace" and eyebrow["textTransform"] == "uppercase"
    assert eyebrow["sections"] == 2 and eyebrow["gapBelow"] == 14  # 102 - (68 + 20)
    assert shell["headings"][0]["fontSize"] == 54, "display heading comes first"
    assert any(level["fontSize"] == 22 for level in shell["headings"])
    assert shell["surfaces"][0]["background"] == "#f7f2e8" and shell["surfaces"][0]["borderRadius"] == 8
    assert shell["buttons"][0]["background"].startswith("linear-gradient"), "gradient fill comes from the ::bg layer"
    assert shell["body"][0]["fontSize"] == 17


def test_new_section_root_puts_content_in_the_measured_column() -> None:
    payload = shell_prompt_payload(measure_section_shell(_site()))
    assert payload["newSectionRoot"] == {"width": 1440, "padding": [68, 186, 68, 186], "background": "none"}


def test_no_page_rects_means_no_shell() -> None:
    blocks = _site()
    for block in blocks:
        block["ir"]["meta"].pop("pageRect")
    assert measure_section_shell(blocks) == {}
    assert shell_prompt_payload({}) == {}


def test_builder_stores_shell_and_compiler_emits_required_line() -> None:
    foundations = builder._foundations_from_tokens({}, ["desktop"], _site())
    assert foundations["sectionShell"]["column"]["width"] == 1180
    context = {"foundations": foundations, "constraints": {"usageMode": "extend"}, "components": [],
               "systemRef": {"systemId": "ds", "revision": 1}}
    compiled = compiler.compile_profile(context, brief="Contact form", token_budget=compiler.default_budget("extend"))
    assert "foundations.section-shell" in compiled["includedRuleIds"]
    assert "SECTION SHELL" in compiled["promptBlock"] and '"newSectionRoot"' in compiled["promptBlock"]
