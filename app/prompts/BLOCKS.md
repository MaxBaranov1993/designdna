# Blocks

This file is used by `app/llm_client.py` inside the generation system prompt. Keep it concise, current and model-friendly.

Sections are **composed**, not picked from a menu. `composition` is the general case: a section whose whole content is a tree of primitives inside auto-layout frames. The semantic blocks below are accelerators — use one when its shape already matches the content, and drop to `composition` the moment the content wants a shape the variants do not have. Never invent a top-level `type` outside this list; the schema and renderer would reject it.

## Free composition

### `composition`

A section with no semantic props: everything lives in `children`.

- `props`: `heading`, `subheading` (both optional, rendered left-aligned above the tree), `background` (`background` | `surface` | `primary` | `accent` | `none` — token roles only, never a hex), `density` (`tight` | `normal` | `airy`, scales the section's vertical rhythm).
- `children`: any primitive from the list below. `frame` is the container — it carries auto-layout (`frame.layout:"auto"` with `direction`/`gap`/`padding`/`justify`/`align`/`wrap`) or a free canvas (`frame.layout:"free"`, children positioned by `frame.x`/`frame.y`; a free parent needs a numeric `frame.height`).
- The section's own `frame` is only the content rail: `contentMaxWidth`/`contentGutter` (or `layout:"free"` for a free canvas). Never put `direction`/`gap`/`align`/`padding`/`width` on the section itself — that auto-layout belongs to a child `frame`; the section's vertical rhythm comes from `props.density`.
- The tree is edited in the DNA editor exactly like ordinary frame children: every child gets a layer, a selection box, drag/resize and an inspector.
- Reach for it when the section is a manifesto, a price ladder, a table of contents, a full-bleed quote, an offset diptych — anything that is not "heading + a row of cards".
- `variant` остаётся обязательным полем, но для `composition` это свободная подпись композиции (`menu-column`, `ledger-strip`, `offset-diptych`): она попадает в редактор и в слои, поэтому называйте по смыслу, а не «custom».

Example shape (abbreviated):

```json
{"id":"manifest","type":"composition","variant":"offset-diptych",
 "props":{"background":"surface","density":"airy"},
 "children":[
   {"type":"frame","frame":{"layout":"auto","direction":"row","gap":64,"align":"start"},
    "children":[
      {"type":"frame","frame":{"layout":"auto","direction":"column","gap":16,"width":420},
       "children":[{"type":"heading","level":2,"text":"…"},{"type":"text","text":"…"}]},
      {"type":"image","imagePrompt":"…","alt":"…"}]}]}
```

## Top-level sections

### `source-block`

Rendered Source Import section. It keeps a compact semantic DOM tree and carries `semantic` metadata (`role`, `label`, `selector`, optional repeat count/kind). Flex and grid containers compile to nested auto-layout frames; only real overlays, positioned elements, or a child explicitly detached by the user use absolute positioning. Stable `sourceKey` values connect desktop, tablet and mobile overrides without duplicating the tree.

### navbar

Use for site navigation.

Common props:

- `logoText`
- `links: [{label, href}]`
- `cta: {text, variant, href?, icon?}`
- `sticky`
- `transparent`

Variants:

- `classic`
- `centered`
- `split`

### hero

Use for the primary first screen.

Common props:

- `badge`
- `heading`
- `subheading`
- `ctaPrimary`
- `ctaSecondary`
- `media`
- `align`

Variants:

- `split` — текст слева, медиа справа; равные половины. Дефолт, а не «лучший выбор».
- `centered` — всё по центру. Только когда у продукта одно сообщение и нет медиа.
- `media-bg` — затемнённое медиа во всю ширину под текстом.
- `editorial-stack` — надзаголовок капслоком без плашки, display-заголовок во всю
  колонку, под линией полоса «лид слева + действие справа», медиа широкой полосой
  внизу. Для продуктов, где сильна формулировка, а не скриншот.
- `poster` — плита с рамкой на фоне `surface`: заголовок сверху, подпись и кнопки
  прижаты к низу плиты. Афиша: событие, выпуск, меню, коллекция.
- `split-offset` — узкая текстовая колонка и медиа, поднятое над базовой линией и
  уходящее за правый край. Асимметрия вместо двух ровных половин.
- `numbered` — тезис слева, справа пронумерованные строки из `children`
  (каждый ребёнок = один пункт). Нумерация обязана означать порядок, а не декор.

### feature-grid

Use for feature cards.

Common props:

- `heading`
- `subheading`

Children:

- `card`
- `heading`
- `text`

Variants:

- `grid-2` / `grid-3` / `grid-4` — равные карточки в ряд.
- `bento` — трёхколоночное бенто из карточек.
- `list-rail` — строки-рейка: крупный индекс `01/02/03` слева, содержимое справа,
  строки разделены линией, карточных плашек нет. Лучше всего с `frame`-детьми.
- `bento-asym` — шестиколоночная сетка с чередованием ширин 4/2 → 3/3 → 2/4,
  первая плитка выше остальных. Ряды заполняются без дыр.
- `two-col-manifest` — залипающий заголовок в левой колонке, тезисы сплошным
  текстом справа. Для принципов, гарантий, условий — не для фич-карточек.

### feature-alternating

Use for alternating image/text rows.

Variants:

- `2-rows`
- `image-left`
- `image-right`

### stats

Use for metrics.

Common props:

- `heading`
- `items: [{value, label}]`

Variants:

- `grid`
- `with-heading`

### gallery

Use for screenshots, work samples, visual grids.

Variants:

- `grid-uniform`
- `masonry`
- `carousel`

### logo-cloud

Use for client/platform logos.

Variants:

- `row`
- `grid`

### testimonials

Use for quotes/reviews.

Variants:

- `grid-2`
- `grid-3`
- `carousel`

### pricing

Use for pricing plans.

Common props:

- `heading`
- `subheading`
- `tiers`

Variants:

- `cards`
- `comparison`

### faq

Use for questions and answers.

Common props:

- `heading`
- `items: [{question, answer}]`

Variants:

- `accordion`
- `grid`

### steps

Use for “how it works”.

Variants:

- `horizontal`
- `vertical`

### team

Use for people/team sections.

Variants:

- `grid-4`
- `cards`

### newsletter

Use for email capture.

Common props:

- `heading`
- `subheading`
- `placeholder`
- `submitText`

Variants:

- `boxed`
- `inline`

### cta

Use for conversion sections.

Common props:

- `heading`
- `subheading`
- `ctaPrimary`
- `ctaSecondary`

Variants:

- `centered`
- `split`

### footer

Use for footer navigation.

Common props:

- `logoText`
- `tagline`
- `columns`
- `copyright`

Variants:

- `columns`
- `minimal`

## Child elements

Allowed child elements (the composition primitives):

- `frame` — контейнер: auto-layout (`layout:"auto"`) или свободный холст (`layout:"free"`).
  Своей рамки и фона не имеет, только геометрия и дети.
- `heading` (`level` 1–4), `text`, `button`, `image`, `divider`, `rect`
- `card` — плашка с фоном `surface`, рамкой и тенью. Это оформление, а не контейнер:
  для группировки без плашки берите `frame`.
- `badge`, `icon`, `avatar`, `rating`, `stat`, `list`, `input`
- `input`: `inputType` = `text` (default), `search`, `email`, `tel`, `url`, `password`,
  `number`, `textarea`, `select`, or `checkbox`; `placeholder`, `label`, `value`.
  For `select`, use `items` as an array of strings. Example search field:
  `{"type":"input","inputType":"search","placeholder":"Поиск объявлений"}`.

## Изображения

У каждого `image` обязателен `imagePrompt` с настоящей арт-дирекцией (предмет,
материал, свет, палитра, ракурс) — заглушка показывает именно его, а не `alt`.
Тон заглушки берётся из палитры страницы, поэтому пустая картинка читается как
часть макета. `src` модель не выдумывает: реальный файл подставляет пользователь.

## Token guidance

Always include useful tokens:

- `color.primary`
- `color.secondary`
- `color.accent`
- `color.background`
- `color.surface`
- `color.text`
- `color.textMuted`
- `color.border`
- `font.display`
- `font.body`
- `radius`
- `spacing`
- `shadow`

## Controlled generation rules

When reference IR or Style DNA is provided:

- preserve structure unless asked otherwise;
- preserve layout if lock/layout language is present;
- use tokens from Style DNA;
- avoid adding random sections;
- keep copy realistic and concise;
- return only valid JSON IR.

When asked to derive a related component:

- reuse visual rhythm;
- reuse typography scale;
- reuse radius and spacing logic;
- create the requested block type only;
- do not recreate the entire page unless asked.
