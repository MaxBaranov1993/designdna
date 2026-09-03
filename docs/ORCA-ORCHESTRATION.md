# Orca-оркестрация DesignDNA

Координатор — Claude Fable 5.1 (этот терминал, воркtree `C:/Users/iamma/Documents/desingaiweb`). Воркеры — отдельные Orca-воркtree от базовой ветки, каждый со своим агентом. Скрипт: `tools/orca/design-studio-run.ps1`.

## Роли и модели

| Роль | Агент Orca | Модель / усилие | Для чего |
|---|---|---|---|
| Оркестратор | текущий терминал (Claude Code) | Fable 5.1 | план, задачи-DAG, приёмка, слияние |
| Реализация бэкенда | `codex` | `gpt-5.6-sol`, effort `medium` | Python-пайплайн, схемы, судья |
| Реализация фронта/архитектуры | `claude` | `opus` | рендерер, токены, промпты |
| Тесты, эталоны, UI-обвязка | `claude` через z.ai | GLM 5.3 | библиотека эталонов, чипы направлений |

### Как запускается каждый агент

- **Codex Sol medium**: `orca orchestration worker-start --task <id> --worktree new-child --agent codex --model gpt-5.6-sol --effort medium`.
- **Opus**: `orca orchestration worker-start --task <id> --worktree new-child --agent claude --model opus`.
- **GLM 5.3 (z.ai)**: у Orca нет отдельного провайдера, GLM работает через Claude Code с Anthropic-совместимым эндпоинтом z.ai. Нужны переменные окружения в терминале воркера (ключ хранится только в `%USERPROFILE%\.designdna\zai.env`, в репозиторий не попадает):

  ```powershell
  $env:ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"
  $env:ANTHROPIC_AUTH_TOKEN = "<ключ z.ai>"
  $env:ANTHROPIC_MODEL = "glm-5.3"
  claude
  ```

  Скрипт создаёт воркtree без агента, открывает терминал командой выше и делает `dispatch --to <handle> --inject`. Если файла с ключом нет, скрипт пропускает GLM-задачи и печатает, как их запустить на Codex.

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
