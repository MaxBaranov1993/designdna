from __future__ import annotations

import json

import art_direction


def result() -> dict:
    return {
        "schemaVersion": "design-brief/1.0",
        "audience": {"primary": "Finance teams", "task": "Understand cash flow"},
        "tone": "technical",
        "typePair": "russo-golos",
        "palette": {
            "background": {"lightness": 0.97, "chroma": 0.01, "hue": 250},
            "accent": {"lightness": 0.58, "chroma": 0.16, "hues": [250]},
        },
        "rhythm": {
            "sections": [
                {"purpose": "promise", "density": "airy"},
                {"purpose": "evidence", "density": "dense"},
                {"purpose": "action", "density": "balanced"},
            ],
            "risk": "Expose one oversized live metric in the hero",
        },
        "copyDeck": {"hero": "See tomorrow's cash before it moves", "cta": "Model cash flow",
                     "proofs": ["Updated from every connected account"]},
    }


def directions() -> list[dict]:
    items = []
    for index, tone in enumerate(("technical", "editorial", "industrial"), start=1):
        brief = result()
        brief["tone"] = tone
        items.append({
            "id": f"direction-{index}",
            "label": f"Direction {index}",
            "motivation": f"Motivation {index}",
            "tradeoff": f"Tradeoff {index}",
            "designBrief": brief,
        })
    return items


def test_art_direction_uses_fast_role_and_caches_by_brief_and_product(monkeypatch) -> None:
    stored: dict[tuple[str, str], dict] = {}
    calls = []
    monkeypatch.setattr(art_direction.cache_store, "get", lambda kind, key: stored.get((kind, key)))
    monkeypatch.setattr(art_direction.cache_store, "put",
                        lambda kind, key, value: stored.__setitem__((kind, key), value))

    def fake_chat(*args, **kwargs):
        calls.append((args, kwargs))
        return "```json\n" + json.dumps(result()) + "\n```"

    monkeypatch.setattr(art_direction.llm, "chat", fake_chat)
    first = art_direction.create_design_brief("Cash-flow SaaS", "saas", style_dna={"tone": "calm"})
    second = art_direction.create_design_brief("Cash-flow SaaS", "saas", style_dna={"tone": "calm"})

    assert first == second == result()
    assert len(calls) == 1
    assert calls[0][1]["role"] == "art-direction"
    assert calls[0][1]["reasoning_effort"] == "medium"
    assert calls[0][1]["timeout"] == 30


def test_art_direction_returns_three_validated_cached_directions(monkeypatch) -> None:
    stored: dict[tuple[str, str], object] = {}
    calls = []
    monkeypatch.setattr(art_direction.cache_store, "get", lambda kind, key: stored.get((kind, key)))
    monkeypatch.setattr(art_direction.cache_store, "put",
                        lambda kind, key, value: stored.__setitem__((kind, key), value))
    monkeypatch.setattr(art_direction.llm, "chat", lambda *args, **kwargs: (
        calls.append((args, kwargs)), json.dumps({"directions": directions()})
    )[1])

    first = art_direction.create_design_brief(
        "Cash-flow SaaS", "saas", style_dna={"systemId": "ds-1"}, count=3)
    second = art_direction.create_design_brief(
        "Cash-flow SaaS", "saas", style_dna={"systemId": "ds-1"}, count=3,
        generate_if_missing=False)

    assert first == second == directions()
    assert len(calls) == 1
    assert calls[0][1]["role"] == "art-direction"


def test_cache_key_changes_with_product_type_and_is_order_stable() -> None:
    left = art_direction.cache_key({"goal": "sell", "audience": "teams"}, "saas")
    right = art_direction.cache_key({"audience": "teams", "goal": "sell"}, "saas")
    assert left == right
    assert left != art_direction.cache_key({"audience": "teams", "goal": "sell"}, "marketplace")
    assert left != art_direction.cache_key(
        {"audience": "teams", "goal": "sell"}, "saas", {"systemId": "ds-1"})
