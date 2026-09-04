"""Builder: Source Pack → reference-faithful draft Design System.

Observed masters are exact deep copies of Source component boundaries. Canonical
taxonomy is metadata only: it may name/classify a captured component, but it must
never replace its geometry, styles, responsive overrides, hierarchy or content.
Synthetic canonical templates live in ``suggestions`` and are excluded from the
publishable registry until a user explicitly promotes them.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any, Callable
from urllib.parse import urlparse

from . import mock as mock_mod
from .document import component_fidelity_status
from .document import content_hash as _content_hash
from .document import new_document
from .identity import extract_identity

# Должен совпадать с blockparse.SOURCE_COMPILER_VERSION: пак записывает эту
# версию, когда нода не передала свою. Расхождение (было "dom-v31" против
# "dom-v39") помечало свежие захваты устаревшим парсером. Синхронность
# проверяется тестом test_source_compiler_default_matches_pipeline.
SOURCE_COMPILER_DEFAULT = "dom-v41"
_GEN_STATES = ("hover", "loading", "error", "empty", "disabled")

# ---------- Style DNA нормализация ----------

_RADIUS_PX = {"none": 0, "sm": 4, "md": 8, "lg": 14, "xl": 22, "full": 999}
_CONTAINER_PX = {"narrow": 680, "default": 1120, "wide": 1360, "full": 1600}
_SECTION_PX = {"sm": 32, "md": 56, "lg": 96, "xl": 128}

_DEFAULT_DNA = {
    "mode": "light",
    "color": {
        "primary": "#111827", "secondary": "#374151", "accent": "#7c6cf0",
        "background": "#ffffff", "surface": "#f8fafc", "text": "#111827",
        "textMuted": "#6b7280", "border": "#e5e7eb",
    },
    "font": {"display": {"family": "Inter", "weight": 700},
             "body": {"family": "Inter", "weight": 400}, "scale": "default"},
    "radius": {"card": "lg", "button": "md", "input": "md"},
    "spacing": {"section": "lg", "container": "wide"},
    "shadow": "sm",
}


def _radius_to_enum(value: Any, default: str = "md") -> str:
    """px|enum → enum (пороги симметричны scraper._radius_enum)."""
    if isinstance(value, str) and value in _RADIUS_PX:
        return value
    try:
        px = float(value)
    except (TypeError, ValueError):
        return default
    if px >= 999:
        return "full"
    if px < 1:
        return "none"
    if px <= 4:
        return "sm"
    if px <= 10:
        return "md"
    if px <= 18:
        return "lg"
    return "xl"


def _spacing_enum(value: Any, default: str) -> str:
    if isinstance(value, str) and value in _SECTION_PX:
        return value
    try:
        px = float(value)
    except (TypeError, ValueError):
        return default
    if px < 40:
        return "sm"
    if px < 80:
        return "md"
    if px < 128:
        return "lg"
    return "xl"


def _container_enum(value: Any, default: str = "wide") -> str:
    if isinstance(value, str) and value in _CONTAINER_PX:
        return value
    try:
        px = float(value)
    except (TypeError, ValueError):
        return default
    if px < 720:
        return "narrow"
    if px <= 1152:
        return "default"
    if px <= 1440:
        return "wide"
    return "full"


def _shadow_enum(value: Any) -> str:
    if isinstance(value, str) and value in ("none", "sm", "md", "lg"):
        return value
    return "sm"


def _hex(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        return value.strip().lower()
    return None


def _family(value: Any, default: str = "Inter") -> str:
    text = str(value or "").strip().strip("'\"")
    return re.split(r",", text)[0].strip()[:60] or default


def _weight(value: Any, default: int) -> int:
    try:
        w = int(float(value))
    except (TypeError, ValueError):
        return default
    return w if 100 <= w <= 900 else default


def normalize_dna(tokens: dict | None) -> dict:
    """Частичные токены Source (или их отсутствие) → полная Style DNA.

    Принимает и enum-контракт схемы (radius='lg'), и легаси-числа
    (radius=8) — раньше числовые ожидания ломали радиусы foundations.
    """
    src = tokens if isinstance(tokens, dict) else {}
    dna = copy.deepcopy(_DEFAULT_DNA)
    color = src.get("color") if isinstance(src.get("color"), dict) else {}
    for key in dna["color"]:
        hexv = _hex(color.get(key))
        if hexv:
            dna["color"][key] = hexv
    # brand-палитра capture кладёт в primitives; поддержим и её
    primitives = src.get("primitives") if isinstance(src.get("primitives"), dict) else {}
    if not color and primitives:
        for key in dna["color"]:
            hexv = _hex(primitives.get(key))
            if hexv:
                dna["color"][key] = hexv
    if str(src.get("mode") or "").lower() in ("light", "dark"):
        dna["mode"] = str(src["mode"]).lower()

    font = src.get("font") if isinstance(src.get("font"), dict) else {}
    for role, default_weight in (("display", 700), ("body", 400)):
        entry = font.get(role)
        if isinstance(entry, dict):
            dna["font"][role] = {
                "family": _family(entry.get("family")),
                "weight": _weight(entry.get("weight"), default_weight),
            }
    if isinstance(font.get("scale"), str):
        dna["font"]["scale"] = font["scale"]

    radius = src.get("radius") if isinstance(src.get("radius"), dict) else {}
    for key in ("card", "button", "input"):
        if radius.get(key) is not None:
            dna["radius"][key] = _radius_to_enum(radius.get(key), dna["radius"][key])
    spacing = src.get("spacing") if isinstance(src.get("spacing"), dict) else {}
    if spacing.get("section") is not None:
        dna["spacing"]["section"] = _spacing_enum(spacing.get("section"), dna["spacing"]["section"])
    if spacing.get("container") is not None:
        dna["spacing"]["container"] = _container_enum(spacing.get("container"), dna["spacing"]["container"])
    dna["shadow"] = _shadow_enum(src.get("shadow"))
    return dna


def _dna_px(dna: dict) -> dict:
    return {k: _RADIUS_PX[v] for k, v in dna["radius"].items()}


def _tokens_for_ir(dna: dict) -> dict:
    """DNA → schema-валидные IR-токены (enum-контракт радиусов/интервалов)."""
    return {
        "mode": dna["mode"],
        "color": dict(dna["color"]),
        "font": copy.deepcopy(dna["font"]),
        "radius": dict(dna["radius"]),
        "spacing": copy.deepcopy(dna["spacing"]),
        "shadow": dna["shadow"],
    }


# ---------- референсный контент (мок-данные в стиле источника) ----------

_PRICE_RE = re.compile(r"\d[\d\s\u00a0]{0,9}(?:[.,]\d{1,2})?\s*(?:₽|руб\.?|р\.|€|\$|₸)", re.IGNORECASE)
_PRIVACY_RE = re.compile(r"@|\+?\d[\d\s(-]{6,}|\d{4,}", re.IGNORECASE)
_BAD_NAME_RE = re.compile(r"^[\s\d.,:;·•—–\-|/()№%]+$|^(?:шаг|step|слайд|slide)\b", re.IGNORECASE)
# служебные элементы интерфейса, которые не несут продуктового смысла:
# переключатели языка (RU/EN/KZ), cookie-баннеры, технические рубрики
_UTILITY_WORDS = {
    "cookie", "cookies", "ru", "en", "kz", "ua", "by", "uz", "de", "fr", "es",
    "англ", "rus", "eng", "skip", "закрыть", "понятно", "ок", "devlog", "blog",
    "news", "svg", "logo",
}
_LANG_CODE_RE = re.compile(r"^[A-ZА-ЯЁ]{2}$")
# «Максим Баранов» — персоналия продавца из карточки: в моках ей не место (§13.4)
_PERSON_NAME_RE = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]{2,}\s+[A-ZА-ЯЁ][a-zа-яё]{2,}$")
_QUESTION_WORD_RE = re.compile(r"^(как|что|почему|где|когда|сколько|можно|нужно|какой|какая|есть)\b", re.IGNORECASE)

_DEFAULT_CONTENT = {
    "brand": "Бренд",
    "nav": ["Главная", "Каталог", "Избранное", "Профиль"],
    "cta": ["Подробнее", "В корзину", "Отправить"],
    "heading": ["Популярные товары", "Новые поступления", "Выгодные предложения"],
    "title": ["Компактная модель", "Премиальная модель", "Базовый пакет"],
    "price": ["4 990 ₽", "12 400 ₽", "1 299 ₽"],
    "category": ["Электроника", "Для дома", "Аксессуары", "Хобби"],
    "badge": ["Хит", "Новинка", "-25%"],
    "question": ["Как оформить доставку?", "Есть ли гарантия?", "Как оплатить заказ?"],
    "answer": [
        "Курьер привезёт заказ в течение двух дней, дату можно выбрать при оформлении.",
        "На все товары действует гарантия двенадцать месяцев с момента покупки.",
        "Доступна оплата картой, наличными при получении и в рассрочку.",
    ],
    "caption": "Обновляйте контент через mock-данные",
}

# Англоязычный референс без товаров/цен не должен смешиваться с русскими
# дефолтами («Prove it →» рядом с «Компактная модель»): пустые бакеты
# заполняются дефолтами языка доминирующего script'а референса.
_DEFAULT_CONTENT_EN = {
    "brand": "Brand",
    "nav": ["Home", "Catalog", "Favorites", "Profile"],
    "cta": ["Learn more", "Add to cart", "Submit"],
    "heading": ["Popular products", "New arrivals", "Best deals"],
    "title": ["Compact model", "Premium model", "Starter pack"],
    "price": ["$49", "$120", "$13"],
    "category": ["Electronics", "Home", "Accessories", "Hobby"],
    "badge": ["Hot", "New", "-25%"],
    "question": ["How do I arrange delivery?", "Is there a warranty?", "How can I pay?"],
    "answer": [
        "The courier will deliver your order within two days; pick a date at checkout.",
        "Every item is covered by a twelve-month warranty from the purchase date.",
        "Pay by card, in cash on delivery, or in installments.",
    ],
    "caption": "Update content via mock data",
}


def _clean_label(text: Any, limit: int = 64) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value or len(value) < 2 or len(value) > limit:
        return ""
    if _PRIVACY_RE.search(value) or _BAD_NAME_RE.match(value):
        return ""
    if value.lower().startswith(("svelte-", "astro-", "next-", "gatsby-", "vue-")):
        return ""
    return value


def _is_utility(text: str) -> bool:
    """Служебный элемент (переключатель языка, cookie, тех-рубрика)?

    Такие тексты — реальный DOM сайта, но как мок-контент UI kit'а они мусор:
    «RU» превращалось в CTA-кнопку, «Cookie»/«Карта» — в пункты навбара.
    """
    low = text.lower().strip()
    return low in _UTILITY_WORDS or _LANG_CODE_RE.match(text.strip()) is not None


def _top(counter: Counter, limit: int = 8) -> list[str]:
    return [v for v, _ in counter.most_common() if v][:limit]


def harvest_reference_content(blocks: list) -> dict:
    """Тексты Source → мок-контент референса (категории, CTA, заголовки…).

    Персональные данные (email/телефоны/длинные числа) и технический мусор
    (имена фреймворков в классах, «1 из 9») отфильтровываются: в моках
    остаётся только продуктовый контент источника (§13.4 — синтетика
    персоналии не копируется).
    """
    buckets = {key: Counter() for key in ("nav", "cta", "heading", "title", "price", "category", "badge", "question")}
    faq_answers: Counter = Counter()

    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("ir"), dict):
            continue
        kind = str(block.get("kind") or "section").lower()
        roots = list((block["ir"].get("tree") or []))

        def visit(node: dict, depth: int = 0, role_hint: str = "") -> None:
            if not isinstance(node, dict):
                return
            meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
            role = str(meta.get("componentRole") or role_hint or node.get("type") or "").lower()
            ntype = str(node.get("type") or "").lower()
            text = _clean_label(node.get("text") if ntype in ("button", "text", "heading") else "")
            utility = bool(text) and _is_utility(text)

            if ntype == "button" and text and not utility and len(text) >= 4:
                buckets["cta"][text] += 1
            if ntype == "heading" and text:
                buckets["heading"][text] += 1
            # навбар — пункты верхнего меню (шапка/навигация), а не служебные
            # ссылки футера (cookie, карта сайта) и не переключатели языка
            if (role in ("nav", "navigation", "menu", "toolbar") and text
                    and not utility and len(text) <= 24 and depth >= 1
                    and kind not in ("footer", "faq", "journal")):
                buckets["nav"][text] += 1
            if role == "status" and text and len(text) <= 20 and not utility:
                buckets["badge"][text] += 1
            if _PRICE_RE.search(str(node.get("text") or "")):
                price = _PRICE_RE.search(str(node.get("text"))).group(0).replace("\u00a0", " ").strip()
                buckets["price"][price] += 1

            if (kind == "faq" and ntype == "heading" and text
                    and ("?" in text or _QUESTION_WORD_RE.match(text))):
                buckets["question"][text] += 1
                for child in node.get("children") or []:
                    answer = _clean_label(child.get("text") if isinstance(child, dict) else "", 140)
                    if answer and len(answer) > 20:
                        faq_answers[answer] += 1
            if (kind in ("product-grid", "journal") and ntype in ("text", "heading")
                    and depth >= 2 and 10 <= len(text) <= 60 and not utility
                    and len(text.split()) >= 2 and not _PERSON_NAME_RE.match(text)):
                buckets["title"][text] += 1
            if kind == "categories" and ntype in ("text", "heading") and text and len(text) <= 30 and not utility:
                buckets["category"][text] += 1

            for child in node.get("children") or []:
                visit(child, depth + 1, role if role in ("nav", "navigation", "menu", "toolbar", "status") else "")

        for root in roots:
            visit(root)

    harvested = {key: _top(counter) for key, counter in buckets.items()}
    if faq_answers:
        harvested["answer"] = _top(faq_answers)
    # базовые дефолты — на языке референса: латиница в собранных текстах
    # означает англоязычный сайт, русские дефолты рядом с «Prove it →»
    # выглядели бы мешаниной в каждой карточке
    sample = [v for key in ("nav", "cta", "heading", "title", "category", "badge", "question")
              for v in harvested.get(key, [])]
    latin = sum(len(re.findall(r"[A-Za-z]", v)) for v in sample)
    cyrillic = sum(len(re.findall(r"[А-Яа-яЁё]", v)) for v in sample)
    base = _DEFAULT_CONTENT_EN if latin > cyrillic else _DEFAULT_CONTENT
    content = dict(base)
    for key, values in harvested.items():
        if values:
            content[key] = values
    return content


def _brand_from_url(url: Any) -> str:
    """Бренд kit'а — имя хоста референса (rsale.net → Rsale), не лейбл блока."""
    try:
        host = urlparse(str(url or "")).netloc or str(url or "")
    except Exception:
        host = str(url or "")
    host = host.strip().lower().removeprefix("www.")
    name = host.split(".")[0] if "." in host else host
    name = re.sub(r"[^a-z0-9а-яё-]+", "", name).strip("-")
    if not name or _is_utility(name):
        return ""
    return name[:20].capitalize()


# ---------- каноническая таксономия (shadcn/ui-уровень) ----------

def _sec(children: list, *, width: int = 460, direction: str = "column", gap: int = 14) -> dict:
    return {
        "id": "ds-master",
        "type": "source-block",
        "variant": "ds-master",
        "props": {},
        "frame": {"width": width, "layout": "auto", "direction": direction, "gap": gap, "padding": 20},
        "children": children,
    }


def _btn(dna: dict, text: str, variant: str = "primary", *, width: Any = "hug", height: int = 44) -> dict:
    return {
        "type": "button", "text": text, "variant": variant,
        "style": {"borderRadius": _dna_px(dna)["button"],
                  "fontWeight": dna["font"]["body"]["weight"]},
        "frame": {"width": width, "height": height, "layout": "auto", "direction": "row", "justify": "center", "align": "center"},
    }


def _txt(dna: dict, text: str, *, size: int = 15, weight: int | None = None, color: str | None = None,
         muted: bool = False, width: Any = "fill", height: int = 24) -> dict:
    style = {"fontSize": size, "lineHeight": 1.45,
             "fontWeight": weight or dna["font"]["body"]["weight"]}
    if muted:
        style["color"] = dna["color"]["textMuted"]
    elif color:
        style["color"] = color
    return {"type": "text", "text": text, "style": style,
            "frame": {"width": width, "height": height}}


def _head(dna: dict, text: str, level: int = 2, *, size: int | None = None) -> dict:
    sizes = {1: 40, 2: 28, 3: 21}
    return {
        "type": "heading", "level": level, "text": text,
        "style": {"fontSize": size or sizes[level], "fontWeight": dna["font"]["display"]["weight"],
                  "color": dna["color"]["text"]},
        "frame": {"width": "fill", "height": round((size or sizes[level]) * 1.3)},
    }


def _card_shell(dna: dict, *, direction: str = "column", gap: int = 12, padding: int = 18,
                width: Any = "fill", background: str | None = None,
                children: list | None = None) -> dict:
    px = _dna_px(dna)
    return {
        "type": "card", "role": "ds-surface",
        "style": {"background": background or dna["color"]["surface"],
                  "borderColor": dna["color"]["border"], "borderWidth": 1,
                  "borderRadius": px["card"]},
        "frame": {"width": width, "layout": "auto", "direction": direction, "gap": gap, "padding": padding},
        "children": children or [],
    }


def _input_el(dna: dict, placeholder: str, *, multiline: bool = False) -> dict:
    px = _dna_px(dna)
    return {
        "type": "input", "placeholder": placeholder,
        "style": {"background": dna["color"]["background"],
                  "borderColor": dna["color"]["border"], "borderWidth": 1,
                  "borderRadius": px["input"], "color": dna["color"]["textMuted"],
                  "fontSize": 15, "lineHeight": 1.45},
        "frame": {"width": "fill", "height": 112 if multiline else 46, "layout": "auto",
                  "direction": "row", "align": "center", "padding": [0, 14]},
    }


def _badge_el(dna: dict, text: str, tone: str = "primary") -> dict:
    return {
        "type": "badge", "text": text, "tone": tone,
        "style": {"borderRadius": min(_dna_px(dna)["button"], 999), "fontSize": 12,
                  "fontWeight": 600},
        "frame": {"width": "hug", "height": 26},
    }


def _avatar_el(dna: dict, name: str, role: str = "") -> dict:
    return {
        "type": "avatar", "name": name, "role": role,
        "style": {},
        "frame": {"width": "fill", "height": 44},
    }


def _product_card_el(dna: dict, content: dict, index: int = 0) -> dict:
    card = _card_shell(dna, gap=10, padding=0, width="fill")
    titles, prices, badges = content["title"], content["price"], content["badge"]
    image = {"type": "image", "alt": titles[index % len(titles)],
             "style": {"borderRadius": _dna_px(dna)["card"], "background": dna["color"]["border"]},
             "frame": {"width": "fill", "height": 150}}
    title = _txt(dna, titles[index % len(titles)], size=15, weight=600, color=dna["color"]["text"])
    price = _txt(dna, prices[index % len(prices)], size=18,
                 weight=dna["font"]["display"]["weight"], color=dna["color"]["primary"])
    cta = _btn(dna, content["cta"][index % len(content["cta"])], "primary", height=38)
    badge = _badge_el(dna, badges[index % len(badges)])
    card["children"] = [image, badge, title, price, cta]
    card["frame"]["padding"] = 12
    return card


def _tile_el(dna: dict, label: str, index: int) -> dict:
    tile = _card_shell(dna, direction="column", gap=8, padding=16, width="fill")
    tile["children"] = [
        {"type": "icon", "icon": label[:1].upper(), "style": {}, "frame": {"width": 40, "height": 40}},
        _txt(dna, label, size=15, weight=600, color=dna["color"]["text"], height=20),
    ]
    return tile


# Каждая запись: ключ shadcn-стиля, имя, категория, описание, states (generated),
# мок-схема (поля; формат/enum подставляется позже), сборка шаблона от DNA+контента.
def _build_library(dna: dict, content: dict) -> list[dict]:
    px = _dna_px(dna)
    c = content
    primary, surface, border, muted = (dna["color"]["primary"], dna["color"]["surface"],
                                       dna["color"]["border"], dna["color"]["textMuted"])
    specs: list[dict] = []

    def spec(key: str, name: str, category: str, description: str, states: list[str],
             mock_fields: list[dict], build: Callable[[], list[dict]]) -> None:
        specs.append({"key": key, "name": name, "category": category, "description": description,
                      "states": states, "mockFields": mock_fields, "build": build})

    spec("button", "Button", "actions", "Кнопка действий; варианты из референса (заливка/контур/ghost)",
         ["hover", "loading", "disabled"], [{"name": "text", "format": "cta"}],
         lambda: [_sec([_btn(dna, c["cta"][0], "primary"),
                        _btn(dna, c["cta"][1 % len(c["cta"])], "secondary"),
                        _btn(dna, c["cta"][2 % len(c["cta"])], "outline"),
                        _btn(dna, c["cta"][0], "ghost")], direction="row", gap=10, width=520)])

    spec("icon-button", "Icon Button", "actions", "Квадратная кнопка-иконка (44×44, тач-зона)",
         ["hover", "disabled"], [{"name": "icon", "format": "word"}],
         lambda: [_sec([{**_btn(dna, "✎", "outline", width=44, height=44),
                         "style": {"borderRadius": px["button"], "fontSize": 16}},
                        {**_btn(dna, "♡", "ghost", width=44, height=44),
                         "style": {"fontSize": 16}}], direction="row", gap=10)])

    spec("input", "Input", "forms", "Однострочное поле ввода в стиле референса",
         ["focus", "error", "disabled"], [{"name": "placeholder", "format": "sentence"}],
         lambda: [_sec([_txt(dna, "Email", size=13, weight=600, muted=True, height=18),
                        _input_el(dna, "user@example.com")])])

    spec("search", "Search Field", "forms", "Поисковая строка с кнопкой (типично для референса)",
         ["focus", "loading"], [{"name": "query", "format": "sentence"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"borderColor": border, "borderWidth": 1,
                                                                        "borderRadius": px["input"], "background": dna["color"]["background"]},
                        "frame": {"width": "fill", "height": 46, "layout": "auto", "direction": "row",
                                  "gap": 8, "align": "center", "padding": [0, 6, 0, 14]},
                        "children": [{"type": "icon", "icon": "⌕", "style": {"color": muted}, "frame": {"width": 22, "height": 22}},
                                     _txt(dna, "Поиск по каталогу", muted=True, height=20),
                                     _btn(dna, c["cta"][0], "primary", height=36)]}])])

    spec("textarea", "Textarea", "forms", "Многострочное поле (комментарий, сообщение)",
         ["focus", "error"], [{"name": "text", "format": "sentence"}],
         lambda: [_sec([_input_el(dna, "Комментарий к заказу…", multiline=True)])])

    spec("select", "Select", "forms", "Выпадающий список",
         ["hover", "disabled"], [{"name": "value", "format": "word"}],
         lambda: [_sec([{**_input_el(dna, c["category"][0]), "frame": {"width": "fill", "height": 46, "layout": "auto",
                                                                        "direction": "row", "align": "center", "padding": [0, 14]},
                        "children": [_txt(dna, c["category"][0], size=15, height=20),
                                     _txt(dna, "▾", size=14, muted=True, height=20)]}])])

    spec("checkbox", "Checkbox", "forms", "Чекбокс с подписью",
         ["checked", "disabled"], [{"name": "label", "format": "sentence"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 10, "align": "center"},
                     "children": [{"type": "rect", "fill": primary, "radius": min(px["input"], 8),
                                   "style": {"borderRadius": min(px["input"], 8)},
                                   "frame": {"width": 20, "height": 20, "layout": "auto", "direction": "row",
                                             "justify": "center", "align": "center"},
                                   "children": [_txt(dna, "✓", size=13, color="#ffffff", height=16)]},
                                  _txt(dna, "Согласен с условиями", size=14, height=20)]}])])

    spec("switch", "Switch", "forms", "Переключатель вкл/выкл",
         ["checked", "disabled"], [{"name": "label", "format": "sentence"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 10, "align": "center"},
                     "children": [{"type": "rect", "fill": primary, "radius": 999, "style": {"borderRadius": 999},
                                   "frame": {"width": 44, "height": 24, "layout": "free"},
                                   "children": [{"type": "rect", "fill": "#ffffff", "radius": 999,
                                                 "style": {"borderRadius": 999, "boxShadow": "0 1px 2px rgba(0,0,0,.2)"},
                                                 "frame": {"width": 18, "height": 18, "absolute": True, "x": 23, "y": 3}}]},
                                  _txt(dna, "Уведомления", size=14, height=20)]}])])

    spec("badge", "Badge", "feedback", "Метка статиса/скидки (контент — из референса)",
         [], [{"name": "text", "format": "badge"}],
         lambda: [_sec([_badge_el(dna, c["badge"][0], "primary"),
                        _badge_el(dna, c["badge"][1 % len(c["badge"])], "muted"),
                        _badge_el(dna, c["badge"][2 % len(c["badge"])], "accent")], direction="row", gap=8)])

    spec("alert", "Alert", "feedback", "Статусное сообщение (info/success/warning/error)",
         [], [{"name": "text", "format": "sentence"}],
         lambda: [_sec([_card_shell(dna, direction="row", gap=10, padding=14, background=surface,
                                    children=[{"type": "icon", "icon": "✓", "style": {"color": primary}, "frame": {"width": 22, "height": 22}},
                                              _txt(dna, "Заказ оформлен — курьер приедет 26 августа", size=14, height=38)])])])

    spec("skeleton", "Skeleton", "feedback", "Плейсхолдер загрузки в стиле референса",
         [], [],
         lambda: [_sec([{k: v for k, v in _card_shell(dna, gap=10).items() if k != "children"} |
                        {"children": [
                            {"type": "rect", "fill": border, "radius": px["card"] // 2, "style": {"borderRadius": px["card"] // 2},
                             "frame": {"width": "fill", "height": 120}},
                            {"type": "rect", "fill": border, "radius": 6, "style": {"borderRadius": 6},
                             "frame": {"width": 220, "height": 16}},
                            {"type": "rect", "fill": border, "radius": 6, "style": {"borderRadius": 6},
                             "frame": {"width": 120, "height": 16}}]}])])

    spec("divider", "Divider", "surfaces", "Разделитель", [], [],
         lambda: [_sec([{"type": "divider", "style": {"background": border},
                         "frame": {"width": "fill", "height": 1}}])])

    spec("card", "Card", "surfaces", "Базовая карточка-поверхность",
         [], [{"name": "title", "format": "title"}, {"name": "text", "format": "sentence"}],
         lambda: [_sec([_card_shell(dna, children=[
             _head(dna, c["heading"][0], 3),
             _txt(dna, "Короткое описание содержимого карточки в две строки.", muted=True, height=40),
             _btn(dna, c["cta"][0], "primary", height=38)])])])

    spec("accordion", "Accordion / FAQ", "surfaces", "Раскрывающийся список вопросов-ответов (контент референса)",
         [], [{"name": "question", "format": "question"}, {"name": "answer", "format": "answer"}],
         lambda: [
             {"id": "ds-accordion", "type": "faq", "variant": "stack",
              "props": {"heading": c["heading"][0],
                        "items": [{"question": q, "answer": c["answer"][i % len(c["answer"])]}
                                  for i, q in enumerate(c["question"][:4])]}}])

    spec("navbar", "Navbar", "navigation", "Шапка с меню и CTA (пункты — из референса)",
         ["sticky"], [{"name": "items", "format": "nav"}],
         lambda: [{"id": "ds-navbar", "type": "navbar", "variant": "default",
                   "props": {"logoText": c["brand"],
                             "links": [{"label": item, "href": "#"} for item in c["nav"][:5]],
                             "cta": {"text": c["cta"][0], "variant": "primary"}, "sticky": True}}])

    spec("breadcrumb", "Breadcrumb", "navigation", "Хлебные крошки", [], [{"name": "items", "format": "nav"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 6, "align": "center"},
                     "children": [_txt(dna, " / ".join([c["nav"][0], c["category"][0]]), size=13, muted=True, height=18)]}])])

    spec("tabs", "Tabs", "navigation", "Набор вкладок", ["hover"], [{"name": "items", "format": "nav"}],
         lambda: [_sec([{"type": "card", "role": "ds-field",
                     "style": {"background": dna["color"]["background"], "borderColor": border,
                               "borderWidth": 1, "borderRadius": px["button"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 4, "padding": 4},
                     "children": [
                         {**_btn(dna, c["nav"][0], "primary", height=34),
                          "style": {"borderRadius": px["button"]}},
                         _btn(dna, c["nav"][1 % len(c["nav"])], "ghost", height=34),
                         _btn(dna, c["nav"][2 % len(c["nav"])], "ghost", height=34)]}])])

    spec("pagination", "Pagination", "navigation", "Постраничная навигация", ["disabled"], [{"name": "page", "format": "word"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 6},
                     "children": [_btn(dna, "‹", "outline", width=36, height=36)] +
                                  [_btn(dna, str(i + 1), "primary" if i == 0 else "outline", width=36, height=36)
                                   for i in range(3)] +
                                  [_btn(dna, "›", "outline", width=36, height=36)]}])])

    spec("footer", "Footer", "navigation", "Подвал с колонками ссылок (контент референса)",
         [], [{"name": "items", "format": "nav"}],
         lambda: [{"id": "ds-footer", "type": "footer", "variant": "columns",
                   "props": {"logoText": c["brand"], "tagline": "Маркетплейс-референс для UI Kit",
                             "columns": [{"title": col, "links": [{"label": item, "href": "#"} for item in c["nav"][:3]]}
                                         for col in c["category"][:3]],
                             "copyright": f"© 2026 {c['brand']}"}}])

    spec("product-card", "Product Card", "content", "Карточка товара: фото, бейдж, цена, CTA (моки — из референса)",
         ["loading", "empty"], [{"name": "title", "format": "title"}, {"name": "price", "format": "price"},
                                {"name": "badge", "format": "badge"}, {"name": "image", "format": "url"}],
         lambda: [_sec([{"type": "card", "role": "ds-grid", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 14, "wrap": True},
                     "children": [_product_card_el(dna, c, i) for i in range(2)]}], width=640)])

    spec("category-tile", "Category Tile", "content", "Плитка категории (названия — из референса)",
         [], [{"name": "label", "format": "category"}],
         lambda: [_sec([{"type": "card", "role": "ds-grid", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 12, "wrap": True},
                     "children": [_tile_el(dna, label, i) for i, label in enumerate(c["category"][:4])]}], width=560)])

    spec("article-card", "Article Card", "content", "Карточка материала/поста (журнал референса)",
         [], [{"name": "title", "format": "title"}, {"name": "text", "format": "sentence"}],
         lambda: [_sec([_card_shell(dna, padding=0, children=[
             {"type": "image", "alt": c["heading"][0],
              "style": {"borderRadius": px["card"], "background": border},
              "frame": {"width": "fill", "height": 130}},
             _head(dna, c["heading"][0], 3),
             _txt(dna, "Анонс материала: пара строк о содержании и дате публикации.", muted=True, height=40)])])])

    spec("carousel", "Carousel", "content", "Карусель слайдов с точками (как в референсе)",
         ["loading"], [{"name": "title", "format": "title"}, {"name": "price", "format": "price"}],
         lambda: [_sec([_head(dna, c["heading"][0], 3),
                        _product_card_el(dna, c, 0),
                        {"type": "card", "role": "ds-dots", "style": {"background": dna["color"]["background"]},
                         "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 6, "justify": "center"},
                         "children": [{"type": "rect", "fill": primary, "radius": 999, "style": {"borderRadius": 999},
                                       "frame": {"width": 8, "height": 8}}] +
                                     [{"type": "rect", "fill": border, "radius": 999, "style": {"borderRadius": 999},
                                       "frame": {"width": 8, "height": 8}} for _ in range(3)]}], width=420)])

    spec("cta-banner", "CTA Banner", "content", "Промо-блок с заголовком и кнопками",
         [], [{"name": "heading", "format": "heading"}],
         lambda: [{"id": "ds-cta", "type": "cta", "variant": "default",
                   "props": {"heading": c["heading"][0],
                             "subheading": "Соберите блок в стиле референса за один промпт.",
                             "ctaPrimary": {"text": c["cta"][0], "variant": "primary"},
                             "ctaSecondary": {"text": c["cta"][1 % len(c["cta"])], "variant": "outline"}}}])

    spec("price", "Price", "content", "Цена: текущая + зачёркнутая старая (формат референса)",
         [], [{"name": "price", "format": "price"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 10, "align": "center"},
                     "children": [_txt(dna, c["price"][0], size=20, weight=dna["font"]["display"]["weight"],
                                       color=primary, height=26),
                                  _txt(dna, c["price"][1 % len(c["price"])], size=14, muted=True, height=20)]}])])

    spec("rating", "Rating", "content", "Рейтинг звёздами", [], [{"name": "value", "format": "word"}],
         lambda: [_sec([{"type": "card", "role": "ds-field", "style": {"background": dna["color"]["background"]},
                     "frame": {"width": "fill", "layout": "auto", "direction": "row", "gap": 8, "align": "center"},
                     "children": [{"type": "rating", "value": 4, "style": {}, "frame": {"width": 110, "height": 20}},
                                  _txt(dna, "4,2 · 128 оценок", size=13, muted=True, height=18)]}])])

    spec("list", "List", "content", "Список пунктов с маркерами", [], [{"name": "items", "format": "sentence"}],
         lambda: [_sec([{"type": "list", "items": c["nav"][:4], "style": {},
                     "frame": {"width": "fill", "height": 120}}])])

    spec("avatar", "Avatar", "media", "Аватар с именем и ролью (синтетические персоналии)",
         [], [{"name": "name", "format": "name"}, {"name": "role", "format": "word"}],
         lambda: [_sec([_avatar_el(dna, "Анна Ковалёва", "Продавец· 4,9")])])

    spec("heading", "Heading", "typography", "Заголовки шкалы референса (display→h3)",
         [], [{"name": "text", "format": "heading"}],
         lambda: [_sec([_head(dna, c["heading"][0], 1), _head(dna, c["heading"][1 % len(c["heading"])], 2),
                        _head(dna, c["heading"][2 % len(c["heading"])], 3)], width=560)])

    spec("text", "Text", "typography", "Основной и вспомогательный текст",
         [], [{"name": "text", "format": "sentence"}],
         lambda: [_sec([_txt(dna, "Основной текст абзаца в теле сайта референса.", size=16, height=26),
                        _txt(dna, "Вспомогательная подпись и уточнения.", size=13, muted=True, height=20)],
                       width=520)])

    return specs


# ---------- маппинг наблюдений Source на канонические ключи ----------

_KIND_TO_KEY = {
    "header": ("navbar",), "navigation": ("navbar",), "footer": ("footer",),
    "carousel": ("carousel",), "categories": ("category-tile",),
    "product-grid": ("product-card",), "services-grid": ("category-tile",),
    "journal": ("article-card",), "faq": ("accordion",), "cta": ("cta-banner",),
    "trust": ("card",), "pricing": ("price",), "testimonials": ("card",),
    "gallery": ("carousel",), "toolbar": ("navbar",), "profile": ("avatar",),
    "panel": ("card",), "status": ("badge",), "section": ("card",),
}

_TYPE_TO_KEY = {
    "button": ("button",), "input": ("input",), "card": ("card",),
    "heading": ("heading",), "text": ("text",), "image": ("category-tile",),
    "badge": ("badge",), "avatar": ("avatar",), "rating": ("rating",),
    "list": ("list",), "icon": ("icon-button",),
}

# ---------- сборка документа ----------


def _walk_nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.get("tree") or []:
            yield from _walk_nodes(child)
        for child in value.get("children") or []:
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_nodes(item)


def _absolute_component_frame(node: dict, ancestors: tuple[dict, ...], viewport: str) -> dict | None:
    """Resolve a captured node frame relative to the Source block root.

    Source Import stores every child frame relative to its parent. Design
    System evidence crops, however, address the full block screenshot. Keep the
    published master local/editable and make only the evidence bounds absolute.
    """
    absolute_x = 0.0
    absolute_y = 0.0
    frame: dict = {}
    for part in (*ancestors, node):
        if not isinstance(part, dict):
            continue
        base = part.get("frame") if isinstance(part.get("frame"), dict) else {}
        override = ((part.get("responsive") or {}).get(viewport) or {})
        if isinstance(override, dict) and override.get("visible") is False:
            return None
        override_frame = (override.get("frame")
                          if isinstance(override, dict) and isinstance(override.get("frame"), dict)
                          else {})
        current = {**base, **override_frame}
        absolute_x += float(current.get("x") or 0)
        absolute_y += float(current.get("y") or 0)
        if part is node:
            frame = current
    if any(not isinstance(frame.get(key), (int, float)) for key in ("width", "height")):
        return None
    return {**copy.deepcopy(frame), "x": absolute_x, "y": absolute_y}


def _measured_foundation_values(blocks: list) -> dict:
    colors: Counter[str] = Counter()
    families: Counter[str] = Counter()
    weights: Counter[int] = Counter()
    font_sizes: Counter[float] = Counter()
    radii: Counter[float] = Counter()
    spacings: Counter[float] = Counter()
    shadows: Counter[str] = Counter()
    breakpoints: dict[str, int] = {}
    root_widths: list[float] = []

    def number(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    for block in blocks or []:
        ir = block.get("ir") if isinstance(block, dict) else None
        if not isinstance(ir, dict):
            continue
        responsive = (ir.get("responsive") or {}).get("viewports") or {}
        if isinstance(responsive, dict):
            for name, config in responsive.items():
                width = number((config or {}).get("width") if isinstance(config, dict) else None)
                if width and width > 0:
                    breakpoints[str(name)] = int(round(width))
        sizes = block.get("sizes") if isinstance(block.get("sizes"), dict) else {}
        for name, config in sizes.items():
            width = number((config or {}).get("width") if isinstance(config, dict) else None)
            if width and width > 0:
                breakpoints.setdefault(str(name), int(round(width)))
        for root in ir.get("tree") or []:
            frame = root.get("frame") if isinstance(root, dict) and isinstance(root.get("frame"), dict) else {}
            width = number(frame.get("width"))
            if width and width > 0:
                root_widths.append(width)
        for node in _walk_nodes(ir.get("tree") or []):
            style = node.get("style") if isinstance(node.get("style"), dict) else {}
            for key in ("color", "background", "borderColor"):
                color = _hex(style.get(key))
                if color:
                    colors[color] += 1
            if node.get("type") == "rect":
                color = _hex(node.get("fill"))
                if color:
                    colors[color] += 1
            family = str(style.get("fontFamily") or "").split(",")[0].strip().strip("'\"")
            if family:
                families[family[:60]] += 1
            weight = number(style.get("fontWeight"))
            if weight and 100 <= weight <= 900:
                weights[int(round(weight))] += 1
            size = number(style.get("fontSize"))
            if size and size > 0:
                font_sizes[round(size, 2)] += 1
            radius = number(style.get("borderRadius"))
            if radius is None:
                radius = number(node.get("radius"))
            if radius is not None and radius >= 0:
                radii[round(radius, 2)] += 1
            shadow = str(style.get("boxShadow") or "").strip()
            if shadow and shadow != "none":
                shadows[shadow[:240]] += 1
            frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
            for key in ("gap", "padding"):
                raw = frame.get(key)
                values = raw if isinstance(raw, list) else [raw]
                for value in values:
                    spacing = number(value)
                    if spacing and spacing > 0:
                        spacings[round(spacing, 2)] += 1
    return {
        "colors": [value for value, _ in colors.most_common(16)],
        "families": [value for value, _ in families.most_common(8)],
        "weights": sorted(weights),
        "fontSizes": sorted(font_sizes, reverse=True),
        "radii": sorted(radii),
        "spacings": sorted(spacings),
        "shadows": [value for value, _ in shadows.most_common(12)],
        "breakpoints": breakpoints,
        "containers": sorted(set(round(value, 2) for value in root_widths)),
    }

def build_source_pack(source_node_data: dict, *, source_node_id: Any = 0) -> dict:
    """Source Pack from a Source node, including exact IR and fidelity evidence."""
    blocks = source_node_data.get("blocks") or []
    pack_blocks = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("error") or not block.get("ir"):
            continue
        packed = {
            "name": block.get("name"),
            "label": block.get("label"),
            "kind": block.get("kind") or "section",
            "selector": block.get("selector") or "",
            "ir": copy.deepcopy(block.get("ir")),
            "preview": block.get("preview"),
            "previews": copy.deepcopy(block.get("previews") or {}),
            "sizes": copy.deepcopy(block.get("sizes") or {}),
            "fidelity": copy.deepcopy(block.get("fidelity") or {}),
            "p95LayoutError": copy.deepcopy(block.get("p95LayoutError") or {}),
            "paintCoverage": copy.deepcopy(block.get("paintCoverage") or block.get("coverage") or {}),
            "droppedByViewport": copy.deepcopy(block.get("droppedByViewport") or {}),
            "extrasByViewport": copy.deepcopy(block.get("extrasByViewport") or {}),
            "fidelityReport": copy.deepcopy(block.get("fidelityReport") or {}),
            "irHash": "sha256:" + hashlib.sha256(
                json.dumps(block.get("ir"), ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        pack_blocks.append(packed)
    source_artifact = source_node_data.get("sourceArtifact") if isinstance(source_node_data.get("sourceArtifact"), dict) else None
    revision_basis = ({"sourceArtifact": source_artifact, "tokens": source_node_data.get("tokens") or {}}
                      if source_artifact else {"blocks": pack_blocks, "tokens": source_node_data.get("tokens") or {}})
    return {
        "schemaVersion": "source-pack/1.0",
        "sourceNodeId": str(source_node_id),
        "sourceRevisionHash": _content_hash(revision_basis),
        "source": {
            "kind": "url" if (source_node_data.get("mode") or "url") == "url" else "screenshot",
            "url": source_node_data.get("url"),
            "capturedAt": source_node_data.get("capturedAt") or "",
            "parserVersion": source_node_data.get("parserVersion") or SOURCE_COMPILER_DEFAULT,
        },
        "blocks": pack_blocks,
        "sourceArtifact": copy.deepcopy(source_artifact),
        "tokens": source_node_data.get("tokens") or {},
        "viewports": ["desktop", "tablet", "mobile"],
    }


def _foundations_from_tokens(tokens: dict, viewports: list, blocks: list | None = None) -> dict:
    """Build foundations from measured Source values; never invent a scale."""
    dna = normalize_dna(tokens)
    px = _dna_px(dna)
    brand = [v for v in (tokens or {}).get("brandColors", []) if _hex(v)] if isinstance(tokens, dict) else []
    measured = _measured_foundation_values(blocks or [])
    measured_colors = [value for value in measured["colors"] if value not in brand]
    font_sizes = measured["fontSizes"]
    scale_names = ("display", "h2", "h3", "body", "caption")
    type_scale = {name: value for name, value in zip(scale_names, font_sizes[:5])}
    if len(font_sizes) > len(scale_names):
        type_scale.update({f"size{index + 1}": value for index, value in enumerate(font_sizes[5:], start=5)})
    token_families = [dna["font"]["display"]["family"], dna["font"]["body"]["family"]]
    families = list(dict.fromkeys(measured["families"] + token_families))[:8]
    weights = measured["weights"] or sorted({dna["font"]["display"]["weight"], dna["font"]["body"]["weight"]})
    radii = measured["radii"] or sorted({px["card"], px["button"], px["input"]})
    spacing = {f"space{index + 1}": value for index, value in enumerate(measured["spacings"])}
    raw_spacing = tokens.get("spacing") if isinstance(tokens, dict) and isinstance(tokens.get("spacing"), dict) else {}
    if raw_spacing.get("section") is not None:
        spacing["section"] = _SECTION_PX[dna["spacing"]["section"]]
    raw_breakpoints = measured["breakpoints"]
    if not raw_breakpoints and isinstance(viewports, dict):
        raw_breakpoints = {
            str(name): int(config.get("width"))
            for name, config in viewports.items()
            if isinstance(config, dict) and isinstance(config.get("width"), (int, float))
        }

    foundations = {
        "mode": dna["mode"],
        "colors": {"primitives": {
                       **{f"brand{i + 1}": _hex(v) for i, v in enumerate(brand[:6]) if _hex(v)},
                       **{f"measured{i + 1}": value for i, value in enumerate(measured_colors[:16])},
                   },
                   "semantic": dict(dna["color"])},
        "typography": {
            "families": families,
            "scale": type_scale,
            "weights": weights,
            "display": dict(dna["font"]["display"]),
            "body": dict(dna["font"]["body"]),
        },
        "spacing": spacing,
        "radii": radii,
        "radius": dict(px),
        "shadows": measured["shadows"],
        "breakpoints": raw_breakpoints,
        "containers": ({"content": max(measured["containers"])} if measured["containers"] else {}),
        "measurement": {
            "basis": "source-ir",
            "fontSizeCount": len(font_sizes),
            "spacingCount": len(measured["spacings"]),
            "radiusCount": len(measured["radii"]),
        },
    }
    if isinstance(tokens, dict) and tokens.get("iconStyle"):
        foundations["iconStyle"] = tokens["iconStyle"]
    if isinstance(tokens, dict) and tokens.get("imageDirection"):
        foundations["imageDirection"] = tokens["imageDirection"]
    return foundations


def _mock_field(field: dict, content: dict) -> dict:
    """Поле мок-схемы: формат → enum из контента референса, где он есть."""
    fmt = str(field.get("format") or "sentence")
    enum_map = {
        "cta": content.get("cta"), "nav": content.get("nav"), "badge": content.get("badge"),
        "category": content.get("category"), "heading": content.get("heading"),
        "title": content.get("title"), "price": content.get("price"),
        "question": content.get("question"), "answer": content.get("answer"),
    }
    values = enum_map.get(fmt)
    out = {"name": field["name"], "format": fmt, "type": "string"}
    if values and field.get("enum", True):
        out["enum"] = list(values[:6])
    return out


def _mock_data_for(components: dict, content: dict, locale: str) -> dict:
    schemas: dict[str, dict] = {}
    fixtures: dict[str, dict] = {}
    for key, comp in components.items():
        schema_id = f"{key}-data"
        fields = [_mock_field(f, content) for f in (comp.get("_mockFields") or [])]
        if not fields:
            for field_name, field in (comp.get("propsSchema") or {}).items():
                if not isinstance(field, dict):
                    continue
                field_type = str(field.get("type") or "string")
                fields.append({
                    "name": str(field_name),
                    "format": "url" if field_type == "iri" else "sentence",
                    "type": "string",
                })
        if not fields:
            fields = [{"name": "text", "format": "sentence", "type": "string"}]
        schema = {"id": schema_id, "locale": locale, "fields": fields}
        schemas[schema_id] = schema
        for profile, fixture in mock_mod.default_profiles(schema, locale).items():
            fixtures[fixture["id"]] = fixture
        primary = fields[0]["name"] if fields else "text"
        comp["mockBindings"] = [{"schemaId": schema_id, "field": primary}]
    return {"schemas": schemas, "fixtures": fixtures}


def _props_from_node(node: dict) -> dict:
    props: dict[str, dict] = {}
    text_nodes = [item for item in _walk_nodes(node) if str(item.get("text") or "").strip()]
    media_nodes = [item for item in _walk_nodes(node) if item.get("type") == "image"]
    if text_nodes:
        props["text"] = {
            "type": "string", "required": True,
            "description": f"captured source text ({len(text_nodes)} fragments)",
        }
    for index, _ in enumerate(media_nodes, start=1):
        props[f"media{index}"] = {"type": "iri", "required": False, "description": "captured source media"}
    if str(node.get("type") or "").lower() == "button":
        props["action"] = {"type": "string", "required": False, "description": "button action"}
    return props


def _source_keys(node: dict) -> list[str]:
    return list(dict.fromkeys(
        str(item.get("sourceKey")) for item in _walk_nodes(node)
        if isinstance(item.get("sourceKey"), str) and item.get("sourceKey")
    ))


def _clean_key(value: Any, fallback: str) -> str:
    key = re.sub(r"[^a-z0-9-]+", "-", str(value or "").lower()).strip("-")
    return key[:64] or fallback


def _block_evidence_key(block: dict) -> str:
    ir_hash = str(block.get("irHash") or hashlib.sha256(
        json.dumps(block.get("ir") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest())
    identity = f"{block.get('name') or ''}|{block.get('selector') or ''}|{ir_hash}"
    return "evidence-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def _reference_assets(blocks: list) -> dict:
    assets: dict[str, dict] = {}
    for block in blocks or []:
        if not isinstance(block, dict) or not isinstance(block.get("ir"), dict):
            continue
        previews = copy.deepcopy(block.get("previews") or {})
        if block.get("preview") and "desktop" not in previews:
            previews["desktop"] = block.get("preview")
        assets[_block_evidence_key(block)] = {
            "sourceBlock": str(block.get("name") or "block"),
            "selector": str(block.get("selector") or ""),
            "referencePreviews": previews,
            "blockSizes": copy.deepcopy(block.get("sizes") or {}),
        }
    return assets


def _component_fidelity(block: dict, source_key: str = "", node: dict | None = None,
                        family: str = "") -> dict:
    block_report = block.get("fidelityReport") if isinstance(block.get("fidelityReport"), dict) else {}
    component_reports = block_report.get("components") if isinstance(block_report.get("components"), dict) else {}
    component_report = component_reports.get(source_key) if source_key and isinstance(component_reports.get(source_key), dict) else None
    report = component_report or block_report
    report_viewports = report.get("viewports") if isinstance(report.get("viewports"), dict) else {}
    legacy_similarity = block.get("fidelity") if isinstance(block.get("fidelity"), dict) else {}
    legacy_p95 = block.get("p95LayoutError") if isinstance(block.get("p95LayoutError"), dict) else {}
    legacy_paint = block.get("paintCoverage") if isinstance(block.get("paintCoverage"), dict) else {}
    dropped = block.get("droppedByViewport") if isinstance(block.get("droppedByViewport"), dict) else {}
    extras = block.get("extrasByViewport") if isinstance(block.get("extrasByViewport"), dict) else {}
    expected_viewports = (list(report_viewports) if component_report else list(dict.fromkeys(
        list((block.get("previews") or {}).keys()) + list((block.get("sizes") or {}).keys())
    ))) or ["desktop", "tablet", "mobile"]
    names = list(dict.fromkeys(
        expected_viewports + list(report_viewports) + list(legacy_similarity) + list(legacy_p95) + list(legacy_paint)
    ))
    viewports: dict[str, dict] = {}
    for name in names:
        raw = report_viewports.get(name) if isinstance(report_viewports.get(name), dict) else {}
        losses = [
            item for item in list(dropped.get(name) or []) + list(extras.get(name) or [])
            if isinstance(item, dict) and item.get("visual") and not item.get("explained")
        ]
        viewports[str(name)] = {
            "pixelSimilarity": raw.get("pixel_similarity", legacy_similarity.get(name)),
            "paintCoverage": raw.get("paint_coverage", legacy_paint.get(name)),
            "bboxP95": raw.get("bbox_p95", legacy_p95.get(name)),
            "originError": raw.get("grid_origin_error"),
            "unexplainedLosses": raw.get("unexplained_losses", len(losses)),
            "sizeMatch": raw.get("size_match"),
            "sourceGatePassed": ((raw.get("gate") or {}).get("passed")
                                 if isinstance(raw.get("gate"), dict) else None),
            "sourceGateReasons": list((raw.get("gate") or {}).get("reasons") or [])
                                 if isinstance(raw.get("gate"), dict) else [],
        }
    node_frame = (node or {}).get("frame") if isinstance((node or {}).get("frame"), dict) else {}
    node_role = str(_node_meta(node or {}).get("componentRole") or (node or {}).get("type") or "").lower()
    compact_control = (
        (family == "button" or node_role in {"button", "a", "link", "radio", "checkbox"})
        and isinstance(node_frame.get("width"), (int, float))
        and isinstance(node_frame.get("height"), (int, float))
        and float(node_frame["width"]) <= 128
        and float(node_frame["height"]) <= 64
    )
    fidelity = {
        "basis": ("component-source-fidelity-harness" if component_report
                  else "source-fidelity-harness" if report_viewports else "legacy-source-metrics"),
        "viewports": viewports,
        "requiredViewports": expected_viewports,
        "containsRaster": any(
            str(item.get("type") or "").lower() == "image"
            or bool((_node_meta(item).get("objectSha256") or _node_meta(item).get("captureVersion")))
            for item in _walk_nodes(node or {})
        ),
        "compactControl": compact_control,
    }
    fidelity["status"] = component_fidelity_status(fidelity)["status"]
    fidelity["reasons"] = component_fidelity_status(fidelity)["reasons"]
    return fidelity


def _canonical_spec_map(dna: dict, content: dict) -> dict[str, dict]:
    return {spec["key"]: spec for spec in _build_library(dna, content)}


_SEMANTIC_COMPONENTS = {
    "button": ("Button", "actions", "Observed button and link treatments"),
    "search-field": ("Search field", "forms", "Observed composite search control"),
    "header-actions": ("Header actions", "navigation", "Observed header action group"),
    "hero-slide": ("Hero slide", "content", "Observed marketplace carousel slide"),
    "category-tile": ("Category tile", "navigation", "Observed category navigation tile"),
    "listing-section-header": ("Listing section header", "navigation", "Observed listing heading and filters"),
    "filter-bar": ("Filter bar", "actions", "Observed listing filter group"),
    "service-card": ("Service card", "surfaces", "Observed service or product listing card"),
    "trust-card": ("Trust card", "surfaces", "Observed trust and safety card"),
    "article-section": ("Article section", "patterns", "Observed editorial section composition"),
    "article-card": ("Article card", "surfaces", "Observed editorial card"),
    "section-header": ("Section header", "content", "Observed section heading"),
    "process-step": ("Process step", "content", "Observed numbered process step"),
    "text-link": ("Text link", "actions", "Observed inline navigation link"),
    "accordion-item": ("Accordion item", "disclosure", "Observed FAQ disclosure row"),
    "support-card": ("Support card", "surfaces", "Observed support contact card"),
    "footer-navigation": ("Footer navigation", "navigation", "Observed footer navigation group"),
    "mobile-navigation-item": ("Mobile navigation item", "navigation", "Observed mobile navigation action"),
    "navigation-group": ("Navigation group", "navigation", "Observed navigation composition"),
    "content-card": ("Content card", "surfaces", "Observed content surface"),
    "form-group": ("Form group", "forms", "Observed multi-field form composition"),
    "form-field": ("Form field", "forms", "Observed single input control"),
    "list-item": ("List item", "content", "Observed repeated list row"),
    "nested-surface": ("Nested surface", "surfaces", "Observed surface inside another component"),
}


def _node_meta(node: dict) -> dict:
    return node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}


def _node_text(node: dict) -> str:
    values: list[str] = []
    for item in _walk_nodes(node):
        text = " ".join(str(item.get("text") or "").split())
        if text:
            values.append(text)
    return " | ".join(values)


def _node_composition(node: dict) -> dict:
    """Из чего состоит компонент: типы и количество потомков, наличие текста.

    Основа классификации вместо имён CSS-классов: состав содержимого одинаков
    на любом сайте, а `card`/`item`/`tile` в классах — соглашение конкретной
    команды (и вовсе отсутствует при Tailwind, CSS-modules и хешах).
    """
    types: dict[str, int] = {}
    depth = 0

    def walk(current: dict, level: int) -> None:
        nonlocal depth
        depth = max(depth, level)
        for child in current.get("children") or []:
            if not isinstance(child, dict):
                continue
            node_type = str(child.get("type") or "").lower()
            types[node_type] = types.get(node_type, 0) + 1
            walk(child, level + 1)

    walk(node, 0)
    return {
        "types": types,
        "depth": depth,
        "total": sum(types.values()),
        "text": _node_text(node).strip(),
        "media": types.get("image", 0) + types.get("icon", 0) + types.get("avatar", 0),
        "headings": types.get("heading", 0),
        "actions": types.get("button", 0),
        "fields": types.get("input", 0),
    }


def _semantic_component_key(node: dict, block: dict, ancestor_key: str = "") -> str | None:
    """Map measured Source semantics to a small, stable UI-kit taxonomy.

    Классификация идёт по признакам, а не по литералам конкретного сайта:
    ARIA-роль и тег (переносимая семантика HTML), состав содержимого и факт
    повторяемости. Прежняя версия сравнивала componentLabel с именами классов
    одного маркетплейса, поэтому на любом другом сайте всё падало в
    generic-хвост и схлопывалось в один `content-card`.
    """
    meta = _node_meta(node)
    role = str(meta.get("componentRole") or "").lower()
    node_type = str(node.get("type") or "").lower()
    kind = str(block.get("kind") or block.get("name") or "").lower()
    repeated = bool(meta.get("repeatGroup"))
    composition = _node_composition(node)

    # Интерактивные примитивы — по роли/типу, они однозначны.
    if node_type == "button" or role in ("button", "radio", "action", "menuitem", "tab"):
        return "button"
    if role in ("details", "disclosure") or node_type == "details":
        return "accordion-item"
    if role == "form" or composition["fields"] >= 1 and composition["actions"] >= 1:
        return "search-field" if composition["fields"] == 1 else "form-group"
    if node_type == "input" or role in ("textbox", "searchbox", "combobox"):
        return "form-field"

    # Навигация: явная роль либо плотная группа ссылок без длинного текста.
    if role in ("nav", "navigation", "menu", "menubar", "toolbar", "tablist"):
        return "footer-navigation" if kind == "footer" else "navigation-group"
    if role == "a":
        if repeated and composition["media"]:
            return "category-tile"
        return "mobile-navigation-item" if kind == "navigation" else "text-link"

    # Заголовок секции: заголовочная роль или блок из заголовка и короткого текста.
    if role in ("header", "heading") or node_type == "heading":
        return "listing-section-header" if kind.startswith("product-grid") else "section-header"
    if composition["headings"] and composition["total"] <= 3 and not composition["media"]:
        return "section-header"

    # Повторяющаяся единица. Вид блока (kind) теперь выводится структурно
    # (scraper._structural_role), поэтому опираться на него безопасно: это
    # свойство раскладки страницы, а не имя класса конкретного сайта.
    if repeated or role in ("li", "listitem", "article", "option"):
        by_kind = {
            "product-grid": "service-card",
            "services-grid": "service-card",
            "journal": "article-card",
            "categories": "category-tile",
            "faq": "accordion-item",
            "trust": "trust-card",
            "testimonials": "trust-card",
            "how-it-works": "process-step",
            "gallery": "category-tile",
        }
        if kind in by_kind:
            return by_kind[kind]
        if composition["media"] and composition["headings"]:
            return "service-card"
        if composition["media"]:
            return "category-tile"
        if composition["headings"] or len(composition["text"]) >= 24:
            return "process-step" if kind == "section" else "list-item"
        return "list-item"

    # Поверхность-контейнер: раньше вложенные возвращали None и молча исчезали
    # из UI Kit. Теперь вложенная поверхность — самостоятельное семейство.
    if role in ("card", "panel", "section", "region", "group", "widget", "module", "component", "complementary"):
        if kind in ("panel", "carousel") and composition["media"]:
            return "hero-slide"
        if kind == "trust":
            return "trust-card"
        if kind == "footer":
            return "support-card"
        if composition["media"] and composition["headings"]:
            return "content-card"
        return "nested-surface" if ancestor_key else "content-card"
    return None


def _semantic_spec(family: str, specs: dict[str, dict]) -> dict:
    aliases = {
        "service-card": "product-card", "accordion-item": "accordion", "text-link": "button",
        "filter-bar": "button", "header-actions": "navbar", "footer-navigation": "footer",
        "navigation-group": "navbar", "mobile-navigation-item": "navbar",
        "category-tile": "category-tile", "article-card": "article-card",
        "search-field": "search", "support-card": "card", "trust-card": "card",
        "content-card": "card", "process-step": "steps", "section-header": "heading",
        "listing-section-header": "heading", "hero-slide": "carousel",
    }
    base = copy.deepcopy(specs.get(aliases.get(family, family)) or {})
    name, category, description = _SEMANTIC_COMPONENTS.get(
        family, (family.replace("-", " ").title(), "content", "Captured Source component"))
    base.update({"key": family, "name": name, "category": category, "description": description})
    base.setdefault("mockFields", [])
    base.setdefault("states", _GEN_STATES)
    return base


_VISUAL_IGNORED_KEYS = {
    "id", "sourceKey", "sourceMeta", "text", "src", "alt", "href", "url", "semantic",
    "props", "styleBindings", "__path", "preview", "sourcePreview", "contentHash",
}


def _visual_structure(value: Any, *, family: str, in_button: bool = False) -> Any:
    if isinstance(value, list):
        return [_visual_structure(item, family=family, in_button=in_button) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    button_scope = in_button or family == "button"
    for key in sorted(value):
        if key in _VISUAL_IGNORED_KEYS:
            continue
        child = value[key]
        if key == "frame" and isinstance(child, dict):
            frame = {k: v for k, v in child.items() if k not in ("x", "y")}
            if button_scope:
                frame = {k: v for k, v in frame.items() if k not in ("width", "minWidth", "maxWidth")}
            out[key] = _visual_structure(frame, family=family, in_button=button_scope)
            continue
        out[key] = _visual_structure(child, family=family, in_button=button_scope)
    return out


def _rounded_visual(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 1)
    if isinstance(value, list):
        return [_rounded_visual(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded_visual(child) for key, child in value.items()}
    return value


def _visual_signature(node: dict, family: str, variant_key: str = "") -> str:
    """Отпечаток внешнего вида компонента: стиль, геометрия и структура.

    Раньше 16 из 20 семейств хэшировали только `family|variantKey`, то есть
    визуал вообще не участвовал: два по-разному оформленных набора карточек
    с одинаковым variantKey схлопывались в один мастер, и второй дизайн
    терялся как простой инкремент observedCount. Теперь стиль хэшируется для
    всех семейств.
    """
    style = copy.deepcopy(node.get("style") or {}) if isinstance(node.get("style"), dict) else {}
    frame = copy.deepcopy(node.get("frame") or {}) if isinstance(node.get("frame"), dict) else {}
    for key in ("x", "y", "absolute"):
        frame.pop(key, None)
    if family in ("button", "hero-slide"):
        frame.pop("width", None)

    responsive: dict[str, dict] = {}
    for viewport_name, override in (node.get("responsive") or {}).items():
        if not isinstance(override, dict):
            continue
        viewport_frame = copy.deepcopy(override.get("frame") or {}) if isinstance(override.get("frame"), dict) else {}
        for key in ("x", "y", "absolute"):
            viewport_frame.pop(key, None)
        if family in ("button", "hero-slide"):
            viewport_frame.pop("width", None)
        responsive[str(viewport_name)] = {
            "visible": override.get("visible", True),
            "frame": viewport_frame,
            "style": copy.deepcopy(override.get("style") or {}),
        }

    payload: dict[str, Any] = {
        "type": node.get("type"),
        "variant": variant_key,
        "style": style,
        "frame": frame,
        "responsive": responsive,
    }
    # Структурный скелет — для всех семейств: карточка «картинка + заголовок»
    # и карточка «заголовок + список» визуально разные компоненты, даже когда
    # их стилевые токены совпадают.
    def skeleton(value: dict, depth: int = 0) -> Any:
        if not isinstance(value, dict) or depth > 3:
            return None
        return [
            str(value.get("type") or ""),
            [skeleton(child, depth + 1) for child in (value.get("children") or [])[:8]],
        ]
    payload["structure"] = skeleton(node)
    payload = _rounded_visual(payload)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _color_luminance(value: str) -> float | None:
    color = _hex(value)
    if not color:
        return None
    rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _observed_style(node: dict) -> dict:
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    return {
        key: copy.deepcopy(value) for key, value in {
            "background": style.get("background"), "color": style.get("color"),
            "borderColor": style.get("borderColor"), "borderWidth": style.get("borderWidth"),
            "borderRadius": style.get("borderRadius"), "shadow": style.get("boxShadow") or style.get("shadow"),
            "width": frame.get("width"), "height": frame.get("height"),
            "padding": frame.get("padding"), "gap": frame.get("gap"),
        }.items() if value not in (None, "")
    }


def _variant_identity(node: dict, family: str, dna: dict, scale: dict | None = None) -> tuple[str, str]:
    """Вариант компонента. Пороги — доли ширины страницы, а не абсолютные
    пиксели: прежние 90/600/300 px были замерами одного макета на 1440 и на
    сайте с другим масштабом переворачивали классификацию."""
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    text = _node_text(node)
    width = frame.get("width") if isinstance(frame.get("width"), (int, float)) else None
    height = frame.get("height") if isinstance(frame.get("height"), (int, float)) else None
    page_width = float((scale or {}).get("pageWidth") or 1440) or 1440
    narrow = page_width * 0.0625   # ≈90px на 1440
    wide = page_width * 0.4167     # ≈600px на 1440

    # Процентная нотация универсальна (не привязана к языку): карточка со
    # скидочным токеном — отдельный промо-вариант семейства.
    if family in ("service-card", "article-card", "trust-card", "content-card") and "%" in text:
        return "sale", "Sale"
    if family in ("service-card", "content-card"):
        return "standard", "Standard"
    if family == "category-tile":
        if str(node.get("type") or "").lower() == "button":
            return "more", "More"
        return ("compact", "Compact") if width is not None and width <= narrow else ("standard", "Standard")
    if family == "article-card":
        return ("featured", "Featured") if width is not None and width >= wide else ("compact", "Compact")
    if family == "accordion-item":
        # Раскрытая строка выше своей же типовой высоты — сравниваем с медианой
        # семейства, а не с константой 90px.
        typical = float((scale or {}).get("accordionMedian") or 0) or 90.0
        return ("open", "Open") if height is not None and height > typical * 1.4 else ("closed", "Closed")
    if family == "hero-slide":
        background = _hex(style.get("background"))
        if background:
            return f"background-{background[1:]}", f"Background {background.upper()}"
    if family == "mobile-navigation-item":
        return ("primary", "Primary") if width is not None and width < narrow * 0.78 else ("standard", "Standard")

    if family == "button":
        background = _hex(style.get("background"))
        color = _hex(style.get("color"))
        border = _hex(style.get("borderColor"))
        border_width = float(style.get("borderWidth") or 0)
        primary = _hex((dna.get("color") or {}).get("primary"))
        accent = _hex((dna.get("color") or {}).get("accent"))
        radius = float(style.get("borderRadius") or 0)
        circular = bool(width and height and abs(width - height) <= 2 and radius >= height / 2 - 1)
        pill = bool(height and radius >= height / 2 - 1 and not circular)
        icon_only = circular or not text.strip()
        if background == primary:
            tone = "brand"
        elif background == accent:
            tone = "accent"
        elif background:
            luminance = _color_luminance(background)
            if border_width > 0 and background == "#ffffff":
                tone = "outline-brand" if color == primary or border == primary else "outline-neutral"
            elif luminance is not None and luminance > .8:
                tone = "soft"
            elif luminance is not None and luminance < .25:
                tone = "inverse"
            else:
                tone = f"color-{background[1:]}"
        elif border_width > 0:
            tone = "outline-brand" if color == primary or border == primary else "outline-neutral"
        else:
            tone = "ghost"
        shape = " icon" if icon_only else " pill" if pill else " compact" if height and height <= 32 else ""
        key = _clean_key(tone + shape.replace(" ", "-"), "observed")
        return key, (tone + shape).replace("-", " ").title()

    if width is not None and height is not None:
        if width <= narrow * 1.11 or height <= 48:
            return "compact", "Compact"
        if width >= wide or height >= 300:
            return "expanded", "Expanded"
    return "standard", "Standard"


def _default_variant_rank(candidate: dict) -> tuple[int, int]:
    family = candidate["family"]
    key = candidate["variantKey"]
    if family == "button":
        order = ("brand", "accent", "outline-brand", "outline-neutral", "soft", "ghost", "inverse")
        return next(((index, 0) for index, value in enumerate(order) if key == value), (50, 0))
    preferred = {
        "service-card": "standard", "category-tile": "standard", "article-card": "featured",
        "accordion-item": "closed", "mobile-navigation-item": "standard",
    }.get(family)
    return (0 if preferred and key == preferred else 1, 0)


def _canonical_key(node: dict, block: dict) -> str:
    return _semantic_component_key(node, block) or "component"


def _inferred_component_keys(blocks: list) -> set[str]:
    keys: set[str] = set()

    def visit(node: dict, block: dict, depth: int = 0) -> None:
        if not isinstance(node, dict):
            return
        meta = node.get("sourceMeta") if isinstance(node.get("sourceMeta"), dict) else {}
        if meta.get("componentBoundary"):
            return
        node_type = str(node.get("type") or "").lower()
        candidates = _TYPE_TO_KEY.get(node_type, ())
        if depth == 0:
            candidates = _KIND_TO_KEY.get(str(block.get("kind") or "").lower(), ()) or candidates
        for key in candidates:
            if key not in ("text", "heading"):
                keys.add(str(key))
        for child in node.get("children") or []:
            visit(child, block, depth + 1)

    for block in blocks or []:
        ir = block.get("ir") if isinstance(block, dict) else None
        if not isinstance(ir, dict):
            continue
        # A block with explicit captured boundaries is already explained by
        # observed components. Adding canonical guesses beside them creates the
        # duplicate, generic Card/Button/Navbar list the UI kit must avoid.
        if any(_node_meta(node).get("componentBoundary") for node in _walk_nodes(ir.get("tree") or [])):
            continue
        for root in ir.get("tree") or []:
            visit(root, block)
    return keys


def _components_from_blocks(blocks: list, source_revision_hash: str, dna: dict,
                            content: dict) -> tuple[dict, dict, dict]:
    """Extract exact Source masters into semantic families without duplicates.

    Content repetitions become occurrences, not variants. A variant is created
    only when the measured visual structure/style differs. Every retained
    variant still points to an exact Source subtree and evidence crop.
    """
    specs = _canonical_spec_map(dna, content)
    # Масштаб захвата: пороги вариантов считаются в долях ширины страницы,
    # чтобы сайт с другой шириной макета не переклассифицировался.
    page_widths = [
        size.get("width") for block in blocks or []
        if isinstance(block, dict) and isinstance(size := block.get("size"), dict)
        and isinstance(size.get("width"), (int, float)) and size.get("width")
    ]
    scale = {"pageWidth": max(page_widths) if page_widths else 1440}
    components: dict[str, dict] = {}
    suggestions: dict[str, dict] = {}
    candidates: dict[str, list[dict]] = {}
    total_boundaries = 0
    included_boundaries = 0
    suppressed_boundaries = 0

    for block in blocks or []:
        ir = block.get("ir") if isinstance(block, dict) else None
        if not isinstance(ir, dict):
            continue
        block_name = str(block.get("name") or "block")
        block_tokens = ir.get("tokens") if isinstance(ir.get("tokens"), dict) else _tokens_for_ir(dna)
        evidence_key = _block_evidence_key(block)

        def visit(node: dict, ancestor_key: str = "", ancestors: tuple[dict, ...] = ()) -> None:
            nonlocal total_boundaries, included_boundaries, suppressed_boundaries
            if not isinstance(node, dict):
                return
            meta = _node_meta(node)
            next_ancestor = ancestor_key
            if meta.get("componentBoundary"):
                total_boundaries += 1
                family = _semantic_component_key(node, block, ancestor_key)
                if family:
                    included_boundaries += 1
                    next_ancestor = family
                    repeat_group = str(meta.get("repeatGroup") or "")
                    master = {
                        "version": ir.get("version") or "1.1",
                        "tokens": copy.deepcopy(block_tokens),
                        "tree": [copy.deepcopy(node)],
                    }
                    # meta.fontFaces — единственный источник @font-face для
                    # рендерера. Без него КАЖДОЕ превью компонента рисовалось
                    # системным шрифтом вместо шрифта сайта: мастер вырезается
                    # из блока, а meta оставалась у блока.
                    block_meta = ir.get("meta") if isinstance(ir.get("meta"), dict) else {}
                    if block_meta.get("fontFaces"):
                        master["meta"] = {"fontFaces": copy.deepcopy(block_meta["fontFaces"])}
                    # Корневой маркер responsive.viewports: без него рендерер не
                    # применяет per-viewport override'ы узлов (в т.ч. visible:false
                    # для клонов других вьюпортов) — мастер рисовал desktop и
                    # mobile-версии текста друг поверх друга («текст дважды»).
                    block_responsive = ir.get("responsive") if isinstance(ir.get("responsive"), dict) else {}
                    if isinstance(block_responsive.get("viewports"), dict) and block_responsive["viewports"]:
                        master["responsive"] = {"viewports": copy.deepcopy(block_responsive["viewports"])}
                    bounds_by_viewport = {
                        viewport_name: frame
                        for viewport_name in ("desktop", "tablet", "mobile")
                        if (frame := _absolute_component_frame(node, ancestors, viewport_name)) is not None
                    }
                    base_bounds = copy.deepcopy(
                        bounds_by_viewport.get("desktop")
                        or _absolute_component_frame(node, ancestors, "desktop")
                        or node.get("frame") or {}
                    )
                    source_ref = {
                        "sourceBlock": block_name,
                        "selector": str(block.get("selector") or ""),
                        "sourceKey": str(node.get("sourceKey") or ""),
                        "sourceKeys": _source_keys(node),
                        "sourceRevisionHash": source_revision_hash,
                        "masterHash": _content_hash(master),
                        "repeatGroup": repeat_group,
                        "bounds": base_bounds,
                        "boundsByViewport": bounds_by_viewport,
                        "evidenceKey": evidence_key,
                    }
                    variant_key, variant_label = _variant_identity(node, family, dna, scale)
                    fidelity = _component_fidelity(block, source_ref["sourceKey"], node, family)
                    candidates.setdefault(family, []).append({
                        "family": family,
                        "node": node,
                        "meta": meta,
                        "master": master,
                        "sourceRef": source_ref,
                        "fidelity": copy.deepcopy(fidelity),
                        "signature": _visual_signature(node, family, variant_key),
                        "variantKey": variant_key,
                        "variantLabel": variant_label,
                        "observedStyle": _observed_style(node),
                        "sourceLabel": str(meta.get("componentLabel") or "").strip(),
                        "blockName": block_name,
                    })
                else:
                    suppressed_boundaries += 1
            for child in node.get("children") or []:
                visit(child, next_ancestor, (*ancestors, node))

        for root in ir.get("tree") or []:
            visit(root)

    def unique_variant_key(base: str, existing: set[str], candidate: dict) -> tuple[str, str]:
        label = candidate["variantLabel"]
        if base not in existing:
            return base, label
        style = candidate.get("observedStyle") or {}
        suffixes = []
        if style.get("height") is not None:
            suffixes.append(f"{style['height']}px")
        if style.get("background"):
            suffixes.append(str(style["background"]).lstrip("#"))
        if style.get("borderRadius") is not None:
            suffixes.append(f"r{style['borderRadius']}")
        for suffix in suffixes:
            key = _clean_key(f"{base}-{suffix}", base)
            if key not in existing:
                return key, f"{label} · {suffix}"
        key = _clean_key(f"{base}-{candidate['signature'][:8]}", base)
        return key, f"{label} · observed {candidate['signature'][:6]}"

    def make_component(key: str, candidate: dict, spec: dict, *, status: str) -> dict:
        node = candidate["node"]
        meta = candidate["meta"]
        source_ref = copy.deepcopy(candidate["sourceRef"])
        return {
            "componentKey": key,
            "canonicalRole": candidate["family"],
            "name": str(spec.get("name") or key.replace("-", " ").title()),
            "sourceLabel": candidate["sourceLabel"],
            "category": str(spec.get("category") or "content"),
            "description": str(spec.get("description") or f"Exact Source master from {candidate['blockName']}"),
            "origin": "observed",
            "status": status,
            "confidence": 1.0,
            "confirmed": True,
            "masterIr": copy.deepcopy(candidate["master"]),
            "propsSchema": _props_from_node(node),
            "slots": [],
            "variants": {
                "default": {
                    "label": candidate["variantLabel"], "semanticKey": candidate["variantKey"],
                    "origin": "observed", "confirmed": True, "masterRef": "self", "diff": {},
                    "observedStyle": copy.deepcopy(candidate["observedStyle"]), "observedCount": 1,
                }
            },
            "states": {
                state_name: {
                    "label": state_name, "origin": "generated", "confirmed": False,
                    "description": f"State {state_name} was not observed in Source",
                }
                for state_name in (spec.get("states") or _GEN_STATES)
            },
            "dependencies": [],
            "tokenBindings": {},
            "mockBindings": [],
            "accessibility": {
                "role": str(meta.get("componentRole") or node.get("role") or node.get("type") or "group"),
                "focusable": str(node.get("type") or "") in ("button", "input"),
            },
            "sourceRef": source_ref,
            "fidelity": copy.deepcopy(candidate["fidelity"]),
            "provenance": {
                "sourceKeys": list(source_ref["sourceKeys"]),
                "sourceBlocks": [candidate["blockName"]],
                "sourceBlock": candidate["blockName"],
                "repeatGroup": bool(source_ref.get("repeatGroup")),
                "sourceRevisionHash": source_revision_hash,
                "extraction": "exact-source-subtree-semantic-family",
                "occurrenceCount": 1,
            },
            "_mockFields": copy.deepcopy(spec.get("mockFields") or []),
        }

    review_keys: list[str] = []
    deduplicated_boundaries = 0
    visual_variant_count = 0
    verified_boundaries = 0

    for family, family_candidates in candidates.items():
        spec = _semantic_spec(family, specs)
        passed = [candidate for candidate in family_candidates
                  if component_fidelity_status(candidate["fidelity"])["passed"]]
        failed = [candidate for candidate in family_candidates
                  if not component_fidelity_status(candidate["fidelity"])["passed"]]
        verified_boundaries += len(passed)

        visual_groups: dict[str, dict] = {}
        for candidate in passed:
            group = visual_groups.setdefault(candidate["signature"], {
                "candidate": candidate, "occurrences": [],
            })
            group["occurrences"].append(candidate)
        deduplicated_boundaries += sum(max(0, len(group["occurrences"]) - 1)
                                       for group in visual_groups.values())

        if visual_groups:
            ordered = sorted(visual_groups.values(), key=lambda group: _default_variant_rank(group["candidate"]))
            default_group = ordered[0]
            default_candidate = default_group["candidate"]
            component = make_component(family, default_candidate, spec, status="verified")
            default_variant = component["variants"]["default"]
            default_variant["observedCount"] = len(default_group["occurrences"])
            used_variant_keys = {"default"}
            for group in ordered[1:]:
                candidate = group["candidate"]
                variant_key, variant_label = unique_variant_key(
                    candidate["variantKey"], used_variant_keys, candidate)
                used_variant_keys.add(variant_key)
                component["variants"][variant_key] = {
                    "label": variant_label,
                    "semanticKey": candidate["variantKey"],
                    "origin": "observed",
                    "confirmed": True,
                    "masterIr": copy.deepcopy(candidate["master"]),
                    "sourceRef": copy.deepcopy(candidate["sourceRef"]),
                    "fidelity": copy.deepcopy(candidate["fidelity"]),
                    "diff": {},
                    "observedStyle": copy.deepcopy(candidate["observedStyle"]),
                    "observedCount": len(group["occurrences"]),
                }
            all_occurrences = [item for group in ordered for item in group["occurrences"]]
            component["provenance"]["sourceKeys"] = list(dict.fromkeys(
                source_key for candidate in all_occurrences
                for source_key in candidate["sourceRef"]["sourceKeys"]
            ))
            component["provenance"]["sourceBlocks"] = list(dict.fromkeys(
                candidate["blockName"] for candidate in all_occurrences
            ))
            component["provenance"]["occurrenceCount"] = len(all_occurrences)
            component["provenance"]["visualVariantCount"] = len(ordered)
            component["provenance"]["unverifiedOccurrenceCount"] = sum(
                1 for candidate in failed if candidate["signature"] in visual_groups
            )
            components[family] = component
            visual_variant_count += len(ordered)

        # Fidelity failures remain exact, read-only review records. They never
        # enter the publishable family or become variants of a verified master.
        failed_groups: dict[str, dict] = {}
        for candidate in failed:
            group = failed_groups.setdefault(candidate["signature"], {
                "candidate": candidate, "occurrences": [],
            })
            group["occurrences"].append(candidate)
        deduplicated_boundaries += sum(max(0, len(group["occurrences"]) - 1)
                                       for group in failed_groups.values())
        for group in failed_groups.values():
            # The same measured visual already has verified evidence elsewhere;
            # retain the failed occurrence in provenance/quality, not as a
            # duplicate review card.
            if group["candidate"]["signature"] in visual_groups:
                continue
            candidate = group["candidate"]
            base = family if family not in components and family not in suggestions else f"{family}-review"
            review_key = base
            suffix = 2
            while review_key in components or review_key in suggestions:
                review_key = f"{base}-{suffix}"
                suffix += 1
            review = make_component(review_key, candidate, spec, status="needs-review")
            review["variants"]["default"]["observedCount"] = len(group["occurrences"])
            review["provenance"]["occurrenceCount"] = len(group["occurrences"])
            status_report = component_fidelity_status(candidate["fidelity"])
            review["review"] = {
                "kind": "fidelity",
                "reasons": list(status_report.get("reasons") or ["fidelity gate did not pass"]),
            }
            suggestions[review_key] = review
            review_keys.append(review_key)

    observed_roles = {
        str(comp.get("canonicalRole") or "")
        for comp in list(components.values()) + list(suggestions.values())
        if isinstance(comp, dict) and comp.get("origin") == "observed"
    }
    for key in sorted(_inferred_component_keys(blocks) - observed_roles):
        spec = specs.get(key)
        if not spec:
            continue
        template = {"version": "1.1", "tokens": _tokens_for_ir(dna), "tree": copy.deepcopy(spec["build"]())}
        suggestion_key = key
        suffix = 2
        while suggestion_key in components or suggestion_key in suggestions:
            suggestion_key = f"{key}-suggestion-{suffix}"
            suffix += 1
        suggestions[suggestion_key] = {
            "componentKey": suggestion_key,
            "canonicalRole": key,
            "name": spec["name"],
            "category": spec["category"],
            "description": "Suggested from Source semantics; not a captured visual master",
            "origin": "suggested",
            "status": "draft",
            "confidence": 0.45,
            "confirmed": False,
            "templateIr": template,
            "propsSchema": {
                field["name"]: {"type": "string", "required": index == 0,
                                 "description": f"suggested {field.get('format') or 'content'}"}
                for index, field in enumerate(spec.get("mockFields") or [])
            },
            "variants": {}, "states": {}, "dependencies": [], "mockBindings": [],
            "provenance": {"sourceRevisionHash": source_revision_hash, "extraction": "semantic-suggestion"},
        }

    stats = {
        "boundaryCount": total_boundaries,
        # Every boundary is accounted for as a family occurrence or an
        # intentionally absorbed nested primitive.
        "extractedBoundaryCount": total_boundaries,
        "includedBoundaryCount": included_boundaries,
        "suppressedNestedBoundaryCount": suppressed_boundaries,
        "deduplicatedBoundaryCount": deduplicated_boundaries,
        "visualVariantCount": visual_variant_count,
        "verifiedBoundaryCount": verified_boundaries,
        "observedComponentCount": len(components) + len(review_keys),
        "verifiedComponentCount": len(components),
        "reviewSuggestionCount": len(review_keys),
        "suggestionCount": len(suggestions),
    }
    return components, suggestions, stats


def build_draft(pack: dict, *, name: str | None = None, locale: str = "ru",
                include_generated_states: bool = True, create_mock: bool = True) -> dict:
    """Source Pack → draft Design System Document (§21, шаги 1-15)."""
    source_hash = str(pack.get("sourceRevisionHash") or "")
    doc = new_document(
        name or f"UI Kit · {pack.get('source', {}).get('url') or 'Source'}",
        source_refs=[{"sourceNodeId": pack.get("sourceNodeId"), "revisionHash": source_hash,
                      "url": pack.get("source", {}).get("url"), "capturedAt": pack.get("source", {}).get("capturedAt")}],
    )
    tokens = pack.get("tokens") or {}
    blocks = pack.get("_raw_blocks") or pack.get("blocks") or []
    doc["foundations"] = _foundations_from_tokens(tokens, pack.get("viewports") or [], blocks)
    dna = normalize_dna(tokens)
    content = harvest_reference_content(blocks)
    brand = _brand_from_url(pack.get("source", {}).get("url"))
    if brand:
        content["brand"] = brand
    doc["referenceContent"] = {k: content[k] for k in
                               ("brand", "nav", "cta", "heading", "title", "price", "category", "badge", "question", "answer")}
    components, suggestions, extraction = _components_from_blocks(blocks, source_hash, dna, content)
    if not include_generated_states:
        for comp in components.values():
            comp["states"] = {}
    doc["components"] = components
    # Fidelity is a publish gate, not a visibility gate. Keep every exact
    # observed master in the Design System catalog so Source import produces a
    # Figma-like component sheet even while some masters still need review.
    doc["reviewComponents"] = {
        key: copy.deepcopy(component)
        for key, component in suggestions.items()
        if isinstance(component, dict) and component.get("origin") == "observed"
    }
    doc["suggestions"] = suggestions
    from .organizer import deterministic_catalog
    doc["catalog"] = deterministic_catalog(doc)
    doc["extraction"] = extraction
    # Style Guide: семантическая карта токенов (в духе shadcn/ui) и характер
    # стиля из измеренных значений. AI-ревью (по запросу) допишет review-часть.
    from .style_review import ensure_style_guide
    ensure_style_guide(doc)
    doc["referenceAssets"] = _reference_assets(blocks)

    # Every catalog path consumes masterIr after this point. Run the pure,
    # deterministic polish pass during construction; the explicit /polish
    # endpoint can repeat the same lint in Chromium when source fonts/crops are
    # available. Keeping this pass model-free makes Source and JSON imports
    # reproducible and safe in offline desktop builds.
    from .polish import polish_document
    polish_pools = list((doc.get("components") or {}).values()) + list((doc.get("reviewComponents") or {}).values())
    has_captured_fonts = any(
        isinstance(component, dict)
        and isinstance(component.get("masterIr"), dict)
        and bool(((component["masterIr"].get("meta") or {}).get("fontFaces") or []))
        for component in polish_pools
    )
    polished, _polish_results = polish_document(doc, headless=has_captured_fonts)
    doc["components"] = polished.get("components") or {}
    doc["reviewComponents"] = polished.get("reviewComponents") or {}

    # Deterministic first pass: measurements and provenance are available even
    # when no interpretation model is connected. AI may later propose wording,
    # but it cannot replace these measured fields silently.
    identity, identity_tests, identity_measurements = extract_identity(
        blocks, doc["foundations"], patterns=doc.get("patterns") or {})
    doc["identity"] = identity
    doc["identityTests"] = identity_tests
    doc["identityMeasurements"] = identity_measurements

    if create_mock and components:
        doc["mockData"] = _mock_data_for(components, content, locale)
    for comp in components.values():
        comp.pop("_mockFields", None)

    origins = {"observed": 0, "suggested": 0, "generated": 0, "user": 0}
    for comp in list(components.values()) + list(suggestions.values()):
        origin = str(comp.get("origin") or "observed")
        origins[origin] = origins.get(origin, 0) + 1
    doc["provenance"] = {
        **origins,
        "observedCount": origins["observed"],
        "suggestedCount": origins["suggested"],
        "generatedCount": origins["generated"],
        "reviewCount": extraction.get("reviewSuggestionCount", 0),
    }
    confirmed_states = sum(
        1 for c in components.values()
        for s in (c.get("states") or {}).values()
        if isinstance(s, dict) and (s.get("origin") != "generated" or s.get("confirmed"))
    )
    total_states = sum(len(c.get("states") or {}) for c in components.values())
    coverage = round(100 * extraction["extractedBoundaryCount"] / max(1, extraction["boundaryCount"]))
    verified = sum(1 for comp in components.values() if comp.get("status") == "verified")
    fidelity_coverage = round(
        100 * extraction.get("verifiedBoundaryCount", verified)
        / max(1, extraction.get("includedBoundaryCount", extraction["observedComponentCount"]))
    )
    issues = [
        {"code": "master-needs-review", "componentKey": key,
         "message": "Observed master has no complete release-grade fidelity report"}
        for key, comp in suggestions.items() if comp.get("origin") == "observed"
    ]
    doc["quality"] = {
        "score": round(0.55 * coverage + 0.45 * fidelity_coverage),
        "stateCoverage": round(100 * confirmed_states / max(1, total_states)),
        "issues": issues,
        "observedCoverage": coverage,
        "fidelityCoverage": fidelity_coverage,
    }
    doc["contentHash"] = _content_hash(doc)
    return doc
