"""qualitygate DS-lint: цвета/шрифты только из токенов, текст по ролям типографики.

Закрывает дрейф, который виден у AI-редакторов на многих экранах: «почти
такой же» цвет вне палитры, третий шрифт, line-height 1.30 у одного абзаца и
1.35 у соседнего. Точные копии (source-block, componentRef, editable:false)
правила не трогают.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qualitygate

TOKENS = {
    "mode": "light",
    "color": {"primary": "#2f4bd9", "background": "#ffffff", "surface": "#f4f5f7",
              "text": "#111318", "textMuted": "#5d6270", "border": "#e2e4ea"},
    "font": {"display": {"family": "Manrope", "weight": 700},
             "body": {"family": "Inter", "weight": 400}, "scale": "default"},
    "radius": {"card": "md", "button": "md", "input": "md"},
    "spacing": {"section": "md", "container": "default"},
    "shadow": "sm",
    "v2": {
        "color": {"bg": "#ffffff", "bg2": "#f4f5f7", "surface": "#ffffff", "surface2": "#eceef3",
                  "ink": "#111318", "ink2": "#2a2e38", "inkMuted": "#5d6270", "line": "#e2e4ea",
                  "accent": "#2f4bd9", "accentInk": "#ffffff", "accent2": "#0e6e6a"},
        "type": {
            "families": {"display": {"family": "Manrope", "stack": "Manrope, sans-serif", "weight": 700},
                         "body": {"family": "Inter", "stack": "Inter, sans-serif", "weight": 400}},
            "base": 16, "ratio": 1.25,
            "roles": {
                "display": {"size": 60, "lineHeight": 1.02, "tracking": -0.03, "weight": 700},
                "h1": {"size": 46, "lineHeight": 1.1, "tracking": -0.02, "weight": 700},
                "h2": {"size": 30, "lineHeight": 1.15, "tracking": -0.01, "weight": 700},
                "h3": {"size": 20, "lineHeight": 1.2, "tracking": 0, "weight": 600},
                "lead": {"size": 19, "lineHeight": 1.5, "tracking": 0, "weight": 400},
                "body": {"size": 16, "lineHeight": 1.5, "tracking": 0, "weight": 400},
                "small": {"size": 13, "lineHeight": 1.5, "tracking": 0, "weight": 400},
                "eyebrow": {"size": 12, "lineHeight": 1.2, "tracking": 0.12, "weight": 600},
            },
        },
    },
}


def _ir(children, section_type="composition", **section_extra):
    sec = {"id": "s", "type": section_type, "variant": "free",
           "frame": {"width": 1200, "height": 400, "layout": "free"}, "children": children}
    sec.update(section_extra)
    return {"version": "1.1", "tokens": copy.deepcopy(TOKENS), "tree": [sec]}


def _rules(*ids):
    return [qualitygate.RULES_BY_ID[i] for i in ids]


def test_off_palette_color_is_reported_with_nearest_token_and_snapped_when_close():
    ir = _ir([
        {"type": "text", "text": "a", "style": {"color": "#121419"}},   # почти ink
        {"type": "text", "text": "b", "style": {"color": "#111318"}},   # ровно ink
        {"type": "rect", "fill": "#2f4bd9aa"},                          # токен с alpha — ок
        {"type": "rect", "fill": "#2e4ad8cc"},                          # дрейф accent с alpha
    ])
    out = qualitygate.check(ir, rules=_rules("token-color"))
    assert [v["path"] for v in out] == ["tree.0.children.0.style.color", "tree.0.children.3.fill"]
    assert all(v["severity"] == "warning" for v in out)
    assert "tokens.color.text" in out[0]["message"] or "tokens.v2.color.ink" in out[0]["message"]

    fixed, journal = qualitygate.autofix(ir)
    assert fixed["tree"][0]["children"][0]["style"]["color"] == "#111318"
    assert fixed["tree"][0]["children"][3]["fill"] == "#2f4bd9cc"  # alpha сохранена
    assert len([j for j in journal if j.startswith("rule token-color")]) == 2
    assert qualitygate.check(fixed, rules=_rules("token-color")) == []


def test_far_color_is_only_reported_unless_strict_tokens():
    ir = _ir([{"type": "rect", "fill": "#ff0000"}])  # красного в палитре нет
    assert len(qualitygate.check(ir, rules=_rules("token-color"))) == 1
    soft, _ = qualitygate.autofix(ir)
    assert soft["tree"][0]["children"][0]["fill"] == "#ff0000"
    strict, journal = qualitygate.autofix(ir, strict_tokens=True)
    assert strict["tree"][0]["children"][0]["fill"] != "#ff0000"
    assert any("token-color" in j for j in journal)


def test_exact_copies_are_skipped():
    drift = {"type": "text", "text": "x", "style": {"color": "#121419", "fontFamily": "Comic Sans"}}
    source = _ir([copy.deepcopy(drift)], section_type="source-block")
    assert qualitygate.check(source, rules=_rules("token-color", "token-font")) == []
    pinned = _ir([{"type": "card", "sourceMeta": {"kind": "dom", "componentRef": {
        "systemId": "ds-1", "revision": 1, "componentKey": "k", "masterHash": "sha256:" + "0" * 64}},
        "children": [copy.deepcopy(drift)]}])
    assert qualitygate.check(pinned, rules=_rules("token-color", "token-font")) == []
    locked = _ir([dict(drift, editable=False)])
    assert qualitygate.check(locked, rules=_rules("token-color", "token-font")) == []


def test_foreign_font_family_is_reported_and_stripped():
    ir = _ir([
        {"type": "heading", "level": 2, "text": "h", "style": {"fontFamily": "'Manrope', sans-serif"}},
        {"type": "text", "text": "t", "style": {"fontFamily": "Comic Sans MS, cursive", "color": "#111318"}},
    ])
    out = qualitygate.check(ir, rules=_rules("token-font"))
    assert [v["path"] for v in out] == ["tree.0.children.1.style.fontFamily"]
    assert "comic sans ms" in out[0]["message"]
    fixed, journal = qualitygate.autofix(ir)
    assert "fontFamily" not in fixed["tree"][0]["children"][1]["style"]
    assert fixed["tree"][0]["children"][1]["style"]["color"] == "#111318"
    assert fixed["tree"][0]["children"][0]["style"]["fontFamily"].startswith("'Manrope'")
    assert any("token-font" in j for j in journal)


def test_explicit_type_role_wins_over_inline_overrides():
    ir = _ir([
        {"type": "text", "typeRole": "body", "text": "a", "style": {"fontSize": 16, "lineHeight": 1.3, "fontWeight": 500}},
        {"type": "text", "typeRole": "body", "text": "b", "style": {"fontSize": 16, "lineHeight": 1.5, "fontWeight": 400}},
        {"type": "text", "typeRole": "eyebrow", "text": "c", "style": {"letterSpacing": 0.5}},  # 0.12em*12px = 1.44px
    ])
    out = qualitygate.check(ir, rules=_rules("type-role-drift"))
    paths = [v["path"] for v in out]
    assert paths == ["tree.0.children.0.style.lineHeight", "tree.0.children.0.style.fontWeight",
                     "tree.0.children.2.style.letterSpacing"]
    fixed, journal = qualitygate.autofix(ir)
    assert fixed["tree"][0]["children"][0]["style"] == {"fontSize": 16}
    assert fixed["tree"][0]["children"][2]["style"] == {}
    assert qualitygate.check(fixed, rules=_rules("type-role-drift")) == []
    assert len([j for j in journal if "type-role-drift" in j]) == 3


def test_heading_level_role_is_reported_but_not_autofixed():
    ir = _ir([{"type": "heading", "level": 1, "text": "h", "style": {"fontSize": 72}}])
    out = qualitygate.check(ir, rules=_rules("type-role-drift"))
    assert len(out) == 1 and "h1" in out[0]["message"]
    fixed, _ = qualitygate.autofix(ir)
    assert fixed["tree"][0]["children"][0]["style"]["fontSize"] == 72


def test_warnings_do_not_fail_the_gate():
    ir = _ir([{"type": "rect", "fill": "#ff0000"}])
    out = qualitygate.check(ir, rules=_rules("token-color"))
    assert out and qualitygate.passed(out)
    assert not qualitygate.passed(out + [{"rule": "x", "severity": "error", "path": "", "message": ""}])


def test_documents_without_tokens_are_untouched():
    ir = {"version": "1.1", "tokens": {}, "tree": [{"id": "s", "type": "composition",
          "children": [{"type": "text", "text": "a", "style": {"color": "#ff0000", "fontFamily": "Zapf"}}]}]}
    assert qualitygate.check(ir, rules=_rules("token-color", "token-font", "type-role-drift")) == []
    fixed, journal = qualitygate.autofix(ir)
    assert fixed["tree"][0]["children"][0]["style"]["color"] == "#ff0000"
    assert not [j for j in journal if "token-" in j or "type-role" in j]
