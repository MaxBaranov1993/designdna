# SLSBMB: карточка товара из Source Import в DNA Editor

## Итог

- Источник захвата: **live full-page plus live selective Pricing retry** (`https://slsbmb.com`).
- Полный Source Import: job `complete`, **9** блоков, **7** ошибок (`cta, cta-2, section, gallery, section-2, pricing, footer`).
- Селективный Pricing-import: без ошибок восстановлено **4** из 7 атомов (`pricing-scan-eyebrow, pricing-scan-title, pricing-scan-copy, pricing-scan-price`); ожидание 900 с, заданный бюджет maxRegions=3 (repair неприменим без валидного IR).
- Design System: `ds-98d49b55acd6`; опубликована ревизия **v7**.
- Компонент: **AI Market Scan** (`product-card`, origin `user`, status `verified`, confirmed `True`).
- Физических observed-мастеров в итоговом реестре: **0**; целевой тариф сохранён через предусмотренный fallback как `user-fallback`.
- Fidelity: status `verified`, AI review `не требовался`.
- Вариант: **Со скидкой** (`user-1`, origin `user`) сохранён через кнопку `data-act=save-ds-variant`.
- Панель «Компоненты» вставила секцию с совпадающим `sourceMeta.componentRef.componentKey`.

## Редактор и артефакты

Мастер и вариант реально открыты в DNA Editor; сняты полные скриншоты редактора и отдельные PNG через `app/ir_render.py`.

- `artifacts/slsbmb/design-system.json` — draft после сохранения пользовательского варианта.
- `artifacts/slsbmb/product-card.master.json` / `.png` — мастер.
- `artifacts/slsbmb/product-card.variant.json` / `.png` — вариант со скидкой.
- `artifacts/slsbmb/editor.master.png` / `editor.variant.png` — состояния DNA Editor.

## AI review и судья

Master-review: `verified user-master не требовал AI repair`.
Quality Pass: score `84`, verdict `needs_repair`, passed `False`.
Замечания судьи: `[{"category": "hierarchy", "severity": "major", "path": "tree[0].children[0].children[5]", "problem": "Основной CTA имеет ширину около 263 px вместо заданных 700 px, поэтому выглядит второстепенным и не продолжает общую ширину блока преимуществ.", "instruction": "Растянуть кнопку до ширины контейнера контента — 700 px при текущем размере карточки — сохранив высоту 54 px и выравнивание текста по центру."}, {"category": "rhythm", "severity": "minor", "path": "tree[0].children[0].children[5]", "problem": "После полноширинного блока преимуществ резко появляется короткий элемент, из-за чего левый край композиции перегружен, а справа образуется необоснованный провал.", "instruction": "Сделать CTA полноширинным; остальные вертикальные интервалы оставить без изменений."}]`.

## Причина ошибок и fallback

- Все 7 ошибочных полноразмерных блоков завершаются одинаково: `meta/fontFaces ... is too long`. Capture создаёт 16 записей fontFaces, а `schema/design-ir.schema.json` допускает максимум 12; ошибка возникает на `_validate(ir)` до fidelity, поэтому увеличение LLM timeout или maxRegions её не исправляет.
- Провайдер сервера — Codex CLI (`LLM_CLI_PROVIDER=codex`); full-page job завершился, provider-timeout не наблюдался.
- Desktop fallback `%APPDATA%/@designdna/desktop/data/projects.db` проверен: сохранённая slsbmb sourceimport-нода содержит те же 9 блоков и те же 7 ошибок, поэтому её IR не использован как ложный observed-мастер.
- Безошибочный атом цены из Pricing и measured tokens использованы как evidence; полноценная карточка собрана в редакторе и сохранена как user component согласно fallback-контракту задания.

## Найденные дефекты приложения

- Selective Pricing retry recovered 4/7 observed atoms with one desktop viewport; maxRegions=3.
- No physical observed pricing-card boundary survived Source Import; saved a confirmed verified user product-card from observed Pricing atoms and DS tokens.

## Продуктовый смысл

Сценарий закрывает разрыв конкурентов между импортом реального сайта и повторным использованием: один и тот же проверяемый мастер доступен как редактируемый DNA-компонент, пользовательский вариант и вставляемая strict-ссылка, а не как одноразовая картинка.
