"""Mock data: deterministic fixtures по схеме+seed+profile (ТЗ §13).

Синтетика только: реальные персональные данные из Source не копируются (§13.4),
email/имена/телефоны заменяются правдоподобными синтетическими значениями.
"""
from __future__ import annotations

import hashlib
import copy
import random
from typing import Any

_PROFILES = ("typical", "short", "long", "empty", "loading", "error", "edge-case")

_SYNTH = {
    # формат поля -> генератор значения (никогда не real data)
    "name": lambda rng, locale: rng.choice(["Anna Kovaleva", "Ivan Melnik", "Olga Litvin", "Dmitry Savin", "Maria Gonchar"]),
    "email": lambda rng, locale: f"user{rng.randint(100, 999)}@example.com",
    "phone": lambda rng, locale: f"+7 9{rng.randint(10, 99)} {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}",
    "price": lambda rng, locale: f"{rng.randint(3, 12) * 1000 + rng.choice([0, 490, 900]):,}".replace(",", " ") + " ₽",
    "title": lambda rng, locale: rng.choice(["Compact variant", "Premium model", "Basic package", "New collection", "Popular choice"]),
    "sentence": lambda rng, locale: rng.choice([
        "Realistic, specific text for checking the layout.",
        "A longer description for checking line wrapping and content clipping in realistic layout conditions.",
        "Brief.",
    ]),
    "url": lambda rng, locale: f"https://example.com/item/{rng.randint(1, 9999)}",
    "date": lambda rng, locale: f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
    # форматы мок-контента референса (fallback, когда Source не отдал свои значения)
    "cta": lambda rng, locale: rng.choice(["Learn more", "Add to cart", "Submit", "Checkout"]),
    "nav": lambda rng, locale: rng.choice(["Home", "Catalog", "Favorites", "Profile", "Messages"]),
    "badge": lambda rng, locale: rng.choice(["Bestseller", "New", "-25%", "In stock"]),
    "category": lambda rng, locale: rng.choice(["Electronics", "Home", "Accessories", "Hobbies", "Clothing"]),
    "heading": lambda rng, locale: rng.choice(["Popular products", "New arrivals", "Special offers"]),
    "question": lambda rng, locale: rng.choice(["How does delivery work?", "Is there a warranty?", "How can I pay?"]),
    "answer": lambda rng, locale: rng.choice([
        "A courier will deliver within two days. Choose a date at checkout.",
        "All products include a twelve-month warranty from the date of purchase.",
        "Pay by card, cash on delivery, or installments.",
    ]),
    "word": lambda rng, locale: rng.choice(["First", "Main", "Active", "Selected"]),
}


def seed_for(schema_id: str, profile: str) -> int:
    """Одинаковый seed даёт одинаковые данные (§31)."""
    return int(hashlib.sha256(f"{schema_id}:{profile}".encode("utf-8")).hexdigest()[:12], 16)


def make_fixture(schema: dict, profile: str = "typical", *, locale: str = "ru") -> dict:
    """Fixture по схеме: fields=[{name, format?, min?, max?, enum?}]."""
    if profile not in _PROFILES:
        profile = "typical"
    schema_id = str(schema.get("id") or "entity")
    rng = random.Random(seed_for(schema_id, profile))
    data: dict[str, Any] = {}

    if profile == "empty":
        return {"id": f"{schema_id}:empty", "schemaId": schema_id, "locale": locale, "seed": seed_for(schema_id, profile), "profile": "empty", "data": {}}
    if profile == "loading":
        return {"id": f"{schema_id}:loading", "schemaId": schema_id, "locale": locale, "seed": seed_for(schema_id, profile), "profile": "loading", "data": {"__loading": True}}
    if profile == "error":
        return {"id": f"{schema_id}:error", "schemaId": schema_id, "locale": locale, "seed": seed_for(schema_id, profile), "profile": "error", "data": {"__error": "Could not load data"}}

    repeat = {"short": 1, "typical": 3, "long": 8, "edge-case": 12}.get(profile, 3)
    for field in schema.get("fields") or []:
        name = str(field.get("name") or "value")
        fmt = str(field.get("format") or field.get("type") or "sentence")
        if field.get("enum"):
            data[name] = rng.choice(field["enum"])
            continue
        gen = _SYNTH.get(fmt) or _SYNTH.get(name.split("_")[-1]) or _SYNTH["sentence"]
        value = gen(rng, locale)
        if isinstance(value, str) and fmt == "sentence" and profile == "edge-case":
            value = value * 4  # стресс-длина
        data[name] = value
    if profile in ("typical", "long", "edge-case"):
        data["__repeat"] = repeat
    return {"id": f"{schema_id}:{profile}", "schemaId": schema_id, "locale": locale, "seed": seed_for(schema_id, profile), "profile": profile, "data": data}


def default_profiles(schema: dict, locale: str = "ru") -> dict[str, dict]:
    """Набор обязательных профилей для схемы (§13.3)."""
    return {p: make_fixture(schema, p, locale=locale) for p in ("typical", "short", "long", "empty", "loading", "error", "edge-case")}


def materialize_ir(template_ir: dict, fixture: dict | None) -> dict:
    """Apply a deterministic preview fixture without mutating the master.

    ``source``/no fixture is the fidelity view and returns an exact deep copy.
    Other profiles only replace content-bearing values; geometry, styles,
    responsive overrides, source keys and hierarchy remain untouched.
    """
    result = copy.deepcopy(template_ir)
    if not isinstance(result, dict) or not isinstance(fixture, dict):
        return result
    profile = str(fixture.get("profile") or "source")
    if profile == "source":
        return result
    data = fixture.get("data") if isinstance(fixture.get("data"), dict) else {}
    values = [str(value) for key, value in data.items()
              if not str(key).startswith("__") and isinstance(value, (str, int, float))]
    index = 0

    def replacement(original: str) -> str:
        nonlocal index
        if profile == "empty":
            return ""
        if profile == "loading":
            value = "Loading…" if index == 0 else ""
            index += 1
            return value
        if profile == "error":
            value = str(data.get("__error") or "Could not load data") if index == 0 else ""
            index += 1
            return value
        if values:
            value = values[index % len(values)]
            index += 1
        else:
            value = original
        if profile == "short":
            return value[:max(3, min(18, len(value)))]
        if profile in ("long", "edge-case"):
            target = 120 if profile == "long" else 240
            value = (value + " ") * max(1, target // max(1, len(value)))
            return value.strip()[:target]
        return value

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if isinstance(node.get("text"), str):
            node["text"] = replacement(node["text"])
        props = node.get("props")
        if isinstance(props, dict):
            for key, value in list(props.items()):
                if key in data and isinstance(value, (str, int, float)):
                    props[key] = copy.deepcopy(data[key])
        for child in node.get("children") or []:
            visit(child)

    for root in result.get("tree") or []:
        visit(root)
    return result
