"""Design Knowledge Base — «вкус» генератора.

Дистиллят открытых источников (UX/UI Agent Skills, UI UX Pro Max, Refero,
Vercel Web Design Guidelines, Baymard) в компактный детерминированный слой:
тип продукта по брифу → кураторские палитры, шрифтовые пары (typography.py),
UX-правила и анти-паттерны. Никакого скачивания чужих репозиториев: только
собственные формулировки правил и ручные палитры.

Используется /api/generate: каждый вариант получает свою кураторскую палитру
(лок в tokens.color), шрифтовую пару (typography) и секцию промпта с правилами
и анти-клише. Style DNA с провода по-прежнему побеждает всё.
"""
from __future__ import annotations


# ---------- анти-паттерны «AI-дизайна» (всегда) ----------

ANTI_AI = [
    "фиолетово-синий градиент на всю страницу как «дефолтный AI-стиль»",
    "эмодзи вместо иконок",
    "три одинаковые карточки с иконкой в кружке и дежурным текстом",
    "hero с градиентным текстом и размытыми blob-пятнами на фоне",
    "стеклянные карточки (glassmorphism) без функциональной причины",
    "одинаковые отступы везде — без визуального ритма и акцентов",
    " generic stock-описания изображений («business team smiling»)",
]

# ---------- типы продуктов ----------

PRODUCT_TYPES: dict[str, dict] = {
    "marketplace": {
        "label": "маркетплейс / объявления",
        "keywords": ("маркетплейс", "marketplace", "объявлен", "каталог товаров",
                     "продав", "покуп", "listing", "classifieds", "барахолк",
                     "витрин", "товар"),
        "presets": ["minimal", "bento"],
        "fonts": ["manrope", "inter"],
        "palettes": [
            {"primary": "#E85D26", "secondary": "#17201D", "accent": "#0E7A5F",
             "background": "#FFFFFF", "surface": "#F6F7F8", "text": "#17201D",
             "textMuted": "#5D6B66", "border": "#E2E7E5"},
            {"primary": "#FFB020", "secondary": "#F2F4F5", "accent": "#4C9AFF",
             "background": "#101214", "surface": "#181B1F", "text": "#F2F4F5",
             "textMuted": "#9AA4AB", "border": "#2A2F34"},
        ],
        "rules": [
            "поиск — главный элемент шапки, всегда виден, с placeholder-примером",
            "карточки товаров сеткой ≥3 колонок на десктопе, фото доминирует над текстом",
            "цена крупнее остального текста карточки; вторичные действия — ghost-иконки",
            "фильтры и категории доступны без скролла (Baymard: видимая фильтрация)",
        ],
    },
    "saas": {
        "label": "SaaS / продукт",
        "keywords": ("saas", "платформ", "сервис для", "подписк", "дашборд",
                     "dashboard", "crm", "аналитик", "автоматиз", "облачн"),
        "presets": ["bento", "minimal"],
        "fonts": ["sora", "manrope"],
        "palettes": [
            {"primary": "#4F46E5", "secondary": "#0F172A", "accent": "#06B6D4",
             "background": "#FFFFFF", "surface": "#F8FAFC", "text": "#0F172A",
             "textMuted": "#64748B", "border": "#E2E8F0"},
            {"primary": "#818CF8", "secondary": "#E2E8F0", "accent": "#22D3EE",
             "background": "#0B1120", "surface": "#131A2A", "text": "#E2E8F0",
             "textMuted": "#94A3B8", "border": "#1E293B"},
        ],
        "rules": [
            "hero: один чёткий value-proposition + одна primary-кнопка, без второго CTA рядом",
            "фичи — bento-плитки с метриками, а не список иконок",
            "социальное доказательство (логотипы/цифры) сразу после hero",
            "тарифы: рекомендуемый план визуально выделен (бордер/тень), а не только подписью",
        ],
    },
    "editorial": {
        "label": "медиа / журнал",
        "keywords": ("журнал", "стать", "медиа", "блог", "новост", "editorial",
                     "издани", "публикац", "лонгрид"),
        "presets": ["editorial", "minimal"],
        "fonts": ["playfair", "tenor"],
        "palettes": [
            {"primary": "#1A1A1A", "secondary": "#374151", "accent": "#B45309",
             "background": "#FAF9F6", "surface": "#FFFFFF", "text": "#1A1A1A",
             "textMuted": "#6B7280", "border": "#E5E2DB"},
            {"primary": "#F5F0E8", "secondary": "#EDE8E0", "accent": "#D4A373",
             "background": "#141210", "surface": "#1E1B18", "text": "#EDE8E0",
             "textMuted": "#A39E93", "border": "#2E2A26"},
        ],
        "rules": [
            "текстовая мера 55–75 символов; заголовки — serif display крупным кеглем",
            "дата/автор/время чтения — мелким muted-текстом у заголовка",
            "карточки статей: рубрика (overline) → заголовок → лид, фото не обязательно",
            "ритм за счёт типографики и воздуха, без декоративных элементов",
        ],
    },
    "ecommerce": {
        "label": "интернет-магазин",
        "keywords": ("магазин", "ecommerce", "e-commerce", "shop", "купить",
                     "корзин", "бренд одежд", "косметик", "мебел"),
        "presets": ["minimal", "bento"],
        "fonts": ["montserrat", "manrope"],
        "palettes": [
            {"primary": "#111827", "secondary": "#374151", "accent": "#16A34A",
             "background": "#FFFFFF", "surface": "#F9FAFB", "text": "#111827",
             "textMuted": "#6B7280", "border": "#E5E7EB"},
            {"primary": "#F9FAFB", "secondary": "#E5E7EB", "accent": "#34D399",
             "background": "#0F1115", "surface": "#171A21", "text": "#F3F4F6",
             "textMuted": "#9CA3AF", "border": "#262B36"},
        ],
        "rules": [
            "фото товара занимает ≥60% карточки; цена и CTA «В корзину» всегда видны",
            "бейджи скидок/новинок — контрастный акцент, не более одного на карточку",
            "доверие: доставка/возврат/гарантия короткой строкой до footer",
        ],
    },
    "fintech": {
        "label": "финтех / банк",
        "keywords": ("банк", "финанс", "fintech", "платёж", "платеж", "инвестиц",
                     "криптовалют", "кошел", "страхов"),
        "presets": ["minimal", "glass"],
        "fonts": ["plex", "sora"],
        "palettes": [
            {"primary": "#0A2540", "secondary": "#0A2540", "accent": "#635BFF",
             "background": "#FFFFFF", "surface": "#F6F9FC", "text": "#0A2540",
             "textMuted": "#425466", "border": "#E3E8EE"},
            {"primary": "#7C9CFF", "secondary": "#E6EBF4", "accent": "#3DDAB4",
             "background": "#0A0F1E", "surface": "#121830", "text": "#E6EBF4",
             "textMuted": "#8A94B0", "border": "#1F2745"},
        ],
        "rules": [
            "цифры и балансы — табличными начертаниями, крупно, с валютой",
            "доверие: лицензии/защита/шифрование текстовыми маркерами, не иконками-замками",
            "никаких игривых радиусов: радиусы md, тени минимальные",
        ],
    },
    "portfolio": {
        "label": "портфолио / студия",
        "keywords": ("портфолио", "студия", "дизайнер", "фотограф", "архитект",
                     "кейсы", "portfolio", "агентств", "продакшн"),
        "presets": ["brutal", "editorial"],
        "fonts": ["bebas", "unbounded"],
        "palettes": [
            {"primary": "#111111", "secondary": "#111111", "accent": "#D9F24F",
             "background": "#FAFAFA", "surface": "#FFFFFF", "text": "#111111",
             "textMuted": "#6F6F6F", "border": "#E4E4E4"},
            {"primary": "#F2F2F2", "secondary": "#EDEDED", "accent": "#FF4D00",
             "background": "#0D0D0D", "surface": "#161616", "text": "#F2F2F2",
             "textMuted": "#8F8F8F", "border": "#262626"},
        ],
        "rules": [
            "работы крупно: сетка кейсов с большими превью, подписи минимальны",
            "характер через типографику: display-заголовки могут занимать всю ширину",
            "один смелый акцентный цвет вместо палитры из многих",
        ],
    },
    "edtech": {
        "label": "образование",
        "keywords": ("курс", "обучен", "школ", "edtech", "образован", "учеб",
                     "тренинг", "вебинар", "репетитор"),
        "presets": ["bento", "minimal"],
        "fonts": ["manrope", "golos"],
        "palettes": [
            {"primary": "#6C5CE7", "secondary": "#2D3436", "accent": "#00B894",
             "background": "#FFFFFF", "surface": "#F5F6FA", "text": "#2D3436",
             "textMuted": "#636E72", "border": "#E4E7F0"},
            {"primary": "#A29BFE", "secondary": "#F5F3FF", "accent": "#FDCB6E",
             "background": "#151322", "surface": "#1E1B2E", "text": "#F5F3FF",
             "textMuted": "#9B94B8", "border": "#2C2743"},
        ],
        "rules": [
            "программа курса — раскрывающиеся модули/шаги, а не сплошной текст",
            "результат обучения (что сможешь) раньше описания процесса",
            "отзывы с именем и результатом, не безликие цитаты",
        ],
    },
    "healthcare": {
        "label": "медицина / здоровье",
        "keywords": ("медицин", "клиник", "здоров", "врач", "стоматолог",
                     "healthcare", "аптек", "терап", "диагностик"),
        "presets": ["minimal"],
        "fonts": ["inter", "golos"],
        "palettes": [
            {"primary": "#0E7490", "secondary": "#164E63", "accent": "#14B8A6",
             "background": "#FFFFFF", "surface": "#F0FDFA", "text": "#134E4A",
             "textMuted": "#5B7672", "border": "#D6EAE6"},
            {"primary": "#5EEAD4", "secondary": "#CCFBF1", "accent": "#38BDF8",
             "background": "#0C1A1A", "surface": "#122424", "text": "#E6FFFA",
             "textMuted": "#8FB8B2", "border": "#1E3A38"},
        ],
        "rules": [
            "спокойная палитра (teal/мята), никакого агрессивного красного",
            "запись/CTA видна на каждом экране; телефон кликабельный текст, не картинка",
            "врачи с именами и специальностями — доверие через конкретику",
        ],
    },
    "event": {
        "label": "событие / конференция",
        "keywords": ("конференц", "событи", "ивент", "event", "фестивал",
                     "митап", "концерт", "выставк", "хакатон"),
        "presets": ["brutal", "glass"],
        "fonts": ["bebas", "unbounded"],
        "palettes": [
            {"primary": "#FF3D00", "secondary": "#1A1A1A", "accent": "#FFD600",
             "background": "#0E0E10", "surface": "#17171B", "text": "#F5F5F5",
             "textMuted": "#9D9DA6", "border": "#26262C"},
            {"primary": "#121212", "secondary": "#121212", "accent": "#0047FF",
             "background": "#F4F1EA", "surface": "#FFFFFF", "text": "#121212",
             "textMuted": "#6E6A60", "border": "#DDD8CC"},
        ],
        "rules": [
            "дата и место — крупно в hero, до описания",
            "спикеры/программа сеткой с фото; цена билета рядом с CTA",
            "счётчик/дедлайн как элемент срочности, не мигающий баннер",
        ],
    },
    "food": {
        "label": "еда / ресторан",
        "keywords": ("ресторан", "кафе", "еда", "доставк", "меню", "пицц",
                     "суши", "кофе", "бар ", "кухн"),
        "presets": ["editorial", "minimal"],
        "fonts": ["playfair", "tenor"],
        "palettes": [
            {"primary": "#7C2D12", "secondary": "#431407", "accent": "#EA580C",
             "background": "#FFF8F0", "surface": "#FFFFFF", "text": "#431407",
             "textMuted": "#8A6A5C", "border": "#F0E2D4"},
            {"primary": "#FDE68A", "secondary": "#FEF3C7", "accent": "#F97316",
             "background": "#1C1410", "surface": "#281C14", "text": "#FEF3C7",
             "textMuted": "#B59B7F", "border": "#3A2C1E"},
        ],
        "rules": [
            "аппетитные фото крупно; меню с ценами, выровненными в колонку",
            "тёплая палитра (терракота/крем), холодные синие запрещены",
            "адрес/часы/доставка — в шапке или первом экране",
        ],
    },
    "landing": {
        "label": "лендинг",
        "keywords": (),
        "presets": ["bento", "minimal"],
        "fonts": ["manrope", "sora"],
        "palettes": [
            {"primary": "#2563EB", "secondary": "#0F172A", "accent": "#F59E0B",
             "background": "#FFFFFF", "surface": "#F8FAFC", "text": "#0F172A",
             "textMuted": "#64748B", "border": "#E2E8F0"},
            {"primary": "#60A5FA", "secondary": "#E5E7EB", "accent": "#FBBF24",
             "background": "#0F1420", "surface": "#161D2E", "text": "#E5E7EB",
             "textMuted": "#94A3B8", "border": "#232E45"},
        ],
        "rules": [
            "один экран = одна мысль; каждая секция отвечает «зачем мне это»",
            "CTA повторяется после каждых 1–2 секций, одинаковая формулировка",
            "конкретика вместо абстракций: цифры, сроки, имена",
        ],
    },
}


def detect_product(brief: str) -> tuple[str, dict]:
    """Тип продукта по ключевым словам брифа (RU/EN). Дефолт — landing."""
    low = f" {(brief or '').lower()} "
    best_id, best_score = "landing", 0
    for type_id, info in PRODUCT_TYPES.items():
        score = sum(1 for w in info["keywords"] if w in low)
        if score > best_score:
            best_id, best_score = type_id, score
    return best_id, PRODUCT_TYPES[best_id]


def design_direction(type_id: str, info: dict, variant: int) -> tuple[str, dict]:
    """Секция промпта + палитра для варианта (варианты кругом по палитрам)."""
    palette = info["palettes"][(variant - 1) % len(info["palettes"])]
    lines = [
        f"## Design direction — {info['label']}",
        "Палитра этого варианта (обязательно, запиши в tokens.color): "
        + ", ".join(f"{k} {v}" for k, v in palette.items()),
        "UX-правила для этого типа продукта:",
        *("- " + r for r in info["rules"]),
        "Анти-паттерны — НИКОГДА так не делай:",
        *("- " + a for a in ANTI_AI),
    ]
    return "\n".join(lines), palette
