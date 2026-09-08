# DesignDNA: карта репозитория для агентов

Локальная студия веб-дизайна: Electron-приложение с Python-бэкендом и Svelte-фронтендом. Продукт ставят другие пользователи. Весь AI в продукте идёт через подписочные Claude Code и Codex самого пользователя, выбор провайдера делается в каждой ноде. По API-ключу работает только Seedance через OpenRouter (видео). Веб-режим и внешняя оркестрация в продукте не нужны.

## Слои

| Каталог | Что там | Как проверять |
| --- | --- | --- |
| `app/` | FastAPI-бэкенд ([server.py](app/server.py) плюс роутеры `design_system/api.py`, `timeline_api.py`, `video_api.py`, `editor_assist.py`), IR (`app/ir/`), хранилища (`project_store.py`, `cache_store.py`, `design_system/store.py`), AI-транспорт (`llm_client.py`, `cli_llm.py`), MCP-сервер (`designdna_mcp_server.py`) | `.venv/Scripts/python -m pytest app/<файл>_test.py -q` |
| `desktop/` | Electron: `main.mjs`, сервисы провайдеров (`services/claude-agent-server.mjs`, `codex-app-server.mjs`, `provider-router.mjs`), мост к Python-воркеру по JSONL (`lib/jsonl-process.mjs`) | `npm --prefix desktop test` |
| `frontend/` | SvelteKit + Svelte Flow: граф нод (`src/flow/`), редактор (`src/editor/`), десктопный мост (`src/desktop/`) | `npm --prefix frontend run build:desktop`, `node --test frontend/tests/*.test.mjs` |
| `schema/` | JSON-схемы Design IR, Design System, Motion, Timeline. Источник истины для контрактов | `app/*_schema*_test.py` |
| `app/prompts/` | SYSTEM.md, DESIGN.md, BLOCKS.md, RUBRIC.md, generator-policy.json: промпты генератора | `app/prompt_exemplars_test.py`, `app/generator_policy_test.py` |
| `app/prompts/agent-contract/` | пакет инструкций ролей для Claude Code и Codex: `contract.json` и `roles/*.md`; читают `desktop/services/agent-contract.mjs` и `app/agent_contract.py` | `app/agent_contract_test.py`, `desktop/tests/agent-contract.test.mjs` |
| `skills/designdna/` | SKILL.md для внешних агентов, работающих с DesignDNA через MCP | `app/designdna_mcp_server_test.py` |
| `docs/` | текущие документы, см. ниже | |

Тесты лежат рядом с кодом: `app/<модуль>_test.py`, `desktop/tests/*.test.mjs`, `frontend/tests/*.test.mjs`.

## Команды

```bash
npm --prefix desktop test
```

```bash
.venv/Scripts/python -m pytest app -q --ignore-glob="app/ui_*" --ignore-glob="*_live_test.py" --ignore-glob="app/designdna_live_mcp_test.py"
```

```bash
npm run desktop:start
```

- Быстрый Python-набор выше идёт около 6 минут (883 теста на 2026-09-08); десктопный и фронтендовый наборы — по несколько секунд.
- `app/ui_*_test.py` требуют собранный фронтенд, запущенный сервер и Playwright; список поддерживаемого набора в [app/ui_smoke.py](app/ui_smoke.py).
- `*_live_test.py` делают платные вызовы AI. Не запускать без явной просьбы.
- Полный CI: [.github/workflows/desktop.yml](.github/workflows/desktop.yml).

## Инварианты

- **Сохранение проекта — CAS.** `POST /api/project/save` с `expectedRevision`; ревизия — SHA-256 сохранённого JSON ([project_store.py](app/project_store.py)). Конфликт возвращает 409, не перезаписывает.
- **Дизайн-система — реестр и неизменяемые ревизии.** Черновик хранится как ревизия 0, публикация создаёт неизменяемую ревизию, идемпотентно по `contentHash` ([design_system/store.py](app/design_system/store.py)).
- **`componentRef`, `tokens`, `_dsMaster`, `sourceMeta`, `typeRole` в IR не выдумываются и не переименовываются.** Правила в [skills/designdna/SKILL.md](skills/designdna/SKILL.md).
- **Запуск подписочных CLI герметичен.** Инструкции идут явными каналами, cwd — пустой каталог приложения, инструменты выключены, настройки и AGENTS.md/CLAUDE.md пользователя не подгружаются. Контракт и проверенные факты: [docs/AGENT-CONTRACT.md](docs/AGENT-CONTRACT.md). Не возвращать инструкции в текст пользователя и не ослаблять флаги изоляции.
- **Продуктовый путь без API-ключей.** `OPENAI_API_KEY` в Python остаётся для dev и тестов; в продукте GPT идёт через Codex, Claude через Claude Code.
- **Асинхронные результаты нод привязаны к листу и поколению графа.** Подробности в [docs/node-execution.md](docs/node-execution.md).

## Данные

- Dev: `data/` в корне (gitignored): `projects.db`, `design_systems.db`, `cache.db`, `blobs/`, `fonts/`.
- Упакованное приложение: `%APPDATA%\@designdna\desktop\data`, герметичные cwd для CLI в `%APPDATA%\@designdna\desktop\agent-cwd`.
- Не трогать пользовательские `data/` и профили Electron в тестах: проверки интерфейса выполняются в отдельном профиле.

## Документы

| Документ | Зачем |
| --- | --- |
| [docs/AGENT-CONTRACT.md](docs/AGENT-CONTRACT.md) | как приложение говорит с Claude Code и Codex, что проверено, что осталось |
| [docs/BACKEND-REVIEW-2026-09-08.md](docs/BACKEND-REVIEW-2026-09-08.md) | разбор бэкенда и чек-лист улучшений |
| [docs/node-execution.md](docs/node-execution.md) | ноды, листы, жизненный цикл асинхронных задач |
| [docs/all-nodes-review-2026-09-08.md](docs/all-nodes-review-2026-09-08.md) | ревью всех типов нод и результаты проверок |
| [docs/generator-design-playbook/README.md](docs/generator-design-playbook/README.md) | дизайн-политика генератора |
| [docs/image-nodes.md](docs/image-nodes.md) | ноды изображений |
| [skills/designdna/SKILL.md](skills/designdna/SKILL.md) | MCP-инструменты и порядок работы внешнего агента |

Старые документы (ARCHITECTURE, AI, MCP, ROADMAP и другие) лежат в `artifacts/docs-refresh-2026-09-06/previous-documentation.zip` и в `docs/archive/`; в рабочем дереве их нет.

## Правила для агентов

- Изменение поведения сопровождается тестом рядом с модулем и запуском соответствующего набора из таблицы выше.
- Промпты меняются только в `app/prompts/`; тексты ролей для CLI только в `app/prompts/agent-contract/roles/`, в JS и Python их копий нет. Изменение текста роли или версии пакета отражать в `contract.json` (`version`).
- Схемы в `schema/` меняются вместе с миграцией в `app/ir/migrate.py` и тестами.
- Секреты не логировать: OAuth-токены и ключи живут в safeStorage Electron и в env дочерних процессов.
- Коммиты и push только по просьбе пользователя.
