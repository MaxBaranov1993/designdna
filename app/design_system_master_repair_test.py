"""Починка отклонённых мастеров: агент правит визуальные каналы, судья пересматривает.

Без Playwright и сети: рендер и обе модели подменены. Фальшивый судья смотрит на
тот же признак, что и живой — есть ли у рамки альфа; фальшивый чинильщик
возвращает одну операцию restore-style.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_system import document as dsdoc
from design_system import master_repair, master_review


def _png(width: int = 40, height: int = 20) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (20, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _master() -> dict:
    from design_system.builder import _tokens_for_ir, normalize_dna
    return {"version": "1.1", "tokens": _tokens_for_ir(normalize_dna({})), "tree": [{
        "type": "frame", "sourceKey": "field", "sourceMeta": {"kind": "dom", "componentBoundary": True},
        "frame": {"x": 0, "y": 0, "width": 240, "height": 60, "layout": "free"},
        "style": {"background": "#12141c", "borderColor": "#8fb6ff", "borderWidth": 1},
        "children": [{"type": "text", "text": "Sending Engine", "sourceKey": "field-label",
                      "frame": {"x": 12, "y": 20, "width": 200, "height": 20},
                      "style": {"color": "#ffffff", "fontWeight": 700}}],
    }]}


def _document(*, template: bool = False) -> dict:
    master = _master()
    fidelity = {"basis": "component-source-fidelity-harness", "requiredViewports": ["desktop"],
                "viewports": {"desktop": {"pixelSimilarity": 91.2, "paintCoverage": 99, "bboxP95": 1,
                                          "originError": 0, "unexplainedLosses": 0, "sizeMatch": True,
                                          "sourceGatePassed": True}},
                "status": "needs-review", "reasons": ["desktop: pixel similarity 91.2 < 95"]}
    comp = {"componentKey": "field", "name": "Field", "category": "form", "origin": "observed",
            "status": "needs-review", "confirmed": False, "masterIr": master, "fidelity": fidelity,
            "variants": {"default": {"masterRef": "self"}},
            "review": {"kind": "fidelity", "reasons": fidelity["reasons"]},
            "sourceRef": {"sourceKey": "field", "sourceRevisionHash": "rev", "evidenceKey": "ev1",
                          "masterHash": dsdoc.content_hash(master),
                          "bounds": {"x": 0, "y": 0, "width": 240, "height": 60},
                          "boundsByViewport": {"desktop": {"x": 0, "y": 0, "width": 240, "height": 60}}}}
    if template:
        comp["templateIr"] = dsdoc.preview_ir_for_master(master)
    return {
        "id": "ds-repair", "revision": 1, "status": "draft", "components": {},
        "reviewComponents": {"field-review": comp},
        "referenceAssets": {"ev1": {
            "referencePreviews": {"desktop": "data:image/png;base64," + base64.b64encode(_png(240, 60)).decode()},
            "blockSizes": {"desktop": {"width": 240, "height": 60}},
        }},
        "foundations": {}, "sourceRefs": [{"revisionHash": "rev"}],
    }


class _Studio:
    """Рендер + обе модели. Судья одобряет только полупрозрачную рамку."""

    def __init__(self, *, fix: bool = True, values: tuple[str, ...] = ("#8fb6ff33",)) -> None:
        self.fix = fix
        self.values = values
        self.rendered: list[dict] = []
        self.repair_prompts: list[str] = []
        self.vision_prompts: list[str] = []

    def render(self, page, comp, viewport):
        self.rendered.append(copy.deepcopy(comp))
        frame = comp['masterIr']['tree'][0]['frame']
        return _png(int(frame['width']), int(frame['height']))

    def _border(self) -> str:
        master = self.rendered[-1]["masterIr"] if self.rendered else {}
        node = (master.get("tree") or [{}])[0]
        return str((node.get("style") or {}).get("borderColor") or "")

    def vision(self, images, prompt):
        self.vision_prompts.append(prompt)
        assert len(images) == 2 and images[1].startswith("data:image/png")
        if len(self._border()) == 9:  # 8 hex-цифр → рамка снова полупрозрачная
            return json.dumps({"approved": True, "score": 96, "summary": "Совпадает", "defects": []})
        return json.dumps({"approved": False, "score": 71, "summary": "Рамка слишком яркая",
                           "defects": [{"severity": "major",
                                        "what": "bright border where the original is barely visible",
                                        "where": "field outline"}]})

    def repair(self, images, prompt):
        self.repair_prompts.append(prompt)
        assert len(images) == 2
        if not self.fix:
            return json.dumps({"operations": []})
        value = self.values[min(len(self.repair_prompts) - 1, len(self.values) - 1)]
        return json.dumps({"operations": [
            {"op": "restore-style", "sourceKey": "field", "property": "borderColor", "value": value}]})


def test_validate_operations_accepts_alpha_hex_and_drops_geometry():
    master = _master()
    ops = master_repair.validate_operations({"operations": [
        {"op": "restore-style", "sourceKey": "field", "property": "borderColor", "value": "#8FB6FF33"},
        {"op": "restore-style", "sourceKey": "field", "property": "borderWidth", "value": 1.5},
        {"op": "restore-style", "sourceKey": "field-label", "property": "fontWeight", "value": 400},
        {"op": "restore-style", "sourceKey": "field-label", "property": "color", "value": "#a8b0c0"},
        # мусор: чужой узел, геометрия, кадр, нечисловая ширина рамки, не-hex цвет
        {"op": "restore-style", "sourceKey": "ghost", "property": "color", "value": "#ffffff"},
        {"op": "restore-style", "sourceKey": "field", "property": "width", "value": 400},
        {"op": "restore-style", "sourceKey": "field", "property": "frame", "value": "0 0 10 10"},
        {"op": "restore-style", "sourceKey": "field", "property": "borderWidth", "value": "2px"},
        {"op": "restore-style", "sourceKey": "field", "property": "background", "value": "rgba(0,0,0,.5)"},
        {"op": "pin-children", "sourceKey": "field"},
        {"op": "raster-fallback", "sourceKey": "field"},
    ]}, master)
    assert ops == [
        {"op": "restore-style", "sourceKey": "field", "property": "borderColor", "value": "#8fb6ff33"},
        {"op": "restore-style", "sourceKey": "field", "property": "borderWidth", "value": 1.5},
        {"op": "restore-style", "sourceKey": "field-label", "property": "fontWeight", "value": 400},
        {"op": "restore-style", "sourceKey": "field-label", "property": "color", "value": "#a8b0c0"},
    ]
    patched = master_repair.apply_operations(master, ops)
    assert patched["tree"][0]["style"]["borderColor"] == "#8fb6ff33"
    assert patched["tree"][0]["frame"] == master["tree"][0]["frame"]
    # исходный IR не тронут
    assert master["tree"][0]["style"]["borderColor"] == "#8fb6ff"


def test_restore_layout_is_bounded_and_keeps_content_structure():
    master = _master()
    operations = master_repair.validate_operations({"operations": [
        {"op": "restore-layout", "sourceKey": "field-label", "property": "width", "value": 220},
        {"op": "restore-layout", "sourceKey": "field-label", "property": "x", "value": 14},
        # More than 20% and outside the section are rejected.
        {"op": "restore-layout", "sourceKey": "field-label", "property": "height", "value": 40},
        {"op": "restore-layout", "sourceKey": "field-label", "property": "y", "value": 100},
    ]}, master)
    assert operations == [
        {"op": "restore-layout", "sourceKey": "field-label", "property": "width", "value": 220.0},
        {"op": "restore-layout", "sourceKey": "field-label", "property": "x", "value": 14.0},
    ]
    fixed = master_repair.apply_operations(master, operations)
    assert fixed["tree"][0]["children"][0]["frame"]["width"] == 220
    assert fixed["tree"][0]["children"][0]["text"] == "Sending Engine"
    assert master["tree"][0]["children"][0]["frame"]["width"] == 200


def test_parse_operations_survives_prose_and_broken_json():
    master = _master()
    assert master_repair.parse_operations("no json here", master) == []
    assert master_repair.parse_operations('{"operations": "nope"}', master) == []
    assert master_repair.parse_operations(
        'thinking… {"operations": [{"op": "restore-style", "sourceKey": "field", '
        '"property": "opacity", "value": 0.6}]} done', master
    ) == [{"op": "restore-style", "sourceKey": "field", "property": "opacity", "value": 0.6}]


def test_build_repair_prompt_carries_defects_nodes_and_hard_rules():
    doc = _document()
    comp = doc["reviewComponents"]["field-review"]
    verdict = {"approved": False, "score": 71, "summary": "Рамка слишком яркая", "defects": [
        {"severity": "major", "what": "bright border", "where": "field outline"}]}
    nodes = master_repair.describe_nodes(comp["masterIr"])
    prompt = master_repair.build_repair_prompt(comp, verdict, "desktop", nodes)
    assert "major: bright border (field outline)" in prompt
    assert '"sourceKey": "field-label"' in prompt and '"text": "Sending Engine"' in prompt
    assert '"borderColor": "#8fb6ff"' in prompt and '"fontWeight": 700' in prompt
    assert "never change sizes or positions" in prompt and "never add or remove nodes" in prompt
    assert "borderColor" in prompt and "background" in prompt


def test_run_repairs_rejected_master_and_moves_it_into_registry():
    doc = _document()
    studio = _Studio()
    updated, results = master_review.run(doc, provider="codex", chat_vision=studio.vision,
                                         chat_repair=studio.repair, render=studio.render)

    assert results[0]["approved"] and results[0]["repaired"] and results[0]["rounds"] == 1
    assert len(studio.repair_prompts) == 1
    assert "field-review" not in updated["reviewComponents"]
    moved = updated["components"]["field"]
    root = moved["masterIr"]["tree"][0]
    assert root["style"]["borderColor"] == "#8fb6ff33"
    assert root["frame"] == _master()["tree"][0]["frame"]  # геометрия не тронута
    assert root["children"][0]["text"] == "Sending Engine"  # текст не тронут
    assert moved["sourceRef"]["masterHash"] == dsdoc.content_hash(moved["masterIr"])
    assert moved["status"] == "verified" and moved["confirmed"] is True
    review = moved["fidelity"]["aiReview"]
    assert review["verdict"] == "approved" and review["repaired"] is True and review["rounds"] == 1
    assert review["operations"] == [{"op": "restore-style", "sourceKey": "field",
                                     "property": "borderColor", "value": "#8fb6ff33"}]
    assert review["defects"] == []
    assert dsdoc.component_fidelity_status(moved["fidelity"])["passed"]
    bad = [e for e in dsdoc.validate_document(updated)
           if e["code"] in ("master-fidelity-failed", "observed-master-mutated")]
    assert bad == []
    # исходный документ не тронут
    assert doc["reviewComponents"]["field-review"]["masterIr"]["tree"][0]["style"]["borderColor"] == "#8fb6ff"


def test_repair_drops_stale_template_ir_so_document_validates():
    doc = _document(template=True)
    studio = _Studio()
    updated, _results = master_review.run(doc, chat_vision=studio.vision, chat_repair=studio.repair,
                                          render=studio.render)
    moved = updated["components"]["field"]
    assert "templateIr" not in moved
    assert not [e for e in dsdoc.validate_document(updated) if e["code"] == "observed-master-mutated"]


def test_repair_gives_up_and_leaves_master_on_review():
    doc = _document()
    # Чинильщик предлагает цвета без альфы: судья продолжает отклонять.
    studio = _Studio(values=("#101010", "#202020"))
    updated, results = master_review.run(doc, chat_vision=studio.vision, chat_repair=studio.repair,
                                         render=studio.render, repair_rounds=2)
    assert not results[0]["approved"] and results[0]["repaired"] is False and results[0]["rounds"] == 2
    assert len(studio.repair_prompts) == 2
    comp = updated["reviewComponents"]["field-review"]
    assert updated["components"] == {}
    assert comp["status"] == "needs-review"
    assert comp["review"]["reasons"] == [
        "major: bright border where the original is barely visible (field outline)"]
    review = comp["fidelity"]["aiReview"]
    assert review["verdict"] == "rejected" and review["repaired"] is False
    assert review["repairAttempts"] == 2 and review["defects"][0]["severity"] == "major"
    assert not dsdoc.component_fidelity_status(comp["fidelity"])["passed"]


def test_repair_stops_when_the_model_repeats_a_no_op_edit():
    doc = _document()
    studio = _Studio(values=("#101010",))  # один и тот же цвет каждый раунд
    updated, results = master_review.run(doc, chat_vision=studio.vision, chat_repair=studio.repair,
                                         render=studio.render, repair_rounds=3)
    assert results[0]["rounds"] == 1 and len(studio.repair_prompts) == 2
    assert "field-review" in updated["reviewComponents"]


def test_repair_stops_when_model_returns_no_valid_operations():
    doc = _document()
    studio = _Studio(fix=False)
    updated, results = master_review.run(doc, chat_vision=studio.vision, chat_repair=studio.repair,
                                         render=studio.render, repair_rounds=3)
    assert results[0]["rounds"] == 0 and results[0]["repaired"] is False
    assert len(studio.repair_prompts) == 1  # пустой ответ обрывает цикл, а не крутит его
    assert "field-review" in updated["reviewComponents"]


def test_repair_can_be_disabled():
    doc = _document()
    studio = _Studio()
    updated, results = master_review.run(doc, chat_vision=studio.vision, chat_repair=studio.repair,
                                         render=studio.render, repair=False)
    assert not results[0]["approved"] and results[0]["repaired"] is False
    assert studio.repair_prompts == []
    assert "field-review" in updated["reviewComponents"]


def test_repair_failure_does_not_stop_other_components():
    doc = _document()
    second = copy.deepcopy(doc["reviewComponents"]["field-review"])
    second["componentKey"] = "field-2"
    doc["reviewComponents"]["field-2-review"] = second
    studio = _Studio()
    calls = {"n": 0}

    def flaky_repair(images, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("no provider")
        return studio.repair(images, prompt)

    updated, results = master_review.run(doc, chat_vision=studio.vision, chat_repair=flaky_repair,
                                         render=studio.render)
    assert results[0].get("error", "").startswith("RuntimeError")
    assert results[1]["approved"] and results[1]["repaired"]
    assert "field-review" in updated["reviewComponents"]
    assert "field-2" in updated["components"]


def test_repair_description_includes_measured_layout_and_full_caption_without_mutation():
    import copy
    ir = {"tree": [{"sourceKey": "caption", "type": "text", "text": "Full captured caption " * 4,
        "frame": {"x": 20, "y": 78, "width": 212.5, "height": 63, "gap": 8, "padding": [4, 4, 4, 4]},
        "responsive": {"mobile": {"frame": {"width": 180, "x": 16}}}}]}
    before = copy.deepcopy(ir)
    nodes = master_repair.describe_nodes(ir)
    assert nodes[0]["frame"]["x"] == 20 and nodes[0]["frame"]["padding"] == [4, 4, 4, 4]
    assert nodes[0]["responsive"]["mobile"]["frame"]["width"] == 180
    assert nodes[0]["text"] == ir["tree"][0]["text"].strip()
    nodes[0]["frame"]["padding"][0] = 99
    nodes[0]["responsive"]["mobile"]["frame"]["width"] = 1
    assert ir == before
