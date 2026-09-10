"""Правило invisible-text: цвет текста, совпадающий с фоном, чинится детерминированно."""
import copy
import json

import qualitygate
from api import quality
from test_qualitygate import BASE_IR


def _ir():
    ir = copy.deepcopy(BASE_IR)
    ir["version"] = "1.1"
    ir["tokens"]["color"] = {**ir["tokens"]["color"], "background": "#0a0a0e", "surface": "#0a0a0e",
                             "text": "#f2f0ea", "textMuted": "#9d9aab", "primary": "#5b6cff"}
    ir["tree"] = [{
        "id": "s", "type": "composition", "variant": "x", "props": {"background": "background"},
        "children": [
            {"type": "text", "text": "Войти →", "style": {"color": "#0A0A0E"}},
            {"type": "card", "style": {"background": "#5b6cff"}, "children": [
                {"type": "text", "text": "на плашке", "style": {"color": "#5b6cff"}},
                {"type": "text", "text": "нормальный", "style": {"color": "#ffffff"}},
            ]},
            {"type": "text", "text": "обычный", "style": {"color": "#f2f0ea"}},
        ],
    }]
    return ir


def test_invisible_text_is_detected_against_the_effective_background():
    rule = next(r for r in qualitygate.RULES if r["id"] == "invisible-text")
    violations = rule["check"](_ir())
    assert [v["path"] for v in violations] == ["tree.0.children.0.style.color", "tree.0.children.1.children.0.style.color"]
    assert rule["severity"] == qualitygate.SEVERITY_ERROR


def test_invisible_text_fix_uses_the_document_text_token():
    fixed, journal = qualitygate.autofix(_ir(), rules=[r for r in qualitygate.RULES if r["id"] == "invisible-text"])
    section = fixed["tree"][0]
    assert section["children"][0]["style"]["color"] == "#f2f0ea"
    assert section["children"][1]["children"][0]["style"]["color"] == "#f2f0ea"
    assert section["children"][1]["children"][1]["style"]["color"] == "#ffffff"
    assert len(journal) == 2 and all("invisible-text" in line for line in journal)
    assert not next(r for r in qualitygate.RULES if r["id"] == "invisible-text")["check"](fixed)


def test_repair_output_gets_the_same_fix():
    repaired, error = quality._parse_quality_repair(json.dumps(_ir(), ensure_ascii=False))
    assert error is None
    assert repaired["tree"][0]["children"][0]["style"]["color"] == "#f2f0ea"
