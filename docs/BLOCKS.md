# Каталог блоков Design IR v1.0

Закрытая библиотека секций. Модель **выбирает type + variant и заполняет props**, не изобретая новых блоков. Это главный механизм консистентности.

Легенда вариантов: вариант определяет раскладку, токены — стиль.

## Навигация
| type | variants | props (обязательные) |
|---|---|---|
| `navbar` | `classic` (лого слева), `centered` (лого по центру), `minimal` (без cta) | logoText, links[], cta, sticky, transparent |

## Hero
| type | variants | props |
|---|---|---|
| `hero` | `centered`, `split` (текст+медиа), `split-reverse`, `media-bg` (фон-картинка), `gradient` | heading, subheading, ctaPrimary, ctaSecondary, media, badge, align |

## Социальное доказательство
| type | variants | props |
|---|---|---|
| `logo-cloud` | `row`, `grid`, `marquee` | heading, children: image/heading элементы |
| `testimonials` | `grid-2`, `grid-3`, `carousel`, `single-featured` | children: card (avatar + rating + text + name/role) |
| `stats` | `row`, `grid`, `with-heading` | heading, items[{value,label}] |

## Контент
| type | variants | props |
|---|---|---|
| `feature-grid` | `grid-2`, `grid-3`, `grid-4`, `bento` | heading, subheading, children: card(icon, title, text) |
| `feature-alternating` | `2-rows`, `3-rows` | children: чередующиеся image + heading/text/button |
| `steps` | `horizontal`, `vertical`, `numbered` | heading, children: card (шаги) |
| `gallery` | `masonry`, `grid-uniform`, `carousel` | children: image |
| `team` | `grid-3`, `grid-4`, `list` | heading, children: card(avatar, name, role) |
| `blog-grid` | `grid-3`, `featured+list` | heading, children: card(image, badge, title, text) |

## Коммерция
| type | variants | props |
|---|---|---|
| `pricing` | `cards`, `table`, `toggle-monthly-yearly` | heading, tiers[{name, price, features[], cta, highlighted}] |
| `comparison` | `table`, `vs` | children: list / rows |
| `cta` | `centered`, `split`, `banner-bold` | heading, subheading, ctaPrimary, ctaSecondary |
| `banner` | `info`, `promo`, `cookie` | text, cta |

## Вовлечение
| type | variants | props |
|---|---|---|
| `faq` | `accordion`, `two-column`, `with-sidebar` | heading, items[{question, answer}] |
| `contact-form` | `centered`, `split-info` (форма+контакты), `map` | heading, fields[{label, inputType, placeholder, required}], submitText |
| `newsletter` | `inline`, `boxed`, `minimal` | heading, subheading, placeholder, submitText |

## Подвал
| type | variants | props |
|---|---|---|
| `footer` | `simple` (1 строка), `columns`, `mega` (колонки + подпись + соцсети) | logoText, tagline, columns[{title, links[]}], copyright |

## Элементы (children внутри секций)
`heading` (level 1–4, size), `text` (size, align), `button` (variant: primary/secondary/outline/ghost, icon), `image` (src или imagePrompt, aspect), `badge` (tone), `card` (icon, title, text, children), `icon` (lucide name), `divider`, `avatar` (name, role), `rating` (value 0–5), `input`, `stat` (value, label), `list` (items[])

## Правила композиции страницы (для генератора)
1. Страница начинается с `navbar`, заканчивается `footer`.
2. После navbar — `hero`. Ровно один.
3. Типичный порядок лендинга: navbar → hero → logo-cloud → feature-grid → feature-alternating → testimonials → pricing → faq → cta → footer.
4. 7–12 секций на страницу; не повторять один type подряд.
5. Все цвета/шрифты/радиусы — только из `tokens`, никаких произвольных значений в props.
6. Тексты — на языке брифа, реалистичные (не lorem ipsum), heading ≤ 12 слов.

## Геометрия: `frame` (модель Figma)

Каждый узел (корень IR, секция, элемент) может иметь опциональный объект `frame`. **Нет frame — узел в потоке** с раскладкой по умолчанию (поведение до появления геометрии). Добавляй frame, только когда бриф требует явных размеров/позиций (отдельный компонент: карточка, шапка, модалка) или когда нужно зафиксировать раскладку точнее, чем variant.

```json
"frame": {
  "width": 360,                 // число (px) | "fill" (растянуть до родителя) | "hug" (по содержимому)
  "height": "hug",
  "x": 24, "y": 16,             // позиция внутри родителя — работают ТОЛЬКО при layout:"free" у родителя
  "layout": "auto",             // "auto" (children в потоке, flex) | "free" (children по x/y, абсолютно)
  "direction": "column",        // ось auto-layout: "row" | "column"
  "gap": 12,                    // px между children
  "padding": [16, 24, 16, 24],  // px: число или [top, right, bottom, left]
  "justify": "start",           // по главной оси: start | center | end | space-between | space-around
  "align": "stretch",           // по поперечной: start | center | end | stretch | baseline
  "wrap": false                 // перенос children (для direction:"row")
}
```

Правила:
1. **Корневой `frame`** — артборд: `width` = ширина холста (1440 — десктоп, 960 — превью, 390 — мобильный), `height` обычно `"hug"`. Не задавай — рендерер возьмёт 960.
2. Секции внутри страницы почти всегда `width: "fill"` (или без frame). Фиксированная ширина секции — исключение.
3. `x`/`y` имеют смысл только у детей родителя с `layout: "free"`; в потоке они игнорируются. Не смешивай: free-родитель — координаты у всех детей, auto-родитель — координат нет.
4. `layout: "free"` требует от родителя явной высоты (`height` числом), иначе контейнер схлопнется.
5. Числа — целые px, без единиц и строк. Отрицательные x/y допустимы (элемент вылезает за край родителя).
6. Геометрия не отменяет токены: цвета/шрифты/радиусы по-прежнему только из `tokens`.
