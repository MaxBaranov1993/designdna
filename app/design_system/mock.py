"""Mock data: deterministic fixtures по схеме+seed+profile (ТЗ §13).

Синтетика только: реальные персональные данные из Source не копируются (§13.4),
email/имена/телефоны заменяются правдоподобными синтетическими значениями.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

_PROFILES = ("typical", "short", "long", "empty", "loading", "error", "edge-case")

_SYNTH = {
    # формат поля -> генератор значения (никогда не real data)
    "name": lambda rng, locale: rng.choice(["Анна Ковалёва", "Иван Мельник", "Ольга Литвин", "Дмитрий Савин", "Мария Гончар"]),
    "email": lambda rng, locale: f"user{rng.randint(100, 999)}@example.com",
    "phone": lambda rng, locale: f"+7 9{rng.randint(10, 99)} {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}",
    "price": lambda rng, locale: round(rng.uniform(90, 99000), 2),
    "title": lambda rng, locale: rng.choice(["Компактный вариант", "Премиальная модель", "Базовый пакет", "Новая коллекция", "Популярный выбор"]),
    "sentence": lambda rng, locale: rng.choice([
        "Правдоподобный текст с конкретикой для проверки вёрстки.",
        "Более длинное описание, чтобы проверить перенос строк и обрезку контента в реальных условиях макета.",
        "Коротко.",
    ]),
    "url": lambda rng, locale: f"https://example.com/item/{rng.randint(1, 9999)}",
    "date": lambda rng, locale: f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
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
        return {"id": f"{schema_id}:error", "schemaId": schema_id, "locale": locale, "seed": seed_for(schema_id, profile), "profile": "error", "data": {"__error": "Не удалось загрузить данные"}}

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
