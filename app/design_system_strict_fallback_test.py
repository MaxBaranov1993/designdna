import json
from copy import deepcopy
from pathlib import Path

import art_direction
import server
from design_system import resolver, store


ROOT = Path(__file__).resolve().parent.parent


def _fixture() -> dict:
    return json.loads((ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))


def _document(master: dict) -> dict:
    return {
        "id": "ds-pricing", "name": "Pricing kit", "revision": 1, "contentHash": "published-hash",
        "foundations": {}, "styleGuide": {},
        "components": {
            "list-item": {
                "componentKey": "list-item", "name": "List item", "category": "content",
                "origin": "user", "confirmed": True, "masterIr": master,
            },
            "small-link": {
                "componentKey": "small-link", "name": "Small link", "category": "navigation",
                "origin": "user", "confirmed": True,
                "masterIr": {"version": "1.1", "tree": [{"type": "text", "text": "Learn more"}]},
            },
        },
    }


def test_relevance_uses_master_copy_and_pricing_synonyms() -> None:
    pricing = {
        "componentKey": "list-item", "name": "List item", "category": "content", "origin": "observed",
        "masterIr": {"tree": [{"type": "card", "children": [
            {"type": "text", "title": "Sending Engine"}, {"type": "text", "value": "$49 / month"},
        ]}]},
    }
    generic = {
        "componentKey": "process-step", "name": "Process step", "category": "content", "origin": "observed",
        "masterIr": {"tree": [{"type": "card", "text": "Create an account"}]},
    }
    brief = "Карточка тарифа для лендинга"
    assert resolver.component_relevance(pricing, brief) > resolver.component_relevance(generic, brief)
    assert resolver.component_relevance(pricing, brief) >= 3


def test_reference_pins_by_ref_shape_and_editor_meta() -> None:
    master = _fixture()
    document = _document(master)
    explicit = {"tree": [{"type": "text", "sourceMeta": {"componentRef": {"componentKey": "small-link"}}}]}
    shaped = {"tree": [deepcopy(master["tree"][0])]}
    editor = {"meta": {"_dsMaster": {"systemId": "ds-pricing", "componentKey": "list-item"}}, "tree": []}
    assert server._reference_pinned_component_keys([explicit, shaped, editor], document) == ["small-link", "list-item"]


def test_pinned_master_is_packed_before_smaller_masters() -> None:
    document = _document(_fixture())
    context = resolver.resolve_context(document, "unrelated", usage_mode="strict", pinned_keys=["list-item"])
    compiled = resolver.compiled_context(
        context, brief="unrelated", token_budget=500, pinned_keys=["list-item"])
    assert context["components"][0]["componentKey"] == "list-item"
    assert compiled["includedMasterKeys"][0] == "list-item"
    assert "small-link" not in compiled["includedMasterKeys"]
    assert compiled["pinnedMasterKeys"] == ["list-item"]


def test_strict_materializes_pinned_master_without_provider_component_ref(monkeypatch) -> None:
    master = _fixture()
    document = _document(master)
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    reference = deepcopy(master)
    reference.setdefault("meta", {})["_dsMaster"] = {"systemId": "ds-pricing", "componentKey": "list-item"}
    response = server.generate(server.GenerateReq(
        brief="unrelated request", count=1, rawOutputs=[json.dumps(master)], referenceIrs=[reference],
        designSystem={"systemId": "ds-pricing", "revision": 1, "usageMode": "strict"},
    ))
    assert response["variants"][0]["meta"]["strictRecovery"] == "exact-master-materialized"
    assert response["generationLog"]["designSystem"]["pinnedMaster"] == "list-item"
    assert response["generationLog"]["designSystem"]["recovered"]["componentKey"] == "list-item"


def test_strict_accepts_valid_provider_variant_as_extend_when_no_master_matches(monkeypatch) -> None:
    master = _fixture()
    document = _document(master)
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    response = server.generate(server.GenerateReq(
        brief="unrelated canvas", count=1, allowStrictFallback=True, rawOutputs=[json.dumps(master)],
        designSystem={"systemId": "ds-pricing", "revision": 1, "usageMode": "strict"},
    ))
    assert response["generationLog"]["strictFallback"] == "extend"
    warnings = response["variants"][0]["meta"]["designSystemWarnings"]
    assert any(item["code"] == "strict-fallback-extend" for item in warnings)
    assert response["designSystem"]["errors"] == []


def test_strict_materializes_pinned_master_when_it_exceeds_the_context_budget(monkeypatch) -> None:
    """Мастер целой секции не влезает в промпт: модель не зовём, отдаём точную копию (и в prepareOnly тоже)."""
    master = _fixture()
    document = _document(master)
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    monkeypatch.setattr(art_direction, "create_design_brief", lambda *_args, **_kwargs: [])
    reference = deepcopy(master)
    reference.setdefault("meta", {})["_dsMaster"] = {"systemId": "ds-pricing", "componentKey": "list-item"}
    ds = {"systemId": "ds-pricing", "revision": 1, "usageMode": "strict", "tokenBudget": 320}
    # prepareOnly (десктоп): точная копия + промпты на переписывание контента, без IR в промпте
    prepared = server.generate(server.GenerateReq(brief="карточка тарифа", count=2, prepareOnly=True,
                                                  referenceIrs=[reference], designSystem=ds))
    slots = server._content_slots(prepared["variants"][0])
    assert slots and prepared["contentRewrite"]["slots"] == len(slots)
    assert len(prepared["prompts"]) == 2
    user_prompt = prepared["prompts"][0]["messages"][1]["content"]
    assert "карточка тарифа" in user_prompt and slots[0]["id"] in user_prompt and "tree" not in user_prompt
    # второй вызов с ответами модели: тот же мастер, другой контент; strict-копия остаётся валидной
    answer = json.dumps({"slots": [{"id": slots[0]["id"], "text": "Новый заголовок тарифа"}]}, ensure_ascii=False)
    response = server.generate(server.GenerateReq(brief="карточка тарифа", count=2, rawOutputs=[answer, "not json"],
                                                  referenceIrs=[reference], designSystem=ds))
    assert response.get("prompts") == []
    assert len(response["variants"]) == 2
    first, second = response["variants"]
    assert first["meta"]["strictRecovery"] == "exact-master-materialized"
    assert first["meta"]["strictRecoveryReason"] == "pinned-master-exceeds-context-budget"
    assert first["meta"]["contentRewrite"]["replaced"] == 1
    found, value = __import__("qualitygate").get_path(first, slots[0]["path"])
    assert found and value == "Новый заголовок тарифа"
    assert second["meta"]["contentRewrite"]["replaced"] == 0 and "JSON" in second["meta"]["contentRewrite"]["error"]
    log = response["generationLog"]
    assert log["strictRecovery"] == "exact-master-materialized"
    assert log["designSystem"]["pinnedMaster"] == "list-item"
    assert log["contentRewrite"]["slots"] == len(slots)
    assert response["qa"][0]["recovery"] == "exact-master-materialized"
    context = resolver.resolve_context(document, "карточка тарифа", usage_mode="strict", pinned_keys=["list-item"])
    assert resolver.validate_generation(first, context)["errors"] == []
    # серверный путь без rawOutputs зовёт модель сам
    monkeypatch.setattr(server.llm, "chat", lambda *_a, **_k: answer)
    direct = server.generate(server.GenerateReq(brief="карточка тарифа", count=1, referenceIrs=[reference], designSystem=ds))
    assert direct["variants"][0]["meta"]["contentRewrite"]["replaced"] == 1


def test_exact_copy_inside_component_ref_is_trusted_and_placement_does_not_mutate_shape() -> None:
    """Обёртка превью обнуляет x/y и несёт измеренные цвета мастера — копия остаётся exact."""
    from design_system import compiler, document as dsdoc
    master = _fixture()
    root = master["tree"][0]
    root.setdefault("frame", {}).update({"x": 120, "y": 80})
    root.setdefault("style", {})["color"] = "#4f4d5a"  # цвет вне палитры системы, но это цвет самого мастера
    document = _document(master)
    document["foundations"] = {"colors": {"semantic": {"primary": "#5b6cff", "background": "#0a0a0e",
                                                      "text": "#f2f0ea", "textMuted": "#9d9aab", "border": "#1b1b1f"}}}
    context = resolver.resolve_context(document, "карточка тарифа", usage_mode="strict", pinned_keys=["list-item"])
    primary = resolver.primary_component_for_brief(context, "карточка тарифа", pinned_keys=["list-item"])
    recovered, check = server._materialize_exact_master(primary, context, None, "test")
    assert recovered is not None, check["errors"]
    assert check["errors"] == []
    # то же самое, но со сдвигом: положение — не форма
    moved = deepcopy(root)
    moved["frame"]["x"], moved["frame"]["y"] = 0, 0
    assert compiler.component_shape_hash(moved) == compiler.component_shape_hash(root)
    resized = deepcopy(root)
    resized["frame"]["width"] = 999
    assert compiler.component_shape_hash(resized) != compiler.component_shape_hash(root)
    # цвет вне палитры у обычного узла в strict по-прежнему ошибка
    stray = {"version": "1.1", "tokens": {}, "tree": [{"id": "s", "type": "composition",
             "children": [{"type": "text", "text": "x", "style": {"color": "#4f4d5a"}}]}]}
    assert any(e["code"] == "off-system-color" for e in resolver.validate_generation(stray, context)["errors"])
