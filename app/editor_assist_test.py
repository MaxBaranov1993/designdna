import copy
import json
from pathlib import Path

from editor_assist import AssistRequest, editor_assist


FIXTURE = Path(__file__).parent / "fixtures" / "frame-example.json"


def _base():
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    index = 0
    def visit(node):
        nonlocal index
        node["sourceKey"] = f"test:{index}"
        index += 1
        for child in node.get("children") or []: visit(child)
    for section in document["tree"]: visit(section)
    return document


def _nodes(document):
    result = []
    def visit(node):
        result.append(node)
        for child in node.get("children") or []: visit(child)
    for section in document["tree"]: visit(section)
    return result


def _contains(node, source_key):
    return any(item["sourceKey"] == source_key for item in _nodes({"tree": [node]}))


def _request(document, scope, commands):
    return editor_assist(AssistRequest(
        ir=document,
        prompt="Измени только выделение",
        action="custom",
        scope={"sourceKeys": scope, "viewport": "desktop"},
        rawOutput=json.dumps({"summary": "Готово", "commands": commands}),
    ))


def test_single_scope_works_for_every_element_type_and_isolates_siblings():
    base = _base()
    nodes = _nodes(base)
    for target in nodes:
        before = copy.deepcopy(base)
        result = _request(base, [target["sourceKey"]], [{
            "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
            "changes": {"style": {"opacity": 0.9}}, "reason": "focused test",
        }])
        assert isinstance(result, dict), getattr(result, "body", result)
        assert result["validation"]["schema"] is True
        changed = next(node for node in _nodes(result["previewIr"]) if node["sourceKey"] == target["sourceKey"])
        assert changed["style"]["opacity"] == 0.9
        for sibling in _nodes(before):
            if sibling["sourceKey"] == target["sourceKey"] or _contains(sibling, target["sourceKey"]): continue
            after = next(node for node in _nodes(result["previewIr"]) if node["sourceKey"] == sibling["sourceKey"])
            assert after == sibling


def test_group_scope_updates_all_selected_and_keeps_unselected_unchanged():
    base = _base()
    nodes = _nodes(base)
    selected = [nodes[2]["sourceKey"], nodes[3]["sourceKey"]]
    untouched = copy.deepcopy(nodes[4])
    commands = [{
        "command": "update", "targetSourceKey": key, "viewport": "shared",
        "changes": {"style": {"color": "#123456"}}, "reason": "group test",
    } for key in selected]
    result = _request(base, selected, commands)
    assert isinstance(result, dict), getattr(result, "body", result)
    changed = {node["sourceKey"]: node for node in _nodes(result["previewIr"])}
    assert all(changed[key]["style"]["color"] == "#123456" for key in selected)
    assert changed[untouched["sourceKey"]] == untouched


def test_ai_cannot_escape_single_selection():
    base = _base()
    nodes = _nodes(base)
    result = _request(base, [nodes[2]["sourceKey"]], [{
        "command": "update", "targetSourceKey": nodes[3]["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.5}}, "reason": "must reject",
    }])
    assert getattr(result, "status_code", None) == 422
    assert "вне текущего выделения" in result.body.decode("utf-8")
