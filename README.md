# DesignAI Web

**Нодовый редактор веб-дизайна: граф как в Houdini, инструменты как в Figma.** Правым кликом по холсту создаёшь ноды — промпт, референс (изображение/сайт), генератор, микс, редактор — и соединяешь их проводами. Пишешь, что нужно сделать — шапку, карточку объявления, прайсинг — генератор выдаёт варианты IR. Миксуешь варианты между собой и с референсами, с весами. **Внутри каждой ноды с результатом — живое превью и Figma-инструменты**: выделение, перемещение, ресайз, фреймы, токены. Отредактированное подаётся обратно в промпт для следующей итерации. Из отдельных компонентов собирается дизайн-док и целая UI/UX-система.

Редактор открывается на `/` (`app/static/nodes.html`, алиас `/nodes`).

**Основной цикл:**

```
Задача («сделай шапку» / «карточка объявления»)
  → Генерация вариантов
  → Микс: свои промпты + готовые сайты + скриншоты, веса на каждом источнике
  → Ручная правка как в Figma: позиция, размеры, фрейм, тексты, токены
  → «Продолжить от этой версии»: правки сериализуются в промпт
  → Новые компоненты на той же стилевой ДНК
  → Дизайн-док → UI/UX-система
```

Технический стержень — **Design IR**: LLM (Qwen / Kimi) генерирует не картинку и не код, а редактируемый JSON (дизайн-токены + дерево секций из закрытой библиотеки блоков). Всё — генерация, микс, ручная правка, возврат в промпт — операции над одним IR.

**Текущее состояние:** локальный dev-инструмент; ядро цикла работает в нодовом графу: генерация вариантов, Figma-правка геометрии в ноде «Редактор», микс по весам в OKLCH, провода с типами. Чего не хватает до видения — в таблице ниже. Продуктовая дорожная карта — [PLAN.md](PLAN.md). [REPORT.md](REPORT.md) — отчёт по прежней версии инструмента (классическое полотно, удалено); тесты API из него по-прежнему актуальны.

## Что уже есть vs что нужно для видения

| Механика видения | Статус |
|---|---|
| Генерация компонента по задаче (шапка, карточка) | ✅ `/api/generate`, закрытая библиотека блоков |
| Микс вариантов с весами | ✅ `/api/mix`: цвета — интерполяция в OKLCH, структура — от доминанта |
| Микс со своими промптами | ✅ `styleHint` в генерации + `/api/refine` |
| Микс с готовым сайтом | 🟡 `/api/analyze-header`: сайт → токены + бриф; пока не источник микса и не нода |
| Микс со скриншотом | ✅ pixel-perfect reproduction: VLM (GLM) → Python-измерения (цвета, bbox, ASCII-матрицы) → PNG-иконки base64 → HTML absolute positioning → native screenshot → pixel diff по регионам → итеративная доводка; целевой diff < 5% (достигнуто 4.7% на RSale header); алгоритм — [docs/PIXEL-PERFECT-ALGORITHM.md](docs/PIXEL-PERFECT-ALGORITHM.md) |
| Нодовый граф (Houdini-like) | ✅ v1: холст pan/zoom, меню по правому клику, провода с типами (text/ir, проверка циклов), ноды Prompt/Reference/Generator/Edit/Mix/Clone, автосейв + экспорт/импорт JSON |
| Figma-правка: позиция, размеры, фрейм | ✅ ядро `geoedit.js`: выделение кликом, drag с привязкой к сетке 8px, 8 resize-хендлов, двойной клик — редактирование текста inline, сброс frame; полноэкранный DNA-редактор (`editor.js`): слои, линейки, левая панель инструментов как в pen.dev (select/rect/text/frame/hand, хоткеи V/R/T/F/H, создание элементов drag-ом — новые элементы получают `absolute:true` и не ломают раскладку родителя), инспектор (`inspector.js`): Alignment, Position X/Y/R + Absolute Position, Flex Layout (direction none/column/row, 3×3 alignment, gap, space-between/around, padding), Dimensions + Fill/Hug/Clip; в самой ноде Edit — превью + тот же инспектор + зум/скролл |
| Подача правок обратно в промпт | 🟡 refine получает IR + ручную инструкцию; авто-diff → промпт нет |
| Дизайн-док / UI/UX-система из компонентов | ❌ Фаза 4 PLAN.md (Compose Page, Style DNA) |

Следующие шаги: **интеграция pixel-perfect пайплайна в нодовый граф** (нода Reproduce: скриншот → VLM-анализ → Python-измерения → HTML → diff), **авто-diff геометрии → промпт**, сборка дизайн-дока из нод.

## Быстрый старт

```bash
# зависимости (fastapi, uvicorn, jsonschema) уже стоят в .venv;
# при чистой установке:
python -m venv .venv && .venv/Scripts/python -m pip install fastapi uvicorn jsonschema

# ключ Qwen (Alibaba Bailian Token Plan)
set BAILIAN_TOKEN_PLAN_API_KEY=sk-...
# Kimi использует OAuth-токен kimi CLI: ~/.kimi-code/credentials/kimi-code.json

# запуск
.venv/Scripts/python app/server.py
```

Откроется `http://127.0.0.1:8420` (вкладка браузера открывается автоматически).

Провайдеры (`spike/run_test.py`): `qwen` — модель `qwen3.7-max`, температура 0.8; `kimi` — модель `k3`, температура принудительно 1 (ограничение модели); `glm` — модель `glm-4v` (Zhipu AI), vision-анализ структуры UI для pixel-perfect reproduction (см. [docs/PIXEL-PERFECT-ALGORITHM.md](docs/PIXEL-PERFECT-ALGORITHM.md)).

## Как устроено

**Design IR** (`schema/design-ir.schema.json`, JSON Schema Draft-07):

```json
{
  "version": "1.0",
  "meta": { "name": "...", "styleTags": ["..."], "mixOf": [...] },
  "frame": { "width": 1440, "height": "hug" },
  "tokens": {
    "mode": "dark",
    "color": { "primary": "#5B5BD6", "background": "#0E0E12", "...": "..." },
    "font": { "display": { "family": "Sora", "weight": 600 }, "body": {...}, "scale": "spacious" },
    "radius": { "card": "lg", "button": "md", "input": "md" },
    "spacing": { "section": "xl", "container": "default" },
    "shadow": "sm"
  },
  "tree": [ { "type": "navbar", "variant": "classic", "props": {...} }, "..." ]
}
```

- Секции — только из закрытого каталога (~25 типов: navbar, hero, feature-grid, pricing, faq, footer…): модель выбирает `type` + `variant` и заполняет `props`, не изобретая новых блоков. Каталог и правила композиции — в [docs/BLOCKS.md](docs/BLOCKS.md).
- **Геометрия (`frame`, модель Figma)** — опционально на любом узле: размеры (px / `fill` / `hug`), позиция `x/y` внутри `layout:"free"`-контейнеров, auto-layout собственных детей (`direction/gap/padding/justify/align/wrap`), корневой артборд (`frame.width` — ширина холста). Плюс свойства модели pen.dev: `rotation` (поворот), `absolute` (вывод из раскладки родителя, аналог `layoutPosition:absolute`), `clip` (обрезка содержимого). Без frame — прежняя flow-раскладка; рендерер и валидация поддерживают оба режима. Пример IR с геометрией (карточка объявления) — [docs/frame-example.json](docs/frame-example.json).
- Системный промпт генератора собирается из шаблона `spike/system-prompt.md` + встроенной схемы + каталога блоков (`build_system_prompt()` в `spike/run_test.py`).
- Рендерер (`app/static/renderer.js`) превращает IR в DOM: CSS-переменные из токенов, Google Fonts, классы компонентов; превью — десктопная раскладка 960px, масштабируется `transform: scale`.

**Pixel-perfect reproduction** (скриншот → HTML с diff < 5%) — отдельный пайплайн, не через Design IR. VLM (GLM) даёт только структуру; все числа (цвета, bbox, radius) извлекаются из пикселей Python-скриптами (PIL/numpy). Иконки и кириллический контент — PNG base64 из оригинала. Сборка — absolute positioning, не flexbox. Сравнение — native screenshot (Playwright, `device_scale_factor=1`, без `transform: scale`) и pixel diff по регионам. Полный алгоритм, скрипты и антипаттерны — [docs/PIXEL-PERFECT-ALGORITHM.md](docs/PIXEL-PERFECT-ALGORITHM.md).

## API

| Метод | Что делает |
|---|---|
| `POST /api/generate` | `{brief, count≤5, provider, styleHint?, seedTag?}` → `{variants, errors}`. Параллельные вызовы LLM (ThreadPoolExecutor, 4 воркера); в каждый промпт добавляется «вариант N: визуально отличное решение». Упавшие поодиночке варианты возвращаются в `errors`, не роняя остальные. |
| `POST /api/refine` | `{ir, instruction, provider}` → `{ir}`. Модель получает текущий IR + инструкцию и возвращает полный обновлённый IR; ответ валидируется по схеме, при ошибках — один repair-вызов со списком ошибок, иначе 502. |
| `POST /api/mix` | `{irs, weights}` → `{ir}`. Детерминированно: 8 цветовых токенов — взвешенная интерполяция в OKLCH (hue по кратчайшей дуге, все нули → равные доли); enum-токены и всё `tree` — от варианта с максимальным весом. В `meta.mixOf` пишутся индексы и веса. |
| `POST /api/validate` | `{ir}` → `{ok, errors[]}` по `schema/design-ir.schema.json`. |
| `POST /api/clone` | `{url, component, provider}` → `{ir}`. Fetch HTML+CSS сайта → LLM в режиме edit → IR, воспроизводящий указанный компонент точь-в-точь. Repair-проход при невалидности. |
| `POST /api/analyze-header` | Разбор `test-targets/rsale-site/` (HTML шапки + фрагменты страницы) → `{structureSummary, suggestedTokens, headerBrief}`; кэш в `analysis.json`, `force=true` обходит. |
| `GET /` (алиас `/nodes`), `/static/*` | Фронтенд: нодовый редактор (`nodes.html`), галерея сохранённых IR из `results/` (`gallery.html`). |

## UI-флоу (нодовый редактор)

1. **Правый клик по холсту** → создать ноду: Промпт (текст задачи), Референс (изображение + описание стиля), Генератор, Редактор (Figma), Микс. Перетаскивание — за заголовок; панорама — drag фона, зум — колесо.
2. **Провода**: тянуть с выходного порта на входной. Типы проверяются (text/IR), циклы отклоняются, на один вход — один провод.
3. **Генерация**: в Генераторе «▶» — промпт берётся из провода (или из собственного поля), провайдер qwen/kimi, 1–3 варианта → миниатюры; клик по миниатюре выбирает вариант на выходе ноды.
4. **Figma-правка**: в ноде Редактор клик по блоку выделяет его (рамка с чипом «тип · W×H»), drag перемещает (родитель автоматически переводится в `layout:"free"`, соседи сохраняют позиции), хендлы меняют размер, «Сбросить frame» убирает геометрию узла; справа — инспектор как в pen.dev: Alignment (для одного элемента — внутри родителя, для нескольких — между собой), Position (X/Y/R, Absolute Position), Flex Layout (direction none/column/row, 3×3 alignment, gap, space-between/around, padding), Dimensions (W/H, Fill/Hug, Clip Content); зум превью — «−/+», скролл — колесо или рука в редакторе. Кнопка «Открыть DNA-редактор» — полноэкранный режим: слои, линейки и левая панель инструментов как в pen.dev — выделение (V), прямоугольник (R), текст (T), фрейм (F), рука-панорама (H); rect/text/frame создаются кликом или drag-ом в контейнер под курсором (новый элемент получает `absolute:true` — раскладка родителя не ломается). Правки сразу текут вниз по графу.
5. **Микс**: 2–4 IR-входа со слайдерами весов → «Смешать по весам» (цвета — OKLCH, структура — от доминанта) → выходной IR.
6. **Сохранение**: граф автосохраняется в localStorage; кнопки «Экспорт JSON» / «Импорт» — перенос проекта. Dev-хук для консоли — `window.GraphDev`.

## Структура

```
app/
  server.py          FastAPI + uvicorn, порт 8420; LLM-клиент импортируется из spike/run_test.py.
                     Маршруты страниц: / и /nodes — нодовый редактор
  colorutils.py      sRGB ↔ OKLab/OKLCH (формулы Ottosson), взвешенный микс hex-цветов; stdlib
  my_verify.py       независимый smoke-тест API (нужен запущенный сервер)
  ui_edit_test.py    Playwright-тест ноды Edit: выделение, drag, инспектор (нужен сервер)
  ui_editor_test.py  Playwright smoke-тест полноэкранного редактора (нужен сервер)
  static/
    renderer.js      IR → DOM (токены, блоки, frame-геометрия, артборд, _frames)
    geoedit.js       ядро Figma-геометрии: выделение/drag (snap 8px)/resize/текст inline
    inspector.js     панель свойств как в pen.dev: Alignment/Position/Flex Layout/Dimensions
    editor.js        полноэкранный Figma-редактор: тулбар, слои, инспектор, undo
    nodes.html, nodes.js  нодовый редактор: холст pan/zoom, правый клик, провода, 6 типов нод
    gallery.html     галерея сохранённых IR из results/
schema/
  design-ir.schema.json   JSON Schema Draft-07; в meta добавлено необязательное mixOf (для /api/mix)
docs/BLOCKS.md       каталог блоков и правила композиции страницы
docs/DESIGN-KNOWLEDGE.md  база знаний: правила генерации, интерпретация референсов, промпт-инжиниринг
docs/PIXEL-PERFECT-ALGORITHM.md  алгоритм pixel-perfect reproduction из скриншота (GLM VLM + Python-измерения + pixel diff)
docs/frame-example.json   пример IR с геометрией (карточка объявления)
spike/               Фаза 0: run_test.py (LLM-клиент, stdlib), validate.py, system-prompt.md,
                     test-briefs.md, run_all.py (фоновый прогон матрицы 42 генераций)
results/             сохранённые IR матрицы спайка (b1–b7 × qwen/kimi × температуры), *-fixed.json — после repair
test-targets/rsale-site/   HTML реального сайта (шапка + страница) и analysis.json (кэш анализа)
PLAN.md              продуктовый план SaaS (ноды, редактор, RAG, SaaS-обвязка)
REPORT.md            отчёт по прежней версии (классическое полотно): архитектура API, 20 тестов, баги
```

## Spike (Фаза 0)

Автономные скрипты проверки go/no-go — в [spike/README.md](spike/README.md): прогон 7 брифов × 2 провайдера × 3 температуры (42 генерации в `results/`), валидация по схеме (`spike/validate.py`), repair-режим (починка невалидного IR через qwen).

## Ограничения

Коротко: превью только десктопное (артборд по умолчанию 960px); pixel-perfect reproduction работает как отдельный пайплайн (скрипты), интеграция в нодовый граф — следующий шаг; в ноде Edit нет undo (правки геометрии можно убрать через «Сбросить frame»); refine по промпту доступен только как API, ноды для него пока нет; `/api/generate` не валидирует ответ модели на бэкенде (невалидный вариант так и покажется в миниатюре — осознанно: видеть и чинить, а не терять). Ограничения прежней версии — в [REPORT.md](REPORT.md).
