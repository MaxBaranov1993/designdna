# Контракт агентов: как приложение говорит с Claude Code и Codex

Дата: 2026-09-08. Проверено на Claude Code 2.1.190 и Codex CLI 0.153.2 на Windows 11.

DesignDNA ставят другие пользователи. Весь AI в продукте идёт через их собственные подписочные аккаунты: Claude Code (`claude -p`) и Codex (app-server, `codex exec`). Провайдер выбирается в каждой ноде, ноды одного графа могут работать на разных агентах. По API-ключу работает только Seedance через OpenRouter (видео). Orca и любая внешняя оркестрация в продукте отсутствуют.

Этот документ фиксирует, как инструкции продукта попадают в модель, что уже реализовано, что проверено экспериментально и что осталось.

## 1. Принципы

1. **«AGENTS.md» продукта — не файл в cwd.** Оба CLI сами ищут инструкции на диске пользователя: `~/.claude/CLAUDE.md`, CLAUDE.md во всех родительских каталогах cwd, `~/.codex/AGENTS.md`, AGENTS.md проекта, `settings.json` с хуками, `config.toml` с моделью и MCP-серверами. Продукт не может полагаться на этот механизм и обязан от него изолироваться.
2. **Инструкции идут явными каналами.** Claude: настоящий системный промпт через `--system-prompt-file`. Codex: `developerInstructions` в `thread/start`. Не текст пользователя с префиксом `SYSTEM:`.
3. **Герметичный запуск.** cwd — пустой каталог приложения, инструменты выключены на уровне CLI, MCP-серверы и настройки пользователя не подгружаются, сессии не сохраняются.
4. **Флаги — capability, а не константа.** Версия CLI на машине пользователя произвольна. Набор поддерживаемых флагов читается из `claude --help` и применяется по факту; для старых версий действует прежний контракт.
5. **Один контракт для обоих провайдеров.** Нода на Claude и нода на Codex получают одинаковый текст роли, одинаковые схемы и политику ДС. Различается только транспорт.
6. **Трассируемость.** Что реально дошло до модели (модель, усилие, транспорт, подхваченные файлы инструкций) записывается в метаданные ответа.

## 2. Что проверено экспериментально

Канареечные вызовы `claude -p --model haiku` из каталога `work/`, над которым лежит `CLAUDE.md` с инструкцией «начинай каждый ответ словом PINEAPPLE». Системный файл `benign.md`: «заканчивай каждый ответ токеном #ZEBRA». Запрос: «Reply with the single word OK».

| Запуск | Флаги | Ответ | Вывод |
| --- | --- | --- | --- |
| 1 | `--setting-sources "" --tools "" --strict-mcp-config` | `OK` | родительский CLAUDE.md не подхвачен |
| 2 | то же без `--setting-sources` | `PINEAPPLE OK` | без флага CLAUDE.md подхватывается |
| A | изоляция + `--system-prompt-file benign.md` | `OK #ZEBRA` | замена системного промпта работает |
| B | изоляция + `--system-prompt "…"` | `OK #ZEBRA` | inline-вариант работает |
| C | изоляция + `--append-system-prompt-file benign.md` | `OK #ZEBRA` | дополнение работает |
| D | изоляция + `--effort high` + `--system-prompt-file` | `OK #ZEBRA` | `--effort` принимается в print-режиме с подпиской |

Codex app-server 0.153.2 (локальная проверка без вызова модели): `thread/start` принимает `developerInstructions` и `config: {"project_doc_max_bytes": 0, "mcp_servers": {}}`. Выгруженная схема протокола (`codex app-server generate-json-schema`) содержит в `ThreadStartParams` поля `baseInstructions`, `developerInstructions`, `config`, `ephemeral`, в `TurnStartParams` — `effort`, `outputSchema`.

Факты из исходников и документации Codex (см. отчёт исследования 2026-09-08):

- `project_doc_max_bytes = 0` полностью отключает проектные AGENTS.md: `read_agents_md` возвращает `None` при нулевом лимите.
- Глобальный `$CODEX_HOME/AGENTS.md` отключить нельзя, кроме как подменой `CODEX_HOME`, что переносит и `auth.json`. Поэтому `thread/start` возвращает `instructionSources`, список подхваченных файлов, и продукт его записывает.
- `codex exec --ignore-rules` отключает только execpolicy-файлы `.rules`, не AGENTS.md. `--ignore-user-config` не загружает `config.toml`, авторизация сохраняется.
- Документированного лимита на параллельные запросы по подписке нет. Есть `account/rateLimits/read`. Несколько процессов на одном `auth.json` могут гоняться за обновлением токена.
- `--bare` у Claude Code недоступен для продукта: он отключает подписочный OAuth. Значение `--setting-sources ""` в документации не описано, документированы `user`, `project`, `local`. Поведение подтверждено канарейкой на 2.1.190 и должно перепроверяться самопроверкой при подключении.

## 3. Реализовано 2026-09-08

| Файл | Изменение |
| --- | --- |
| [desktop/services/hermetic-agent.mjs](../desktop/services/hermetic-agent.mjs) | общий модуль: `splitSystemMessages`, `HERMETIC_CODEX_CONFIG` |
| [desktop/services/claude-agent-server.mjs](../desktop/services/claude-agent-server.mjs) | `hermeticCwd`; system-сообщения и инструкции профиля через `--system-prompt-file`; `--tools ""` или `--tools Read`; `--strict-mcp-config`; `--effort medium/high/max`; capabilities из `claude --help` (`probeCapabilities`, `parseClaudeCapabilities`); для старых CLI прежний контракт с `MAX_THINKING_TOKENS` |
| [desktop/services/codex-app-server.mjs](../desktop/services/codex-app-server.mjs) | `hermeticCwd`; инструкции в `developerInstructions`; `config` с `project_doc_max_bytes: 0` и `mcp_servers: {}`; `instructionSources` в метаданных ответа |
| [desktop/main.mjs](../desktop/main.mjs) | пустые каталоги `userData/agent-cwd/claude` и `…/codex`; probe capabilities при старте |
| [app/cli_llm.py](../app/cli_llm.py) | тот же контракт для Python-пути: `--setting-sources ""`, `--tools`, `--strict-mcp-config`, `--effort`, `--system-prompt-file`, очистка API-переменных окружения; Codex exec с `project_doc_max_bytes=0` и `mcp_servers={}`; единая таблица бюджетов thinking с десктопом |
| тесты | `desktop/tests/claude-agent-server.test.mjs`, `codex-app-server.test.mjs`, `codex-image-transport.test.mjs`, `app/cli_llm_test.py` |

Второй этап того же дня, пакет инструкций и паритет вывода:

| Файл | Изменение |
| --- | --- |
| [app/prompts/agent-contract/](../app/prompts/agent-contract/) | `contract.json` (версия, роли, правила инструментов и вывода, напоминания, уровни усилия) и `roles/*.md` для chat, generator, quality_judge, quality_repair, editor, graphics. Тексты перенесены дословно из адаптеров |
| [desktop/services/agent-contract.mjs](../desktop/services/agent-contract.mjs), [app/agent_contract.py](../app/agent_contract.py) | два загрузчика одного пакета; `composeInstructions`/`compose` собирают «роль + правило инструментов + правило вывода» одинаково, тест `app/agent_contract_test.py` сверяет результат байт в байт через `node` |
| адаптеры Claude и Codex | собственные копии профилей удалены; роль `chat` теперь есть и у Codex, поэтому Agent Workspace на GPT больше не падает на «Unsupported Codex chat profile» |
| Claude, структурированный вывод | `responseFormat: json_schema` уходит в `--json-schema`, ответ берётся из `structured_output`; для CLI без флага или через cmd.exe-шим схема помечается как `dropped`, промпт по-прежнему просит JSON. `--max-turns` не передаётся: структурированный вывод внутри CLI занимает отдельный ход |
| [frontend/src/flow/store.ts](../frontend/src/flow/store.ts) | судья дизайн-системы получает схему вердикта и для Claude, не только для Codex |
| Python-путь | `cli_llm.chat(..., output_schema=)`: Claude через `--json-schema`, Codex через `--output-schema <файл>`; `llm_client.chat_envelope` передаёт `response_json_schema` в CLI-транспорт; правила инструментов берутся из пакета |
| трассировка | `transport.contractVersion` у обоих провайдеров, `generationLog.contractVersion` на сервере, `agentContract` в `GET /api/config` |
| самопроверка изоляции | `selfTest()` в обоих адаптерах, IPC `providers:self-test`, `window.designDNA.providers.selfTest`, кнопки «Проверить изоляцию GPT / Claude» в Connections ([AgentWorkspace.svelte](../frontend/src/desktop/AgentWorkspace.svelte)); тесты `desktop/tests/agent-isolation-selftest.test.mjs` |

Поведенческое изменение, которое стоит проверить реальной генерацией: системный промпт генератора теперь заменяет системный промпт Claude Code целиком, а у Codex уходит developer-сообщением. Это стандартный канал для обоих CLI, но качество конкретных ролей после переноса нужно посмотреть глазами.

## 3a. Обновление 2026-09-10: таймауты и арт-дирекция

Симптом: две ноды генератора (GPT-6 Astra и Claude Opus) падали с «Codex generator timed out» / «Claude generator timed out». Трасса показала: общий лимит адаптеров 180 с, а генерация с полным системным промптом, блоком дизайн-системы и референс-картинками занимает у Claude 90–220 с, у Codex дольше.

| Файл | Изменение |
| --- | --- |
| [desktop/services/provider-router.mjs](../desktop/services/provider-router.mjs) | `PROFILE_TIMEOUTS_MS`: generator и quality_repair 600 с, editor 480 с, art_direction/quality_judge/graphics 300 с, chat 180 с; явный `timeoutMs` конверта важнее. Таймер адаптера стартует после получения слота регулятора, очередь в него не входит |
| адаптеры Claude и Codex | значение по умолчанию `timeoutMs` поднято до 600 с |
| [app/prompts/agent-contract/](../app/prompts/agent-contract/) | версия `agent-contract/1.1`, новая роль `art_direction` (output json, `roles/art_direction.md`) |
| [app/api/generate.py](../app/api/generate.py), [frontend/src/flow/store.ts](../frontend/src/flow/store.ts) | арт-направления в десктопе идут через транспорт Electron: prepareOnly с `clientArtDirection: true` возвращает `artDirection.messages`, клиент зовёт провайдера с профилем `art_direction` и повторяет prepareOnly с `artDirectionRaw`; сервер валидирует ответ и кладёт в общий кэш. Раньше Python-воркер звал CLI сам: мимо регулятора и трассы, GPT-ноды получали «добавьте OPENAI_API_KEY», а интерактивный воркер с лимитом 120 с рисковал перезапуском |

Параллельность: регулятор даёт по два слота Claude и Codex (`DESIGNDNA_PROVIDER_CONCURRENCY`), остальные запросы ждут в FIFO-очереди без расхода таймаута; несколько нод генератора работают одновременно, третья на том же провайдере встаёт в очередь.

## 4. Каналы доставки по провайдерам

| Аспект | Claude Code | Codex |
| --- | --- | --- |
| Инструкции роли и system конверта | `--system-prompt-file <tmp>/system-prompt.md` | `thread/start.developerInstructions` |
| Ввод пользователя | stdin, блоки `USER:` / `ASSISTANT:`, в конце напоминание про JSON | `turn/start.input` (text, localImage) |
| Инструменты | `--tools ""`; с картинками `--tools Read --allowedTools Read` | `sandbox: read-only`, `approvalPolicy: never`, без dynamicTools |
| Настройки пользователя | `--setting-sources ""`, `--strict-mcp-config`, очищенный env | `config.project_doc_max_bytes = 0`, `config.mcp_servers = {}` |
| cwd | `userData/agent-cwd/claude` | `userData/agent-cwd/codex` |
| Усилие | `--effort medium/high/max`, для старых CLI `MAX_THINKING_TOKENS` 0/8k/24k | `turn/start.effort` |
| Структурированный вывод | `--json-schema` → `structured_output` для компактных схем (вердикты); большая схема Design IR остаётся текстовым JSON с серверной валидацией | `turn/start.outputSchema` |
| Сессии | одноразовый процесс | `ephemeral: true` |
| Трассировка | модель, флаги capabilities | модель, `threadId`, `turnId`, `instructionSources` |

## 5. Остаточные риски

- **Глобальный `~/.codex/AGENTS.md`.** Не отключается. Смягчение: инструкции продукта идут developer-сообщением, а список подхваченных файлов пишется в `transport.instructionSources`. Следующий шаг: показывать предупреждение в Connections, если список непуст.
- **`--setting-sources ""` не документирован.** Работает на 2.1.190. Нужна самопроверка при подключении: канарейка с CLAUDE.md в герметичном cwd, один дешёвый вызов, результат в статусе провайдера.
- **Два транспорта на один `auth.json`.** Electron держит app-server, Python-путь запускает `codex exec` для ревью мастеров ДС, timeline director и понимания страницы. Обновление токена может гоняться. Целевое состояние: один владелец транспорта в Electron, Python-воркер запрашивает `ai.chat` по существующему JSONL-протоколу.
- **Политика вендоров.** Anthropic: использование Claude Code сторонним приложением с подпиской пользователя в документации не описано. OpenAI: руководитель Codex публично подтвердил, что подписка через Sign in with ChatGPT в сторонних клиентах допустима, а превращение подписки в API-трафик для многих пользователей — нет. Документация OpenAI направляет автоматизацию на API-ключи. Уточнить до релиза.
- **Хранение `setup-token` в приложении.** Приложение умеет хранить долгоживущий OAuth-токен Claude в safeStorage. Безопаснее полагаться на логин самого CLI и ничего не хранить.

## 6. Следующие шаги

1. **Пакет инструкций `agent-contract/`.** Сделано 2026-09-08, см. таблицу выше. Осталось: перенести в пакет тексты ролей Python-пути (`llm_client._ROLES` и системные промпты `app/prompts/*.md` остаются отдельным слоем) и добавить роль `assistant` для агентных тредов.
2. **Один компилятор в Python.** Фаза prepare возвращает провайдер-нейтральный конверт:

```json
{
  "contractVersion": "agent-contract/1.0",
  "role": "generator",
  "system": "…роль + SYSTEM.md + политика + ДС…",
  "messages": [{ "role": "user", "content": "…" }],
  "outputSchema": { "$ref": "schema/design-ir.schema.json" },
  "toolPolicy": "none",
  "effort": "high",
  "images": []
}
```

   Electron-адаптеры и `cli_llm.py` принимают этот конверт без знания о ролях.
3. **Самопроверка при подключении.** Сделано 2026-09-08: кнопки «Проверить изоляцию GPT / Claude» в Connections, IPC `providers:self-test`. Codex: `thread/start` в каталоге с канареечным AGENTS.md в герметичной конфигурации, без вызова модели; app-server возвращает `instructionSources`, канарейки там быть не должно, глобальные файлы показываются отдельно (проверено локально: в герметичной конфигурации список пуст, в конфигурации по умолчанию содержит канарейку). Claude: канареечный CLAUDE.md над рабочим каталогом и один короткий запрос haiku по подписке с производственными флагами; ответ со словом-маркером означает протек. Осталось: показывать результат и версию CLI в ноде рядом с выбором провайдера.
4. **Паритет структурированного вывода.** Сделано 2026-09-08 для вердиктов судьи; большая схема Design IR остаётся текстовым JSON с валидацией и одной попыткой исправления.
5. **Agent Workspace**: роль `assistant` с содержимым `skills/designdna/SKILL.md` как `developerInstructions` для Codex и `--append-system-prompt-file` для Claude; для Claude либо подключить собственный MCP приложения через `--mcp-config`, либо явно показать, что инструменты недоступны.
6. **Регулятор параллелизма.** Сделано 2026-09-09: [provider-governor.mjs](../desktop/services/provider-governor.mjs) держит лимит слотов на провайдера (по умолчанию Claude 2, Codex 2, GPT через Codex делит его слоты; `DESIGNDNA_PROVIDER_CONCURRENCY="claude=2,codex=2"`), очередь FIFO, отменённый в очереди запрос слот не занимает. Состояние в `providers:status.governor`, время ожидания в `transport.queuedMs`. Осталось: показать очередь в ноде и повтор при явных лимитах подписки.
7. **Трасса вызовов моделей.** Сделано 2026-09-09 в JSONL вместо SQLite: `<data>/traces/llm-calls.electron.jsonl` ([llm-trace.mjs](../desktop/services/llm-trace.mjs)) и `llm-calls.python.jsonl` ([app/llm_trace.py](../app/llm_trace.py)). Только метаданные: провайдер, модель, усилие, версия контракта, структурированный вывод, `dropped`, длительность и ожидание в очереди, объёмы промпта и ответа, ошибка, отмена, число подхваченных файлов инструкций. Текст промптов и ответов не пишется. Чтение: `GET /api/agent/trace?limit=50&source=python|electron` и MCP-инструмент `designdna_llm_calls`. Осталось: сырые промпты по явному флагу отладки и связь записи с `runId` ноды.
