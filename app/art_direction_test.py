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


def test_design_system_digest_locks_the_direction_prompt() -> None:
    digest = {"systemRef": {"systemId": "ds-kit", "revision": 3}, "soul": "тихая техничная система",
              "decor": ["Служебные лейблы набираются JetBrains Mono 9–11px"], "sectionArchetypes": ["Header", "Pricing"]}
    with_ds = art_direction._prompt("Лендинг", "saas", {"designSystemDigest": digest, "surface": "landing"}, 3)
    without = art_direction._prompt("Лендинг", "saas", {"surface": "landing"}, 3)
    assert "design system is attached" in with_ds[0]["content"]
    assert "Do not propose other palettes or type pairs" in with_ds[0]["content"]
    assert "design system is attached" not in without[0]["content"]
    payload = json.loads(with_ds[1]["content"])
    assert payload["styleDNA"]["designSystemDigest"]["decor"] == digest["decor"]
    assert art_direction.cache_key("Лендинг", "saas", {"designSystemDigest": digest}, count=3) \
        != art_direction.cache_key("Лендинг", "saas", {"designSystemDigest": {**digest, "systemRef": {"systemId": "ds-kit", "revision": 4}}}, count=3)


def test_directions_are_cached_as_an_object_payload(monkeypatch) -> None:
    """cache_store принимает только объекты: список направлений хранится в {"directions": [...]}."""
    stored: dict[tuple[str, str], object] = {}
    monkeypatch.setattr(art_direction.cache_store, "get", lambda kind, key: stored.get((kind, key)))
    monkeypatch.setattr(art_direction.cache_store, "put",
                        lambda kind, key, value: stored.__setitem__((kind, key), value))
    monkeypatch.setattr(art_direction.llm, "chat", lambda *args, **kwargs: json.dumps({"directions": directions()}))
    first = art_direction.create_design_brief("Лендинг", "saas", style_dna={"systemId": "ds-2"}, count=3)
    payload = next(iter(stored.values()))
    assert isinstance(payload, dict) and payload["directions"] == directions()
    second = art_direction.create_design_brief("Лендинг", "saas", style_dna={"systemId": "ds-2"}, count=3,
                                               generate_if_missing=False)
    assert first == second == directions()
