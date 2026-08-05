# Триаж мульти-ревью от 2026-08-05 (product lead: Qwen)

Источник: `app/review_pipeline.py` (qwencloud-only, решение владельца №7), диапазон
`HEAD~2..HEAD` на момент b30bada (коммит fbc154c «Триаж мульти-ревью» — последний коммит
оркестрации Kimi). Ревьюверы: **qwen3.8-max** (21 замечание: 2 critical, 11 major) и
**qwen3.7-max** (12 замечаний: 2 critical, 6 major). Полный JSON — `results/review_sprint4.json`
в worktree `review-qwen-only` (ветка `review-qwen-only`).

## Подтверждено обоими ревьюверами (высокая уверенность) → в работу воркеру W5

1. **geoedit.js, groupSelection(): TypeError на `r.path.split('.')` при `r.path === null`**
   (корневые секции). Guard до измерения DOM: либо отказ группировки верхнего уровня,
   либо индекс из `r.secIdx`. *(critical ×2)*
2. **geoedit.js, groupSelection(): расхождение порядка** — `meas[k]` по отсортированным
   индексам, но splice выбранных узлов идёт в обратном порядке; при не-непрерывном
   выделении координаты и удалённые узлы расходятся. Строить taken/meas из одного
   отсортированного списка выбранных узлов. *(critical + косвенно major)*
3. **cache_store.py: молчаливое проглатывание sqlite3.Error** — ALTER TABLE (миграция
   `hits`) и UPDATE hits в `pass`; добавить логирование на stderr, явный commit,
   json.loads повреждённого payload → cache miss. *(major ×3)*
4. **llm_client.py: валидация model slug** — разрешить только безопасные slug: запрет
   ведущих/концевых `/` и сегментов `..`, проверка по всем путям (не только явный model).
   *(major + minor)*
5. **review_pipeline.py: безопасность git-диапазона** — `--` перед ревизиями в вызове
   `git diff` (subprocess list, без shell — инъекции нет, но возможен разбор аргумента
   как флага git), верификация концов диапазона через `git rev-parse --verify`.
   *(critical у 3.7 частично ложный — shell-инъекции без shell нет; укрепление всё равно делаем)*
6. **editor.js: cleanup `.drop-target`** — на dragend/drop снимать класс со всех элементов
   панели слоёв (document-level query), не только с перетаскиваемого. *(major + minor ×2)*

## Только один ревьювер — взять в W5 с проверкой по коду

7. **geoedit.js, moveSibling()**: возможен TypeError при `ref.path === null`; проверить
   off-by-one финального индекса после remove+insert (`idx < newIndex ? newIndex - 1 : newIndex`)
   и ремоппинг путей мультивыделения после reorder.
8. **geoedit.js, ungroupSelection()**: проверка `!node.frame || node.frame.layout !== 'free'`;
   валидация конечных чисел в `frame.x/y/width/height` детей до применения смещений
   (строки из внешнего IR → NaN).
9. **geoedit.js, groupSelection()/ungroupSelection()**: после структурных мутаций —
   инвалидация кэша hit-targets / полный re-render.
10. **geoedit.js, groupSelection()**: `siblingDom()` вернул null → `onCommit()` уже вызван
    выше; перенести onCommit после всех DOM-проверок (консистентность undo-стека).
11. **review_pipeline.py: обрезка diff** — граница по `rfind('\ndiff --git')` может резать
    хвост; парсить границы файлов полностью. (dev-тул, minor-приоритет.)

## Отклонено / принято как есть

- «Command injection» в review_pipeline (3.7-max, critical) — ложная формулировка:
  subprocess list без shell; укрепление по п. 5 делаем, критичность снижена.
- Прочие minor (округления координат, префиксы путей selectMulti) — в W5 по остаточному
  принципу, если не раздувают дифф.

## Оркестрационные выводы

- qwen3.7-max на ревью-промпте медленный (~8–10 мин/вызов, thinking-режим) — таймауты
  оркестрации закладывать ≥ 12 мин на прогон пайплайна.
- Token-plan эндпоинт (Bailian): доступны qwen3.8-max, qwen3.8-max-preview, qwen3.7-max,
  qwen3.7-plus, qwen3.6-flash, **glm-5.2**, deepseek-v4-*; qwen3-max/qwen-plus/qwen-max — 404.
- Порядок работ: W5 стартует после W4 (общий порт 8420 у Playwright-проверок).
