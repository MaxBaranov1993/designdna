# План работ: редактор закрывает минусы конкурентов, генератор работает от дизайн-системы

Дата: 2026-09-04. Основание: `docs/COMPETITOR-ANALYSIS-AI-DESIGN-TOOLS.md` (разбор видео «Figma больше не нужна? Тест Pencil, Paper, Open Design и Claude Code»). Ветка: `codex/unified-motion-design`.

## 0. Что показало исследование кода (факты до правок)

Генератор (`frontend/src/nodes/GeneratorNode.svelte`, `frontend/src/flow/store.ts` `runGenerator`, `app/server.py` `_generate`):
- Портов ДС и референсов нет. ДС приходит «из воздуха» через глобальный пикер (`pinnedDesignSystemRef`), нода может только выключить ДС крестиком; режим использования (strict / extend / style-only) на ноде не выбирается.
- Блок «Режим встраивания» в промпте — захардкоженная строка, одинаковая для всех режимов.
- Внешней загрузки ДС нет: единственный вход — `POST /api/design-system/build` из блоков Source Import (и сырой `save-draft`). Экспорт токенов в формат Figma есть (`styleguide.figma_tokens`), импорта нет.
- Арт-дирекция (`art_direction.create_design_brief`) и эталоны (`load_exemplars`) не вызываются из `_generate`; чипы направлений на ноде живут только на мок-ответе теста.
- После генерации: `sanitize_generated_ir` → лок токенов → `qualitygate.autofix` → `apply_ir_tokens` → `validate_generation` ДС (в strict — отказ и материализация точного мастера).

Редактор (`frontend/src/editor/*`, `app/editor_assist.py`, `app/qualitygate.py`):
- Текстовые стили: у элемента нет поля роли. Роли типографики токенов v2 (`display … eyebrow`) применяются только по тегу (`h1–h4`, `p`), а инлайновые `style.fontSize/fontWeight/lineHeight` их перекрывают. Классы `.t-display/.t-lead/.t-small/.t-eyebrow` объявлены в CSS, но не эмитятся.
- Варианты компонентов: в документе ДС есть `variants`, но из редактора вариант не создать; вставить компонент ДС в текущую страницу нельзя (мастер открывается как отдельная нода Edit).
- Консистентность: Quality Gate знает контраст, сетку 8, overflow, tap-target, но не знает «цвет не из токенов», «шрифт не из ДС», «line-height/кегль не по роли» — ровно тот дрейф, что автор видео показал на Pencil.
- Прозрачность: `DESIGN.md`, `RUBRIC.md`, `BLOCKS.md` не видны и не редактируются из приложения; журнала решений у генерации нет.
- Сильные стороны, которые остаются: единая поверхность редактирования, AI-правки с областью (single / selection / document), интент-локи, undo по снимкам, CAS-сохранение.

## 1. Карта «минус конкурента → что делаем»

| Минус из видео | Инструмент | Что делаем | Где |
|---|---|---|---|
| Нет текстовых стилей, токены в каждое поле отдельно | Pencil | Роль типографики `typeRole` на текстовом элементе: рендер по роли, инлайн-кегль не перекрывает, выбор роли в инспекторе, правка роли меняет все элементы | схема, `renderer.ts`, `TypeGroups.svelte`, `wireInspector.ts`, `qualitygate` |
| Варианты = новые компоненты, ДС раздувается | Pencil | «Сохранить как вариант» из редактора для мастера ДС; варианты в реестре, не новые компоненты | `design_system/api.py`, `controller.ts`, `TopBar.svelte` |
| Дрейф line-height/весов, забывает экраны | Pencil, Open Design | DS-lint как правила Quality Gate с автопочинкой: `token-color`, `token-font`, `type-role-drift`; отчёт линта в ноде Генератора | `qualitygate.py`, `_generate` |
| Чёрный ящик: скиллы не видны, правил не задать | Pencil | Панель «Правила» в редакторе: показ `DESIGN.md`/`RUBRIC.md`, редактируемые правила проекта, применяемые генератором и судьёй; журнал решений генерации | `app/rules.py`, `RulesPanel.svelte`, `_generate` |
| Библиотеку искать на диске каждый запуск, свой стиль не загрузить | Pencil | Импорт ДС файлом (документ DesignDNA, W3C/Tokens Studio tokens JSON, shadcn-карта) в ноду ДС; ДС живёт в проекте | `design_system/importer.py`, `api.py`, `DesignSystemNode.svelte` |
| Нельзя править руками, только чат | Open Design | Уже есть; добавляем вставку компонента ДС в текущую страницу из редактора | `controller.ts`, `ComponentsPanel.svelte` |
| Нет внутреннего чата | Paper | Уже есть (AI-инспектор с областью) | — |
| MCP «как руки», агент не видит ДС | Pencil, Paper | Генератор берёт ДС по проводу (порт `designSystem`), режим на ноде, референсные экраны портом `reference`; журнал решений отдаётся наружу | `ports.ts`, `dataflow.ts`, `GeneratorNode.svelte`, `store.ts`, `server.py` |
| Сложно поднять среду | Figma + Claude | Из коробки: ДС из Source или из файла → провод в Генератор → strict | — |

## 2. Этапы

### Этап A. DS-lint в Quality Gate (бэкенд)
- `app/qualitygate.py`: правила `token-color` (цвета элементов только из `tokens.color` / `tokens.v2.color`, fix — ближайший токен по ΔE в oklab), `token-font` (семейства только из `tokens.font` / `v2.type.families`, fix — display для заголовков, body для остального), `type-role-drift` (кегль/line-height/вес текстового элемента с `typeRole` или заголовка по уровню отличаются от роли, fix — снять инлайн-переопределения). Правила пропускают `source-block`/`dom-capture` секции (точные копии источника) и узлы с `editable:false`.
- Тесты `app/qualitygate_ds_lint_test.py`.

### Этап B. Роли типографики (текстовые стили)
- `schema/design-ir.schema.json`: `typeRole` (enum ролей) у элементов `heading`/`text`.
- `frontend/src/engine/renderer.ts`: при `typeRole` эмитить класс `t-<role>` и не эмитить инлайн `fontSize/lineHeight/letterSpacing/fontWeight`; CSS для `.t-h1…` по переменным ролей.
- Инспектор: селект роли для текстовых элементов (`TypeGroups.svelte` + `wireInspector.ts`), кнопка «Применить роль ко всем таким».
- Миграция: `ensure_tokens_v2` не трогает; правило `type-role-drift` подсказывает роль.

### Этап C. Генератор от ДС
- Новый вид порта `ds`: `PortKind`, цвета в `portKind.ts` и `dataflow.ts`; у ноды ДС выход `system`, у Генератора вход `designSystem`.
- Вход `reference` (kind `ir`): существующие экраны как контекст «сделай так же».
- `GeneratorNode.svelte`: источник ДС (провод / проект), селект режима strict / extend / style-only, панель «Журнал» (ДС, режим, мастера в контексте, линт, судья).
- `store.ts` `runGenerator`: ref с провода приоритетнее глобального; требование опубликованной ДС с понятной ошибкой; `usageMode` и `referenceIrs` в запросе.
- `server.py`: `GenerateReq.referenceIrs`, `usageMode`; блок «Режим встраивания» зависит от режима; дайджест референсов в промпт; правила проекта в системный промпт; `generationLog` в ответе; DS-lint в ответе (`dsLint`).

### Этап D. Импорт ДС файлом
- `app/design_system/importer.py`: распознавание формата (документ DesignDNA / tokens JSON W3C-Tokens Studio / shadcn-карта) → черновик документа с `foundations`, `styleGuide` (через `ensure_style_guide`), мастера из документа при наличии.
- `POST /api/design-system/import`; `DesignSystemNode.svelte`: кнопка «Загрузить ДС», создание ноды без Source.
- Тесты `app/design_system_import_test.py`.

### Этап E. Правила и журнал
- `app/rules.py`: чтение встроенных `DESIGN.md`/`RUBRIC.md`/`BLOCKS.md`, правила проекта в `data/rules/project.md`; `GET /api/rules`, `PUT /api/rules/project`.
- Генератор и судья подмешивают правила проекта.
- Редактор: `RulesPanel.svelte` (слайд-овер, как DnaPanel), кнопка в TopBar, регистрация в `actionInventory.ts`.

### Этап F. Варианты и вставка компонентов из редактора
- `POST /api/design-system/variant/save`: сохраняет IR текущей ноды Edit как вариант компонента (`origin: user`, `masterRef` отдельный), не создавая нового компонента.
- Редактор: кнопка «Сохранить как вариант» (видна, если у ноды есть `_dsMaster`); панель «Компоненты» со списком мастеров закреплённой ДС и вставкой секции с `componentRef` в текущую страницу.

### Этап G. Проверка
- `pytest -q app`, `npm --prefix frontend run check`, `node frontend/tests/engine.regression.test.mjs`, точечные Playwright-смоки (`app/ui_editor_action_inventory_test.py`, `app/ui_design_system_test.py`, `app/ui_generator_directions_test.py`).

## 3. Вне этого прохода (отдельные задачи)
- Подключение арт-дирекции и эталонов в `_generate` (сейчас мёртвый код) — T3-зона Design Studio v3.
- Мобильные артборды и нода Flow с реестром экранов (E3 из ТЗ).
- Высокоуровневые MCP-инструменты `generate_screens`/`review` (E1 из ТЗ) — после стабилизации API генератора из этого плана.
- Мост Figma (импорт компонентов через REST/MCP, экспорт) — E6.

## 4. Статус (2026-09-04, первый проход)

| Этап | Статус | Что сделано | Проверка |
|---|---|---|---|
| A. DS-lint | сделано | `qualitygate.py`: правила `token-color` (снап к ближайшему токену по ΔE oklab, alpha сохраняется, в strict — всегда), `token-font` (снятие чужого семейства), `type-role-drift` (явная `typeRole` — источник правды, заголовки без роли только репортятся); severity `warning` не роняет gate (`qualitygate.passed`); `QualityGateReq.strictTokens`; генератор зовёт autofix со strict при ДС strict | `app/qualitygate_ds_lint_test.py` (8 тестов) |
| B. Текстовые стили | сделано | `typeRole` в схеме элемента; рендерер эмитит `t-<role>` и снимает инлайн кегль/вес/интерлиньяж/разрядку; CSS ролей на любом теге + мобильные; инспектор: селект «Стиль» и «Всем таким»; AI-правки в редакторе могут ставить `typeRole` | `frontend/tests/engine.regression.test.mjs` (typeRole), `svelte-check`, инвентарь редактора |
| C. Генератор от ДС | сделано | порт `designSystem` (kind `ds`, выход `system` у ноды ДС) и порт `reference`; режим strict/extend/style-only на ноде; «Режим встраивания» по режиму; дайджест референс-экранов и правило `typeRole` в промпте; `generationLog` + DS-lint в ответе и панель «Журнал решений» на ноде; неопубликованная ДС по проводу — понятная ошибка | `app/generation_provider_test.py`, `app/design_system_test.py`, `ui_generator_directions_test.py` |
| D. Импорт ДС | сделано | `design_system/importer.py` (документ DesignDNA, W3C / Tokens Studio с алиасами, shadcn-карта, IR tokens v1) → черновик с foundations/styleGuide/irTokens; `POST /api/design-system/import`; кнопка «Загрузить JSON» на ноде ДС | `app/design_system_import_test.py` |
| E. Правила и журнал | сделано | `app/rules.py`, `GET /api/rules`, `POST /api/rules/project`; правила проекта уходят в промпт генерации и в рубрику судьи; панель «Правила» в редакторе (встроенные — чтение, проектные — редактирование) | `ui_editor_action_inventory_test.py` |
| F. Варианты и вставка | сделано | `POST /api/design-system/variant/save` (вариант `origin: user` в черновик, не новый компонент), кнопка «Вариант в ДС» в тулбаре редактора для ноды с `_dsMaster`; `POST /api/design-system/component-section` + панель «Компоненты» — вставка мастера секцией с `componentRef` | `app/design_system_import_test.py` |
| G. Проверка | сделано | pytest `app`: 559 passed; `npm run build` (svelte-check 0 ошибок); engine regression 26/26; UI-смоки: инвентарь редактора, направления генератора, граф/ноды/редактор — зелёные | — |

Известное: `app/ui_design_system_test.py` падает на шаге «semantic suggestion can be explicitly promoted» (кнопка «Включить в UI Kit» отключена fidelity-гейтом). Тест датирован 2026-09-02, панель ДС менялась 09-03 и 09-04 (AI-ревью мастеров, панель без проверочной обвязки); шаг не связан с правками этого прохода, теста нет в курируемом списке `ui_smoke.py`. Нужна отдельная актуализация теста под новую панель.

Осталось после первого прохода:
- Промпт `DESIGN.md` не упоминает `typeRole` явно (правило подмешивается в user-промпт генератора строкой `_TYPE_ROLE_RULE`); эталоны в `app/exemplars/` пока без `typeRole` — при обновлении эталонов проставить роли.
- Вариант, сохранённый из редактора, попадает в черновик: чтобы генератор его увидел, ДС нужно опубликовать (кнопка Publish в панели ДС). Компилятор ДС кладёт в промпт мастера; пользовательские варианты попадают через `registry.components`, отдельная выдача вариантов в промпт — следующий шаг.
- Панель «Компоненты» вставляет мастер последней секцией; вставка в позицию выделения и drag из панели — следующий шаг.

## 5. Второй проход: Orca-оркестрация с Codex-воркерами (2026-09-04, run_9cd1a3023739)

Скрипт запуска: `tools/orca/ds-editor-run.ps1` (координатор — терминал основного воркtree, воркеры — Codex gpt-5.6-sol medium в дочерних воркtree `dse-p*`).

| Задача | Что сделано | Коммит | Статус |
|---|---|---|---|
| P4 MCP со скиллами | `designdna_generate`, `designdna_list_design_systems`, `designdna_review`, `designdna_rules_get/set`; `skills/designdna/SKILL.md`, `docs/MCP.md`; 34 теста | 6f3fedc | слит |
| P3 Арт-дирекция в генерации | стадия `art-direction` в `_generate`, `selectedDirection`, 2–3 эталона в системный промпт, `directions`/`variantDirections`/`generationLog.direction`, деградация без арт-дирекции | e096831 (merge 0dc2767), фикс теста f1e0d8a | слит |
| P2 Остаток плана | `typeRole` в DESIGN.md и во всех эталонах; варианты компонентов в компиляторе ДС и exact-copy validation по хэшу варианта (`component-section` отдаёт хэш варианта); вставка компонента после выделенной секции; `ui_design_system_test.py` актуализирован; новые `design_system_remaining_test.py`, `ui_editor_components_panel_test.py`; `summary` считает пользовательские варианты | 9de8658 (merge c90d034) | слит |
| P1 Карточка товара slsbmb | `tools/slsbmb_product_card.py`, артефакты `artifacts/slsbmb/*`, отчёт `results/slsbmb-product-card.md`. Первый прогон: 0 наблюдённых мастеров (7 из 9 блоков с ошибками), мок `category-tile`, судья 18/100; воркер завис, скрипт зафиксирован координатором | f4704cb | закрыт |
| P5 Карточка тарифа slsbmb | найдена причина ошибок: захват отдаёт 16 `meta.fontFaces` при лимите схемы 12; пользовательский компонент `product-card` «AI Market Scan» + вариант, Quality Pass 84 | 58e8150 (merge 7c9f391) | слит |
| Фикс схемы | `meta.fontFaces` maxItems 12 → 48 в `design-ir.schema.json` и `design-ir-1.0.schema.json` (захват пишет version 1.0), константа `scraper.MAX_FONT_FACES`, тест `app/schema_font_faces_test.py` | a95d035, c82f2a9 | слит |
| P6 Наблюдённый мастер | после фикса 9/9 блоков без ошибок; observed/verified мастер «Sending Engine» (fidelity 95.55–97.03), вариант «Со скидкой» вставлен через панель «Компоненты», Quality Pass 92; кит загружен в реестр приложения как «SLSBMB Pricing Kit» | fb2135d | слит |
| P8 Strict ДС без ложных отказов | релевантность мастеров по содержимому, пиннутый мастер из «Референса» первым в контекст, fallback в extend вместо 422; плюс координатор: мастер, не влезающий в бюджет промпта (≈45k токенов у «Sending Engine»), материализуется точной копией без вызова модели и в prepareOnly (десктоп), поддерево с `componentRef` не проверяется на «чужие» цвета, положение `frame.x/y` не входит в хэш формы | 3f842ed + фикс координатора | слит |
| P7 Входы Генератора, подсветка, автопубликация | три входа вместо пяти: «Промт» (text), «Дизайн-система» (ds + tokens), «Референс» (ir + text); порты с несколькими видами (`PortDecl.kinds`), миграция рёбер старых графов (tokens→designSystem, style→reference); при перетаскивании провода совместимые входы подсвечиваются (`port-can-drop`), несовместимые гаснут; автопубликация ДС при запуске генерации, после сборки из Source и импорта JSON (тумблер на ноде ДС); новый `ui_ports_highlight_test.py` | 99ceee4 | слит |

| P9 Готовые мастера в UI Kit | при сборке кита из Source каждый мастер прогоняется через полировку (`design_system/polish.py`): headless-линт (обрезанный/наложенный текст, переполнение), автопочинка ширин фреймов, при остатке — AI-доводка `master_repair` restore-layout; приёмка по fidelity ≥ 85 %; статусы `fidelity.polish` и бейджи в панели ДС, endpoint `polish`/`rollback`; Quality Pass в режиме «компонент» для секций с `componentRef` | e2d129d (merge a14af7b) | слит, доработка в P10 |
| P10 Полировка без регрессий | проблема P9: расширение фрейма «$3K» сдвинуло соседей за родителя — футер «We accept · Card · Bank wire · Crypto» обрезался, кандидат всё равно принят (критерий «дефектов меньше + fidelity ≥ 85»). Делается: линт `escape` (узел вне родителя) и `wrap`, дедупликация и игнор скрытых клонов вьюпортов, сдвиг соседей только внутри родителя (иначе — gap/пустота или «нужна доводка»), приёмка «дефекты после ⊆ до, ни одного escape, similarity ≥ before − 1.5 п.п.» с полным откатом, прогон на реальном ките slsbmb | task_03f1137ebfcb | в работе |

Проверка слитого кода (после P7): pytest `app` 583 passed; после P9 (a14af7b) — 595 passed, `test_chess_arena_golden` падал только под параллельной нагрузкой и проходит отдельно; `npm run build` 0 ошибок; UI-смоки на временном сервере 8441 (ports_highlight, flow_graph, flow_nodes, generator_directions, design_system, editor_action_inventory, editor_components_panel, flow_edit, edit) — зелёные. `ui_style_dna_flow_test.py` устарел (создаёт удалённую ноду `styledna`), в курируемый список не входит. Кит slsbmb опубликован в реестр десктопа (`%APPDATA%\@designdna\desktop\data`), веб-сервер по просьбе пользователя не используется.
