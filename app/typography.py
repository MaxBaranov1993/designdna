"""Типографический движок генератора: библиотека шрифтовых пар, type scale,
стилевые пресеты.

Идея: модель не придумывает шрифты и размеры из головы. Пары display+body —
кураторские (все с полной кириллицей, Google Fonts), размеры считаются по
модульной шкале, настроение задаёт пресет или ключевые слова брифа.
Приоритет источника шрифта: Style DNA из парсинга (лок в server.py) →
предпочтение пресета → подбор по настроению брифа.
"""
from __future__ import annotations

# ---------- библиотека шрифтовых пар (только полная кириллица) ----------

FONT_PAIRS: list[dict] = [
    {"name": "inter", "display": {"family": "Inter", "weight": 700},
     "body": {"family": "Inter", "weight": 400},
     "moods": {"neutral", "minimal", "tech", "corporate"}},
    {"name": "manrope", "display": {"family": "Manrope", "weight": 800},
     "body": {"family": "Inter", "weight": 400},
     "moods": {"modern", "product", "friendly", "bento", "minimal"}},
    {"name": "unbounded", "display": {"family": "Unbounded", "weight": 600},
     "body": {"family": "Manrope", "weight": 400},
     "moods": {"premium", "bold", "tech", "bento", "glass"}},
    {"name": "playfair", "display": {"family": "Playfair Display", "weight": 700},
     "body": {"family": "Source Sans 3", "weight": 400},
     "moods": {"editorial", "premium", "classic", "fashion"}},
    {"name": "plex", "display": {"family": "IBM Plex Sans", "weight": 600},
     "body": {"family": "IBM Plex Sans", "weight": 400},
     "moods": {"tech", "docs", "corporate", "neutral"}},
    {"name": "montserrat", "display": {"family": "Montserrat", "weight": 700},
     "body": {"family": "Open Sans", "weight": 400},
     "moods": {"corporate", "classic", "neutral"}},
    {"name": "sora", "display": {"family": "Sora", "weight": 700},
     "body": {"family": "Inter", "weight": 400},
     "moods": {"startup", "tech", "modern", "glass"}},
    {"name": "bebas", "display": {"family": "Bebas Neue", "weight": 400},
     "body": {"family": "Manrope", "weight": 400},
     "moods": {"brutal", "poster", "bold"}},
    {"name": "tenor", "display": {"family": "Tenor Sans", "weight": 400},
     "body": {"family": "Golos Text", "weight": 400},
     "moods": {"elegant", "fashion", "editorial", "premium"}},
    {"name": "golos", "display": {"family": "Golos Text", "weight": 700},
     "body": {"family": "Golos Text", "weight": 400},
     "moods": {"neutral", "cyrillic", "modern", "minimal"}},
]
PAIRS_BY_NAME = {p["name"]: p for p in FONT_PAIRS}

# ---------- стилевые пресеты (тренды UI/UX) ----------

PRESETS: dict[str, dict] = {
    "minimal": {
        "label": "Minimal",
        "moods": {"minimal", "neutral"},
        "font": "inter",
        "prompt": (
            "Минимализм: много воздуха (крупные padding секций), один акцентный "
            "цвет, тонкие бордеры 1px вместо теней, нейтральная палитра, "
            "никаких декоративных элементов без функции."),
    },
    "bento": {
        "label": "Bento",
        "moods": {"bento", "modern", "product"},
        "font": "manrope",
        "prompt": (
            "Bento-сетка: контент разбит на карточки-плитки с радиусами lg/xl, "
            "gap 16–24px, мягкие тени, плитки разного размера в одной сетке, "
            "каждая плитка — одна мысль с иконкой или метрикой."),
    },
    "editorial": {
        "label": "Editorial",
        "moods": {"editorial", "classic"},
        "font": "playfair",
        "prompt": (
            "Журнальная вёрстка: крупные serif-заголовки, узкая текстовая мера "
            "(не шире ~640px), выразительная иерархия заголовок/лид/текст, "
            "спокойная палитра, акцент на типографике, а не на декоре."),
    },
    "brutal": {
        "label": "Brutal",
        "moods": {"brutal", "poster", "bold"},
        "font": "bebas",
        "prompt": (
            "Брутализм: максимальный ч/б контраст, заголовки uppercase крупным "
            "кеглем, радиусы none (прямые углы), видимые бордеры 2–3px, "
            "плоские заливки, никаких теней и градиентов."),
    },
    "glass": {
        "label": "Glass",
        "moods": {"glass", "premium", "tech"},
        "font": "unbounded",
        "prompt": (
            "Glassmorphism: тёмный фон (mode dark), полупрозрачные поверхности, "
            "светящийся акцентный цвет, радиусы xl, мягкие свечения вместо "
            "жёстких теней, воздушные градиентные подложки."),
    },
}

# ---------- настроение из брифа ----------

_MOOD_KEYWORDS = {
    "minimal": ("минимал", "лаконич", "clean", "minimal", "простой"),
    "editorial": ("журнал", "стать", "медиа", "блог", "editorial", "новост"),
    "premium": ("премиум", "lux", "люкс", "premium", "элитн", "boutique", "бутик"),
    "tech": ("saas", "tech", "технолог", "платформ", "api", "dev", "it-", " ai"),
    "startup": ("стартап", "startup", "лендинг прилож", "mvp"),
    "brutal": ("брутал", "brutal", "постер", "дерзк", "громкий"),
    "elegant": ("элегант", "elegant", "мода", "fashion", "свадеб"),
    "corporate": ("корпорат", "банк", "финанс", "страхов", "b2b", "enterprise"),
    "friendly": ("дружелюб", "детск", "friendly", "игр", "edtech"),
    "glass": ("glass", "стекл", "неон", "neon", "кибер"),
    "bento": ("bento", "бенто", "дашборд", "dashboard", "метрик"),
}


def brief_moods(text: str) -> set[str]:
    """Настроения по ключевым словам брифа (RU/EN). Пусто — нейтральный дефолт."""
    low = f" {(text or '').lower()} "
    return {mood for mood, words in _MOOD_KEYWORDS.items()
            if any(w in low for w in words)}


def pick_pair(moods: set[str], prefer: str | None = None) -> dict:
    """Детерминированный выбор пары: prefer (из пресета) → скоринг по настроениям
    → нейтральный Inter. Порядок FONT_PAIRS — tie-break."""
    if prefer and prefer in PAIRS_BY_NAME:
        return PAIRS_BY_NAME[prefer]
    if moods:
        best, best_score = None, 0
        for pair in FONT_PAIRS:
            score = len(pair["moods"] & moods)
            if score > best_score:
                best, best_score = pair, score
        if best is not None:
            return best
    return PAIRS_BY_NAME["inter"]


# ---------- модульная шкала размеров ----------

def type_scale(base: float = 16.0, ratio: float = 1.25) -> dict:
    """Размеры по модульной шкале (px): display/h1/h2/h3/body/small."""
    def at(step: int) -> int:
        return int(round(base * (ratio ** step)))

    return {"display": at(4), "h1": at(3), "h2": at(2), "h3": at(1),
            "body": int(round(base)), "small": max(12, at(-1))}


def font_tokens(pair: dict, scale: str = "default") -> dict:
    """Токены font по схеме Design IR для выбранной пары."""
    return {"display": dict(pair["display"]), "body": dict(pair["body"]),
            "scale": scale}


# ---------- промпт-секция ----------

def typography_guide(pair: dict, scale: dict, preset: dict | None) -> str:
    """Готовая секция промпта: какие шрифты и размеры использовать."""
    lines = [
        "## Typography (обязательно)",
        f"Шрифты (оба с полной кириллицей): display = {pair['display']['family']} "
        f"{pair['display']['weight']}, body = {pair['body']['family']} "
        f"{pair['body']['weight']}. Запиши их в tokens.font.",
        f"Модульная шкала размеров: display {scale['display']}px, h1 {scale['h1']}px, "
        f"h2 {scale['h2']}px, h3 {scale['h3']}px, body {scale['body']}px, "
        f"small {scale['small']}px. Не выдумывай другие размеры.",
        "Длина строки основного текста — 55–75 символов; заголовок в карточке "
        "не должен переноситься по одному слову: ширина колонки под заголовок — "
        "от ~12 символов display-кегля.",
    ]
    if preset:
        lines.append(f"Стилевое направление «{preset['label']}»: {preset['prompt']}")
    return "\n".join(lines)
