"""Верность дизайн-системе после генерации: мелкие лейблы, моно-шрифт, пилюли и frame секций."""
import json
from copy import deepcopy

import art_direction
import qualitygate
import server
from design_system import resolver, store, style_review


def test_min_font_rule_respects_a_lower_floor() -> None:
    ir = {"tree": [{"type": "composition", "variant": "x", "children": [
        {"type": "text", "text": "DAY 1", "style": {"fontSize": 10}},
        {"type": "text", "text": "tiny", "style": {"fontSize": 7}},
    ]}]}
    fixed, journal = qualitygate.autofix(ir, rules=[qualitygate.min_font_rule(9)])
    assert [child["style"]["fontSize"] for child in fixed["tree"][0]["children"]] == [10, 9]
    assert len(journal) == 1 and "7 -> 9" in journal[0]
    default_fixed, _ = qualitygate.autofix(ir, rules=[r for r in qualitygate.RULES if r["id"] == "min-font-size"])
    assert [child["style"]["fontSize"] for child in default_fixed["tree"][0]["children"]] == [12, 12]
    assert qualitygate.min_font_rule(3)["description"].endswith(f"{qualitygate.MIN_FONT_SIZE_FLOOR}px")
    assert qualitygate.min_font_rule(9)["check"](ir) == [{"path": "tree.0.children.1.style.fontSize",
                                                          "message": "fontSize 7px < 9px"}]


def test_label_size_floor_follows_the_measured_scale() -> None:
    assert style_review.label_size_floor({"typography": {"scale": {"display": 66, "body": 16, "size27": 9}}}) == 9
    assert style_review.label_size_floor({"typography": {"scale": {"display": 66, "body": 16, "small": 11}}}) == 11
    assert style_review.label_size_floor({"typography": {"scale": {"display": 66, "body": 16, "size9": 7}}}) == 9
    assert style_review.label_size_floor({"typography": {"scale": {"display": 66, "body": 16}}}) == 0
    assert style_review.label_size_floor({}) == 0


def test_pill_radius_is_not_off_system_when_the_scale_has_pills() -> None:
    context = {"constraints": {"usageMode": "extend"}, "foundations": {"radii": [0, 8, 16, 99]},
               "styleGuide": {"tokens": {"radius-button": 999}}, "components": []}
    ir = {"tree": [{"type": "composition", "variant": "x", "children": [
        {"type": "button", "text": "Go →", "style": {"borderRadius": 999}},
        {"type": "card", "style": {"borderRadius": 24}},
    ]}]}
    messages = [w["message"] for w in resolver.validate_generation(ir, context)["warnings"]
                if w["code"] == "off-system-radius"]
    assert messages == ["Радиус 24 вне шкалы системы"]
    flat = {**context, "foundations": {"radii": [0, 8, 16]}, "styleGuide": {}}
    flat_messages = [w for w in resolver.validate_generation(ir, flat)["warnings"] if w["code"] == "off-system-radius"]
    assert len(flat_messages) == 2
    token_only = {**context, "foundations": {"radii": [0, 8, 16]}}
    assert len([w for w in resolver.validate_generation(ir, token_only)["warnings"]
                if w["code"] == "off-system-radius"]) == 1


MONO_FACE = {"family": "JetBrains Mono", "weight": "400", "style": "normal", "url": "/fonts/jetbrains-mono-400.woff2"}
DISPLAY_FACE = {"family": "Hanken Grotesk", "weight": "700", "style": "normal", "url": "/fonts/hanken-700.woff2"}


def _document() -> dict:
    return {
        "id": "ds-labels", "name": "Labels kit", "revision": 1, "contentHash": "published-hash",
        "styleGuide": {},
        "components": {
            "step-label": {
                "componentKey": "step-label", "name": "Step label", "category": "content",
                "origin": "user", "confirmed": True,
                "masterIr": {"version": "1.1", "meta": {"fontFaces": [MONO_FACE, DISPLAY_FACE, dict(MONO_FACE)]},
                             "tree": [{"type": "text", "text": "DAY 1",
                                       "style": {"fontFamily": "JetBrains Mono", "fontSize": 10}}]},
            },
        },
        "foundations": {
            "colors": {"semantic": {"primary": "#5b6cff", "secondary": "#5b6cff", "accent": "#9aa6ff",
                                    "background": "#0a0a0e", "surface": "#0a0a0e", "text": "#f2f0ea",
                                    "textMuted": "#9d9aab", "border": "#1b1b1f"}},
            "typography": {"families": ["Hanken Grotesk", "JetBrains Mono"],
                           "scale": {"display": 66, "body": 16, "size27": 9}, "weights": [400, 700],
                           "display": {"family": "Hanken Grotesk", "weight": 700},
                           "body": {"family": "Hanken Grotesk", "weight": 400}},
            "radii": [0, 16, 99], "radius": {"button": 999, "card": 16, "input": 0}, "spacing": {"space1": 8},
        },
    }


def test_font_faces_are_collected_from_masters_without_duplicates() -> None:
    faces = style_review.font_faces(_document())
    assert faces == [DISPLAY_FACE, MONO_FACE]  # порядок семейств как в typography.families, дубли сняты
    assert style_review.font_faces({"components": {}}) == []
    merged = style_review.merge_font_faces([MONO_FACE], faces)
    assert merged == [MONO_FACE, DISPLAY_FACE]
    assert style_review.merge_font_faces(None, faces, limit=1) == [DISPLAY_FACE]


def test_generate_keeps_design_system_labels_fonts_pills_and_normalizes_section_frames(monkeypatch) -> None:
    document = _document()
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    raw = {
        "version": "1.1",
        "tokens": {"color": deepcopy(document["foundations"]["colors"]["semantic"]),
                   "font": {"display": {"family": "Hanken Grotesk", "weight": 700},
                            "body": {"family": "Hanken Grotesk", "weight": 400}}},
        "tree": [{"id": "steps", "type": "composition", "variant": "process-steps",
                  "props": {"background": "background", "density": "normal"},
                  "frame": {"layout": "auto", "direction": "column", "gap": 12, "padding": [64, 24], "align": "center"},
                  "children": [
                      {"type": "text", "text": "DAY 1", "style": {"fontFamily": "JetBrains Mono", "fontSize": 10}},
                      {"type": "heading", "level": 2, "text": "Заголовок шага"},
                      {"type": "button", "text": "Дальше →", "style": {"borderRadius": 999}},
                  ]}],
    }
    response = server.generate(server.GenerateReq(
        brief="Секция шагов процесса", count=1, rawOutputs=[json.dumps(raw, ensure_ascii=False)],
        designSystem={"systemId": "ds-labels", "revision": 1, "usageMode": "extend"},
    ))
    assert response["errors"] == []
    variant = response["variants"][0]
    section = variant["tree"][0]
    assert "padding" not in (section.get("frame") or {})
    wrapper = section["children"][0]
    assert wrapper["type"] == "frame" and wrapper["frame"]["gap"] == 12 and wrapper["frame"]["align"] == "center"
    label, _heading, button = wrapper["children"]
    assert label["style"]["fontSize"] == 10  # порог автофикса опущен до шкалы сайта
    assert label["style"]["fontFamily"] == "JetBrains Mono"  # моно-лейбл признан шрифтом системы
    assert button["style"]["borderRadius"] >= 50  # пилюля не «починена» до md
    assert variant["meta"]["fontFaces"] == [DISPLAY_FACE, MONO_FACE]
    journal = response["generationLog"]["variants"][0]["journal"]
    assert not any("min-font-size" in line or "token-font" in line for line in journal)
    assert not any(w["code"] == "off-system-radius" for w in response["designSystem"]["warnings"])
