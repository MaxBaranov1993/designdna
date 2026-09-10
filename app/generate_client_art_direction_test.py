"""Арт-направления через клиента (десктоп): промпт от сервера, ответ модели обратно, кэш общий."""
import json
from copy import deepcopy

import art_direction
import server
from art_direction_test import directions as sample_directions
from design_system import store
from generator_ds_fidelity_test import _document

DS = {"systemId": "ds-labels", "revision": 1, "usageMode": "extend"}
BRIEF = "Лендинг для сервиса рассылок через чат"


def _setup(monkeypatch):
    stored: dict[tuple[str, str], object] = {}
    monkeypatch.setattr(art_direction.cache_store, "get", lambda kind, key: stored.get((kind, key)))
    monkeypatch.setattr(art_direction.cache_store, "put", lambda kind, key, value: stored.__setitem__((kind, key), value))
    monkeypatch.setattr(art_direction.llm, "chat", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    document = _document()
    monkeypatch.setattr(store, "resolve_ref", lambda _ref: (deepcopy(document), None))
    return stored


def _prepare(**extra):
    return server.generate(server.GenerateReq(
        brief=BRIEF, count=1, prepareOnly=True, surface="landing", clientArtDirection=True, designSystem=DS, **extra))


def test_server_hands_the_art_direction_prompt_to_the_client_and_accepts_the_answer(monkeypatch) -> None:
    stored = _setup(monkeypatch)
    first = _prepare()
    assert first["prompts"] == [] and first["variants"] == []
    messages = first["artDirection"]["messages"]
    assert first["artDirection"]["count"] == 3
    assert messages[0]["role"] == "system" and "design system is attached" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["styleDNA"]["designSystemDigest"]["systemRef"]["systemId"] == "ds-labels"
    assert payload["count"] == 3 and first["preparedContextId"]

    answer = json.dumps({"directions": sample_directions()})
    second = _prepare(artDirectionRaw=answer)
    assert "artDirection" not in second
    assert len(second["prompts"]) == 1
    assert [item["id"] for item in second["directions"]] == ["direction-1", "direction-2", "direction-3"]
    assert second["variantDirections"] == ["Direction 1"]
    assert second["designBriefs"][0]["tone"] == "technical"
    cached = next(value for (kind, _key), value in stored.items() if kind == art_direction.CACHE_KIND)
    assert isinstance(cached, dict) and len(cached["directions"]) == 3

    # кэш общий: третий вызов без ответа модели сразу отдаёт промпты
    third = _prepare()
    assert "artDirection" not in third and len(third["prompts"]) == 1
    assert [item["id"] for item in third["directions"]] == ["direction-1", "direction-2", "direction-3"]


def test_invalid_client_answer_falls_back_to_policy_directions(monkeypatch) -> None:
    _setup(monkeypatch)
    response = _prepare(artDirectionRaw="not json at all")
    assert "artDirection" not in response and len(response["prompts"]) == 1
    assert [item["id"] for item in response["directions"]] == ["task-first", "compare-first", "guided"]


def test_raw_outputs_pass_never_asks_for_art_direction(monkeypatch) -> None:
    _setup(monkeypatch)
    prepared = _prepare(artDirectionRaw=json.dumps({"directions": sample_directions()}))
    master = json.loads((server.ROOT / "app" / "fixtures" / "frame-example.json").read_text(encoding="utf-8"))
    response = server.generate(server.GenerateReq(
        brief=BRIEF, count=1, surface="landing", clientArtDirection=True, designSystem=DS,
        rawOutputs=[json.dumps(master)], preparedContextId=prepared["preparedContextId"]))
    assert "artDirection" not in response and response["variants"]
    assert response["generationLog"]["direction"]["variants"] == ["Direction 1"]
