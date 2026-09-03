# Orca-оркестрация DesignDNA

Координатор — Claude Fable 5.1 (этот терминал, воркtree `C:/Users/iamma/Documents/desingaiweb`). Воркеры — отдельные Orca-воркtree от базовой ветки, каждый со своим агентом. Скрипт: `tools/orca/design-studio-run.ps1`.

## Роли и модели

| Роль | Агент Orca | Модель / усилие | Для чего |
|---|---|---|---|
| Оркестратор | текущий терминал (Claude Code) | Fable 5.1 | план, задачи-DAG, приёмка, слияние |
| Реализация бэкенда | `codex` | `gpt-5.6-sol`, effort `medium` | Python-пайплайн, схемы, судья |
| Реализация фронта/архитектуры | `claude` | `opus` | рендерер, токены, промпты |
| Тесты, эталоны, UI-обвязка | `codex` | `gpt-5.6-sol`, effort `medium` | библиотека эталонов, чипы направлений |

### Что выяснилось на первом запуске (2026-09-03)

- `worker-start --agent codex --model gpt-5.6-sol --effort medium` работает, но только с `--from <coordinator_handle>` (иначе `selector_not_found`), и Codex при старте показывает «Update available» — скрипт снимает промпт и делает `dispatch --inject` повторно.
- `worker-start --agent claude` отвечает `agent_unconfigured`: у Orca нет управляемого аккаунта Claude (`orca account list`). Ручной `claude --model opus` в терминале воркtree требует OAuth-логина, который делает только человек. Пока логина нет, задачи Opus выполняются субагентами координатора (Agent tool, model opus) в тех же воркtree; провенанс Orca для них неполный. Чтобы вернуть Opus в Orca: `orca account add` для Claude или один раз войти в `claude` в терминале Orca.
- Провайдеры проекта — только OpenAI (Codex/Sol) и Claude; Kimi и z.ai выведены, GLM-слот из скрипта удалён.

### Как запускается каждый агент

- **Codex Sol medium**: `orca orchestration worker-start --task <id> --worktree new-child --agent codex --model gpt-5.6-sol --effort medium`.
- **Opus**: `orca orchestration worker-start --task <id> --worktree new-child --agent claude --model opus`.
- **Провайдеры**: только OpenAI (Codex CLI / Sol) и Claude (Claude Code). Без API-ключей: сервер и воркер ходят через консольные аккаунты (`app/cli_llm.py`); Seedance — через OpenRouter.

## Порядок

1. `run-create` с целью «Design Studio v3» — Run привязывается к этому терминалу.
2. `task-create` для T1…T6 из `docs/DESIGN-STUDIO-V3.md` § 4, зависимости через `--deps`.
3. `worker-start` для задач без зависимостей (T1, T4), остальные — по мере `worker_done`.
4. Координатор ждёт `orca orchestration check --wait`, читает `worker-read`, принимает по критериям из спецификации, сливает ветки воркtree в `codex/unified-motion-design`.

## Правила для воркеров (кладутся в spec задачи)

- Работать только в своём воркtree, коммитить в свою ветку, не пушить.
- Перед `worker_done`: `pytest app -q`, `npm --prefix frontend run check`, `npm --prefix frontend run build`; затронутые `app/ui_*_test.py` — прогнать на своём сервере (порт 8421+, `DESIGNDNA_DATA_DIR` во временной папке), не на общем 8420.
- Не трогать чужие файлы из таблицы владения в спецификации; конфликтующие правки — через `ask`.
- Отчёт в `worker_done`: что сделано, как проверено, что не удалось.
