# DesignAI Web — полная спецификация

## 1. Суть продукта

Нодовый редактор веб-дизайна, где LLM генерирует не картинку и не код, а **Design IR** — редактируемый JSON (дизайн-токены + дерево секций из закрытой библиотеки ~25 блоков). Всё — генерация, микс, ручная правка, возврат в промпт — операции над одним IR. Конкурент v0 / Claude Design, но с ручным управлением через граф (как ComfyUI/Houdini) и Figma-инструментами.

**Ключевой цикл:**

```
Задача → Генерация вариантов → Микс с весами → Figma-правка геометрии
→ «Продолжить от этой версии» (refine) → Новые компоненты на той же стилевой ДНК
→ Дизайн-док → UI/UX-система
```

---

## 2. Архитектура

**Стек:** Python 3.14 + FastAPI + uvicorn (порт 8420), фронтенд — чистый vanilla JS (без фреймворков), JSON Schema Draft-07.

```
app/
  server.py          FastAPI, 9 эндпоинтов, ThreadPoolExecutor(4) для параллельных LLM-вызовов
  colorutils.py      sRGB ↔ OKLab/OKLCH (формулы Ottosson), взвешенный микс hex-цветов, stdlib
  scraper.py         httpx + BeautifulSoup + trafilatura + tinycss2 + Playwright + Pillow
  my_verify.py       smoke-тест API (7 проверок)
  static/
    nodes.html/js    нодовый редактор: 6 типов нод, pan/zoom, провода с типами, автосейв localStorage
    renderer.js      IR → DOM: CSS-переменные из токенов, Google Fonts, frame-геометрия, артборд 960px
    geoedit.js       ядро Figma-геометрии: выделение/drag(snap 8px)/resize(8 хендлов)/marquee/inline-текст/выравнивание/распределение
    editor.js        полноэкранный DNA-редактор: тулбар, линейки, слои, инспектор, undo(50 шагов), pan/zoom
    gallery.html     галерея сохранённых IR из results/
schema/
  design-ir.schema.json   JSON Schema: tokens(8 цветов, 2 шрифта, радиусы, отступы, тени) + tree(19 типов секций) + frame(Figma-модель) + _frames(оверрайды props)
docs/
  BLOCKS.md          каталог 19 типов секций, варианты, props, правила композиции, геометрия frame
  DESIGN-KNOWLEDGE.md  база знаний: режимы edit/generate, правила интерпретации референсов, паттерны компонентов, quality bar, промпт-инжиниринг, vision-анализ
  frame-example.json пример IR с геометрией (карточка объявления Rsale)
spike/
  run_test.py        LLM-клиент (stdlib): 5 провайдеров, chat + chat_vision, build_system_prompt, extract_json, repair-режим
  validate.py        валидация по схеме
  system-prompt.md   системный промпт генератора (шаблон с плейсхолдерами)
  test-briefs.md     7 брифов + критерии go/no-go + результаты матрицы 42 генераций
  run_all.py         фоновый прогон матрицы
results/             48 файлов: b1–b7 × qwen/kimi × температуры, *-fixed.json после repair
test-targets/rsale-site/  HTML реального сайта + analysis.json (кэш)
```

---

## 3. Design IR (ядро)

**JSON Schema Draft-07**, версия 1.0:

- **tokens** (обязательны): `mode` (light/dark), `color` (8 ключей: primary, secondary, accent, background, surface, text, textMuted, border — все hex), `font` (display + body: family + weight, scale: compact/default/spacious), `radius` (card/button/input: none→full), `spacing` (section: sm→xl, container: narrow→full), `shadow` (none→lg).
- **tree** (обязателен, ≥1): массив секций, каждая — `{id, type, variant, props, children?, frame?, _frames?}`. 19 типов: navbar, hero, logo-cloud, feature-grid, feature-alternating, stats, steps, gallery, testimonials, pricing, comparison, team, blog-grid, faq, cta, contact-form, newsletter, banner, footer. Для 8 типов props строго типизированы (navbarProps, heroProps, pricingProps, statsProps, faqProps, contactFormProps, newsletterProps, footerProps).
- **frame** (опционален на любом узле): Figma-модель — width/height (px | fill | hug), x/y (только в layout:free), layout (auto/free), direction, gap, padding, justify, align, wrap, min/maxWidth/Height.
- **_frames**: оверрайды frame для props-элементов секции (ключи — пути типа `props.links.0`).
- **meta**: name, description, styleTags, mixOf (индексы + веса для микса).
- **elements** (children): 13 типов — heading, text, button, image, badge, card, icon, divider, avatar, rating, input, stat, list. Рекурсивная вложенность.

---

## 4. API (9 эндпоинтов)

| Эндпоинт | Что делает |
|---|---|
| `POST /api/generate` | `{brief, count≤5, provider, styleHint?, seedTag?}` → параллельные LLM-вызовы, режим edit при наличии styleHint, температура 0.8/0.3 |
| `POST /api/refine` | `{ir, instruction, provider}` → LLM получает IR + инструкцию, repair-проход при невалидности |
| `POST /api/mix` | `{irs, weights}` → детерминированный микс: цвета — OKLCH интерполяция (hue по кратчайшей дуге), enum/tree — от доминанта |
| `POST /api/validate` | `{ir}` → jsonschema Draft-07 |
| `POST /api/clone` | `{url, component, provider}` → fetch HTML+CSS → LLM в режиме edit → IR, repair |
| `POST /api/analyze-header` | Разбор test-targets/rsale-site → structureSummary + suggestedTokens + headerBrief, кэш |
| `POST /api/vision-decompose` | `{image(base64), brief, provider}` → pixel-perfect IR из скриншота, автоперебор vision-провайдеров (xai→gemini→groq→qwen), repair |
| `POST /api/scrape` | `{url, use_playwright}` → полный анализ сайта: контент + стили + структура + скриншот + computed styles |
| `GET /`, `/nodes`, `/static/*` | Фронтенд |

---

## 5. LLM-провайдеры (5 штук)

| Провайдер | Модель | Vision | Ключ |
|---|---|---|---|
| **qwen** | qwen3.7-max | qwen-vl-max-latest + 3 fallback | BAILIAN_TOKEN_PLAN_API_KEY |
| **kimi** | k3 (T=1 фикс.) | — | OAuth из ~/.kimi-code/credentials |
| **groq** | llama-3.3-70b-versatile | llama-3.2-90b-vision | GROQ_API_KEY |
| **gemini** | gemini-2.0-flash | gemini-2.0-flash (нативный) | GEMINI_API_KEY |
| **xai** | grok-3-beta | grok-2-vision | XAI_API_KEY |

Все вызовы через stdlib `urllib.request` (кроме scraper — httpx). OpenAI-совместимый формат + отдельный путь для Gemini API. `response_format: json_object` с fallback. `extract_json` вытаскивает JSON из markdown-обёрток.

---

## 6. Нодовый редактор (nodes.js)

**6 типов нод:**

- **Промпт** — текст задачи, propagate живой текст
- **Референс** — загрузка изображения + описание стиля + чекбокс «Разбить на компоненты» (decompose → vision-анализ → free-layout → Editor-нода)
- **Генератор** — провайдер, 1–3 варианта, миниатюры с живым превью, кнопки «→ Editor» и «→ Reference»
- **Редактор (DNA)** — превью IR + GeoEdit-инструменты + кнопка открытия полноэкранного редактора
- **Микс** — 2–4 входа со слайдерами весов, «Смешать по весам»
- **Клон (сайт)** — URL + описание компонента → `/api/clone`

**Механика графа:** pan/zoom (зум к курсору), правый клик → контекстное меню создания, провода с проверкой типов (text/ir) и циклов, один провод на вход, автосейв в localStorage, экспорт/импорт JSON, `window.GraphDev` для консоли.

**Dataflow:** pull-based. Генератор и микс — по кнопке. Текстовые ноды propagate живой текст. Edit мутирует IR через GeoEdit.

---

## 7. Figma-инструменты

### geoedit.js (ядро, ~870 строк)

- Выделение кликом (рамка + чип «тип · W×H»), Shift — мультивыделение, marquee (резиновое выделение)
- Drag с привязкой к сетке 8px, плавный через rAF
- 8 resize-хендлов (nw/n/ne/e/se/s/sw/w), live-превью размера
- Двойной клик — inline-редактирование текста (contenteditable по data-ir-path)
- Автоперевод родителя в `layout:"free"` при первом drag (соседи сохраняют позиции)
- Выравнивание: left/centerH/right/top/centerV/bottom
- Распределение: distributeH/distributeV
- «Сбросить frame» — удаление геометрии узла
- Адресация: `{secIdx, path}` — от корня IR до любого вложенного элемента

### editor.js (полноэкранный DNA-редактор, ~760 строк)

- Тулбар: инструменты (select/hand), zoom, выравнивание, undo, сохранить/закрыть
- Линейки (canvas, адаптивный шаг)
- Панель слоёв: артборд → секции → props-элементы → children (3 уровня вложенности)
- Инспектор: позиция/размер (X/Y/W/H), токены (8 цветов, шрифты, радиусы, отступы, тени), тексты
- Undo: 50 шагов, command pattern через JSON-снимки
- Pan/zoom канваса

---

## 8. Рендерер (renderer.js)

IR → DOM: CSS-переменные из токенов, Google Fonts, классы компонентов. Дизайн-ширина 960px, масштабируется `transform: scale`. Поддержка обоих режимов: flow (без frame) и free-layout (с frame). 19 рендереров секций + 13 типов элементов. `data-ir-path` и `data-ir-sec` для адресации при редактировании. Дефолтные токены при неполных данных.

---

## 9. Scraper (scraper.py)

- **httpx** — быстрый fetch HTML
- **BeautifulSoup** — парсинг структуры (navbar, hero, sections, CTA, footer)
- **trafilatura** — извлечение основного контента
- **tinycss2** — парсинг CSS → токены (цвета, шрифты, радиусы, CSS custom properties)
- **Playwright** — headless Chromium: JS-рендер, скриншоты, computed styles
- **Pillow** — resize изображений для vision API (макс. 1568px)

---

## 10. Spike (Фаза 0) — результаты

Матрица 42 генерации: 7 брифов × 2 провайдера × 3 температуры.

| Критерий | Результат |
|---|---|
| Валидность без repair | 36/42 = 86% |
| Repair за 1 попытку | 6/6 = 100% |
| Композиция (navbar→hero→...→footer) | 35/36 |
| Гранулярность (b6 = 1 блок) | 6/6 |
| Устойчивость к адверсариальному брифу | 6/6 |

**Вердикт: GO.**

---

## 11. Что реализовано vs что заложено в видение

| Механика | Статус |
|---|---|
| Генерация по задаче | ✅ |
| Микс с весами (OKLCH) | ✅ |
| Микс со своими промптами (styleHint) | ✅ |
| Нодовый граф | ✅ v1 |
| Figma-правка геометрии | ✅ ядро |
| Полноэкранный редактор (слои, инспектор, undo) | ✅ |
| Vision-анализ скриншота → IR | ✅ (4 провайдера) |
| Декомпозиция на компоненты (free-layout) | ✅ |
| Клонирование компонента с сайта | ✅ |
| Scraper (Playwright + computed styles) | ✅ |
| Микс с готовым сайтом как нодой | 🟡 analyze-header есть, но не источник микса |
| Авто-diff геометрии → промпт | 🟡 refine получает IR + инструкцию, но не автоматический diff |
| Дизайн-док / UI/UX-система | ❌ Фаза 4 |
| Style DNA (вектор стиля, «залочить стиль») | ❌ |
| RAG-база знаний (pgvector) | ❌ |
| Prompt Enhancer (qwen3-max) | ❌ |
| Critic-нода (рендер → скриншот → vision → автофикс) | ❌ |
| Compose Page (сборка страницы из блоков) | ❌ |
| Export (HTML/React/Figma) | ❌ |
| SaaS-обвязка (auth, биллинг, команды) | ❌ |

---

## 12. Дорожная карта (PLAN.md)

Фаза 0 (Spike) ✅ → Фаза 1 (MVP генерации) → Фаза 2 (Ноды и микс) → Фаза 3 (Редактор) → Фаза 4 (Страницы + RAG) → Фаза 5 (SaaS). Фактически Фазы 0–3 реализованы в виде локального dev-инструмента.

---

## 13. Замечание по безопасности

**`start.bat` содержит API-ключи Gemini и xAI в открытом виде.** Рекомендую перенести их в переменные окружения или `.env`-файл, исключённый из контроля версий.
