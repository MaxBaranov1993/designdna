import copy
import json
from pathlib import Path

from editor_assist import AssistRequest, editor_assist
from ui_contact_form_fields_test import IR as CONTACT_FORM_IR


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


def _request(document, scope, commands, constraints=None):
    return editor_assist(AssistRequest(
        ir=document,
        prompt="Измени только выделение",
        action="custom",
        scope={"sourceKeys": scope, "viewport": "desktop"},
        constraints=constraints or {},
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


def test_empty_scope_is_rejected_instead_of_allowing_the_whole_document():
    base = _base()
    target = _nodes(base)[2]
    result = _request(base, [], [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.5}}, "reason": "must reject",
    }])
    assert getattr(result, "status_code", None) == 422
    assert "выберите хотя бы один элемент" in result.body.decode("utf-8")


def test_nested_group_scope_keeps_specific_child_and_excludes_parent():
    base = _base()
    parent = next(node for node in _nodes(base) if node.get("children"))
    child = parent["children"][0]
    result = _request(base, [parent["sourceKey"], child["sourceKey"]], [{
        "command": "update", "targetSourceKey": child["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.75}}, "reason": "specific child",
    }])
    assert isinstance(result, dict), getattr(result, "body", result)
    assert any(warning["code"] == "nested_scope_normalized" for warning in result["warnings"])
    changed = next(node for node in _nodes(result["previewIr"]) if node["sourceKey"] == child["sourceKey"])
    assert changed["style"]["opacity"] == 0.75

    rejected = _request(base, [parent["sourceKey"], child["sourceKey"]], [{
        "command": "update", "targetSourceKey": parent["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.5}}, "reason": "too broad",
    }])
    assert getattr(rejected, "status_code", None) == 422


def test_content_and_color_constraints_are_enforced_server_side():
    base = _base()
    target = _nodes(base)[2]
    no_color = _request(base, [target["sourceKey"]], [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"style": {"color": "#123456"}}, "reason": "color",
    }], {"allowColor": False})
    assert getattr(no_color, "status_code", None) == 422
    assert "цвета" in no_color.body.decode("utf-8")

    no_content = _request(base, [target["sourceKey"]], [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"text": "Новый текст"}, "reason": "content",
    }], {"allowContent": False})
    assert getattr(no_content, "status_code", None) == 422
    assert "текста" in no_content.body.decode("utf-8")

    no_props = _request(base, [target["sourceKey"]], [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"props": {"submitText": "Новая кнопка"}}, "reason": "content in props",
    }], {"allowContent": False})
    assert getattr(no_props, "status_code", None) == 422


def test_scalar_prop_selection_is_ai_editable_and_stays_scoped():
    base = _base()
    key = "editor:/tree/0/props/heading"
    before_subheading = base["tree"][0]["props"]["subheading"]
    result = _request(base, [key], [{
        "command": "update", "targetSourceKey": key, "viewport": "shared",
        "changes": {"text": "Новый заголовок"}, "reason": "edit selected prop",
    }])
    assert isinstance(result, dict), getattr(result, "body", result)
    assert result["previewIr"]["tree"][0]["props"]["heading"] == "Новый заголовок"
    assert result["previewIr"]["tree"][0]["props"]["subheading"] == before_subheading

    blocked = _request(base, [key], [{
        "command": "update", "targetSourceKey": key, "viewport": "shared",
        "changes": {"text": "Нельзя"}, "reason": "content disabled",
    }], {"allowContent": False})
    assert getattr(blocked, "status_code", None) == 422

    viewport_only = _request(base, [key], [{
        "command": "update", "targetSourceKey": key, "viewport": "mobile",
        "changes": {"text": "Только mobile"}, "reason": "must reject",
    }])
    assert getattr(viewport_only, "status_code", None) == 422

    structured_value = _request(base, [key], [{
        "command": "update", "targetSourceKey": key, "viewport": "shared",
        "changes": {"text": {"unsafe": True}}, "reason": "must reject",
    }])
    assert getattr(structured_value, "status_code", None) == 422

    adapt = editor_assist(AssistRequest(
        ir=base, prompt="Адаптируй", action="adapt",
        scope={"sourceKeys": [key], "viewport": "desktop"}, constraints={},
    ))
    assert getattr(adapt, "status_code", None) == 422


def test_partial_or_ambiguous_scope_is_rejected():
    base = _base()
    target = _nodes(base)[2]
    command = [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.8}}, "reason": "exact scope",
    }]
    partial = _request(base, [target["sourceKey"], "missing:key"], command)
    assert getattr(partial, "status_code", None) == 422

    duplicate = _base()
    nodes = _nodes(duplicate)
    nodes[3]["sourceKey"] = nodes[2]["sourceKey"]
    ambiguous = _request(duplicate, [nodes[2]["sourceKey"]], command)
    assert getattr(ambiguous, "status_code", None) == 422


def test_structured_props_cannot_bypass_structure_lock():
    base = _base()
    target = _nodes(base)[0]
    result = _request(base, [target["sourceKey"]], [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"props": {"ctaPrimary": {"label": "Заменить"}}}, "reason": "must reject",
    }])
    assert getattr(result, "status_code", None) == 422
    assert "структурные props" in result.body.decode("utf-8")


def test_intent_locks_and_embedded_constraints_are_enforced():
    base = _base()
    base["version"] = "1.1"
    for index, section in enumerate(base["tree"]):
        section["id"] = f"section-{index}"
    target = _nodes(base)[0]
    base["constraints"] = {
        "intentLocks": ["appearance", "content", "geometry"],
        "allowedColors": ["#ffffff"], "maxTextLength": 3,
        "minWidth": 100, "maxWidth": 200,
    }
    key = target["sourceKey"]
    cases = [
        ({"style": {"color": "#123456"}}, "Intent Lock"),
        ({"props": {"heading": "длинный текст"}}, "Intent Lock"),
        ({"frame": {"width": 300}}, "Intent Lock"),
    ]
    for changes, expected in cases:
        result = _request(base, [key], [{
            "command": "update", "targetSourceKey": key, "viewport": "shared",
            "changes": changes, "reason": "locked",
        }])
        assert getattr(result, "status_code", None) == 422
        assert expected in result.body.decode("utf-8")


def test_color_constraint_covers_shadows_but_color_is_independent_from_style():
    base = _base()
    target = _nodes(base)[2]
    key = target["sourceKey"]
    shadow = _request(base, [key], [{
        "command": "update", "targetSourceKey": key, "viewport": "shared",
        "changes": {"style": {"boxShadow": "0 0 0 10px #ff0000"}}, "reason": "color",
    }], {"allowColor": False})
    assert getattr(shadow, "status_code", None) == 422

    color_only = _request(base, [key], [{
        "command": "update", "targetSourceKey": key, "viewport": "shared",
        "changes": {"style": {"color": "#123456"}}, "reason": "color only",
    }], {"allowStyle": False, "allowColor": True})
    assert isinstance(color_only, dict), getattr(color_only, "body", color_only)


def test_contact_form_nested_parts_validate_and_are_independently_ai_editable():
    base = copy.deepcopy(CONTACT_FORM_IR)
    form = base["tree"][0]
    form["id"] = "contact-form"
    form["variant"] = "stacked"
    form["props"]["submit"] = {"type": "button", "role": "form-submit"}
    for field in form["props"]["fields"]:
        field["parts"] = {
            "label": {"type": "text", "role": "form-label"},
            "control": {"type": "input", "role": "form-control"},
        }
    label_key = "editor:/tree/0/props/fields/0/parts/label"
    result = _request(base, [label_key], [{
        "command": "update", "targetSourceKey": label_key, "viewport": "shared",
        "changes": {"text": "Товар"}, "reason": "selected label",
    }])
    assert isinstance(result, dict), getattr(result, "body", result)
    field = result["previewIr"]["tree"][0]["props"]["fields"][0]
    assert field["parts"]["label"]["text"] == "Товар"
    assert field["label"] == "Название товара"

    submit_key = "editor:/tree/0/props/submit"
    submit = _request(base, [submit_key], [{
        "command": "update", "targetSourceKey": submit_key, "viewport": "shared",
        "changes": {"style": {"background": "#112233"}}, "reason": "selected submit",
    }])
    assert isinstance(submit, dict), getattr(submit, "body", submit)
    assert submit["previewIr"]["tree"][0]["props"]["submit"]["style"]["background"] == "#112233"

    control_key = "editor:/tree/0/props/fields/0/parts/control"
    control = _request(base, [control_key], [{
        "command": "update", "targetSourceKey": control_key, "viewport": "shared",
        "changes": {"value": "Новая подсказка"}, "reason": "visible control text",
    }])
    assert isinstance(control, dict), getattr(control, "body", control)
    assert control["previewIr"]["tree"][0]["props"]["fields"][0]["parts"]["control"]["placeholder"] == "Новая подсказка"


def test_scaffold_ops_are_not_shown_or_counted_as_high_impact():
    base = _base()
    target = _nodes(base)[2]
    target.pop("style", None)
    result = _request(base, [target["sourceKey"]], [{
        "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.8}}, "reason": "single visible change",
    }])
    assert isinstance(result, dict), getattr(result, "body", result)
    assert len(result["ops"]) == 1 and result["ops"][0]["path"].endswith("/opacity")
    assert not any(warning["code"] == "high_impact" for warning in result["warnings"])


def test_browser_assist_calls_the_supported_llm_interface(monkeypatch):
    base = _base()
    target = _nodes(base)[2]
    seen = {}

    def fake_chat(provider, messages, temperature, role):
        seen.update(provider=provider, messages=messages, temperature=temperature, role=role)
        return json.dumps({
            "summary": "Готово",
            "commands": [{
                "command": "update", "targetSourceKey": target["sourceKey"], "viewport": "shared",
                "changes": {"style": {"opacity": 0.85}}, "reason": "browser route",
            }],
        })

    monkeypatch.setattr("editor_assist.llm.chat", fake_chat)
    result = editor_assist(AssistRequest(
        ir=base, prompt="Сделай немного прозрачнее", action="custom",
        scope={"sourceKeys": [target["sourceKey"]], "viewport": "desktop"}, constraints={},
    ))

    assert isinstance(result, dict), getattr(result, "body", result)
    assert seen["provider"] == "auto" and seen["role"] == "edit"
    assert result["ops"][0]["after"] == 0.85


def test_locked_raster_layers_refuse_ai_mutations_but_stay_inspectable():
    """editable:false (raster fallback Source Import): AI отказывает content/
    geometry/style правки над locked-слоем, соседние editable слои работают."""
    base = _base()
    nodes = _nodes(base)
    locked = nodes[2]
    locked["editable"] = False
    locked["lockedReason"] = "canvas: raster surface"
    editable = nodes[3]

    for changes in ({"text": "Новый текст"}, {"frame": {"x": 12}}, {"style": {"opacity": 0.5}}):
        rejected = _request(base, [locked["sourceKey"]], [{
            "command": "update", "targetSourceKey": locked["sourceKey"], "viewport": "shared",
            "changes": changes, "reason": "probe",
        }])
        assert getattr(rejected, "status_code", None) == 422, (changes, getattr(rejected, "body", rejected))
        assert "editable:false" in rejected.body.decode("utf-8"), rejected.body

    # locked-слой в scope предка тоже защищён (мутация через предка)
    parent_key = next(
        node["sourceKey"] for node in nodes
        if any(child.get("sourceKey") == locked["sourceKey"] for child in node.get("children") or [])
    )
    rejected_child = _request(base, [parent_key], [{
        "command": "update", "targetSourceKey": locked["sourceKey"], "viewport": "shared",
        "changes": {"text": "Новый текст"}, "reason": "probe via parent scope",
    }])
    # вложенный target нормализует scope до родителя, но locked-узел отклоняется валидатором
    assert getattr(rejected_child, "status_code", None) in (422,), getattr(rejected_child, "body", rejected_child)

    # соседний editable слой по-прежнему принимает правки
    accepted = _request(base, [editable["sourceKey"]], [{
        "command": "update", "targetSourceKey": editable["sourceKey"], "viewport": "shared",
        "changes": {"style": {"opacity": 0.9}}, "reason": "control",
    }])
    assert isinstance(accepted, dict), getattr(accepted, "body", accepted)
