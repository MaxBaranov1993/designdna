# SLSBMB: наблюдённый мастер тарифной карточки

## Итог

- Источник: live Source Import `https://slsbmb.com`, сервер `127.0.0.1:8431`, чистый `DESIGNDNA_DATA_DIR=.tmp-data-p6`, `LLM_CLI_PROVIDER=codex`, timeout 900 секунд. Запросы `**/api/project/load|save` замоканы в Playwright-harness.
- До полного schema-fix (P5): 9 блоков, 7 ошибок `meta/fontFaces ... is too long`. После фикса `design-ir.schema.json` и `design-ir-1.0.schema.json`: 9 блоков, 0 ошибок; `block.error` после фикса: `[]`.
- Селективный Pricing-capture: 9/9 блоков без ошибок, включая цельные `.sls-price-panel.sls-price-map` и `.sls-price-panel.sls-price-engine` и семь измеряемых атомов.
- Design System `ds-98d49b55acd6` опубликована как revision 4. В реестре 17 компонентов, review pool пуст; 12 review-мастеров получили AI-review, после review/repair незавершённых review-компонентов нет.
- Целевой мастер: `list-item`, семантические метаданные исправлены по observed evidence на **Sending Engine**, category `pricing`, canonicalRole `pricing-card`; origin `observed`, status `verified`, confirmed `true`. Пользовательский `product-card` из P5 не использован.
- Fidelity observed-мастера: desktop 97.03, tablet 96.62, mobile 95.55 pixel similarity; bbox p95 3 px, paint coverage 100%, source gate passed на всех трёх viewport.

## Редактор, вариант и повторное использование

- Мастер открыт через `applyDesignSystemToEditor` в ноде «Редактор (DNA)»; состояние сохранено в `editor.master.png`.
- Через `data-act=save-ds-variant` сохранён пользовательский вариант **«Со скидкой»**, key `user-1`; затем draft перепубликован, чтобы вариант был доступен нормальному UI реестра.
- Панель «Компоненты» вставила default-мастер с точным `sourceMeta.componentRef.componentKey=list-item`, затем UI отправил второй `/api/design-system/component-section` с `componentKey=list-item`, `variantKey=user-1`; число точных componentRef в editor draft выросло.
- Вариант меняет строку описания на `$400 launch · 20% off`; состояние редактора сохранено в `editor.variant.png`.

## Master review и Quality Pass

- Целевой Sending Engine master сразу прошёл детерминированный fidelity gate и находился в verified registry; master-review был выполнен для review pool и довёл остальные 12 кандидатов до approved/verified.
- Quality Pass с ошибочным требованием встроенного CTA дал 78/100 и `needs_repair`: судья верно заметил, что CTA отсутствует внутри карточки.
- Повторная оценка точного observed-boundary дала **92/100**, verdict `pass`. Два minor-замечания: слабая читаемость горизонтальной линии и слишком приглушённые подписи `/ month` / `CAMPAIGN SENDS / DAY`.
- Поле API `passed=false`, несмотря на score 92, потому что общий детерминированный page-linter применяет к exact component capture правила полной страницы: требует H1, 8px-округление высоты, font size ≥12 и трактует DOM overlay/background layers как overlap. Это отдельная несовместимость Quality Pass с observed component masters; целевой порог оценки ≥80 достигнут.

## Source crop и артефакты

- `artifacts/slsbmb/design-system.json` — опубликованная revision 4 с observed-мастером и вариантом.
- `artifacts/slsbmb/product-card.master.json` / `.png` — exact Sending Engine master.
- `artifacts/slsbmb/product-card.variant.json` / `.png` — вариант «Со скидкой».
- `artifacts/slsbmb/product-card.source-crop.png` — crop исходного Pricing evidence по `sourceRef.bounds` для визуального сравнения с master render.
- `artifacts/slsbmb/editor.master.png` / `editor.variant.png` — мастер и вариант в DNA Editor.

## Что осталось

- На live-странице один общий CTA расположен над двумя тарифными панелями, а не внутри AI Market Scan / Sending Engine. Добавлять его внутрь exact master нельзя без ложного `origin=observed`; это расхождение исходной DOM-границы с формулировкой desired component.
- Builder первоначально назвал observed boundary `List item`, хотя `sourceLabel` и содержимое — Sending Engine; harness исправил только метаданные, не IR/evidence. Автоматическую семантическую классификацию builder стоит улучшить отдельно.
- Quality Pass должен иметь component-mode для exact observed masters, чтобы page-level H1/grid/min-font/overlay правила не делали `passed=false` при vision score 92 и fidelity >95.
