# Редактор/генератор от ДС + карточка товара slsbmb — запуск Orca-оркестрации.
# Координатор: Claude Fable 5.1 (Claude Code); воркеры: Codex gpt-5.6-sol medium в дочерних воркtree.
# Использование (из корня репозитория):
#   powershell -File tools/orca/ds-editor-run.ps1                 # создать Run + задачи + стартовать все
#   powershell -File tools/orca/ds-editor-run.ps1 -Start P1,P2    # стартовать конкретные задачи
#   powershell -File tools/orca/ds-editor-run.ps1 -SkipCreate -Start P3
param(
  [string[]]$Start = @("P1", "P2", "P3", "P4"),
  [switch]$SkipCreate
)
$ErrorActionPreference = "Stop"
$Start = @($Start | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$orca = if ($env:ORCA_CLI_COMMAND) { $env:ORCA_CLI_COMMAND } else { "orca" }
$plan = "docs/WORK-PLAN-DS-EDITOR-GENERATOR.md"
$analysis = "docs/COMPETITOR-ANALYSIS-AI-DESIGN-TOOLS.md"
$repoId = "c20dcb65-e965-4cf2-b40b-2a2bf006eb46"
$main = (Get-Location).Path
$baseBranch = "codex/unified-motion-design"

$rules = @"
Правила: работать только в своём воркtree и своей ветке (git branch --show-current), коммитить туда, не пушить. База — ветка $baseBranch (уже в воркtree). Окружение: .venv, node_modules, frontend/node_modules — junction-ссылки на основной чекаут, .env скопирован. Перед worker_done: .venv\Scripts\python -m pytest app -q; npm --prefix frontend run check; npm --prefix frontend run build; затронутые app/ui_*_test.py гонять на СВОЁМ сервере (cd app; ..\.venv\Scripts\python -m uvicorn server:app --port <8431+>; DESIGNDNA_DATA_DIR во временной папке внутри воркtree; в тесте подменять BASE), не на 8420. Playwright-сценарии обязаны мокать **/api/project/load и **/api/project/save (иначе затирается проект пользователя). Чужие файлы вне своей таблицы владения не трогать; если правка нужна в чужом файле — orca orchestration ask. Без API-ключей LLM ходит через консольный Codex CLI (LLM_CLI_PROVIDER=codex, app/cli_llm.py) — это нормально, ждать. Отчёт в worker_done: что сделано, как проверено (команды и результат), что не удалось и почему. Контекст: $analysis (что за минусы конкурентов закрываем), $plan (что уже сделано в первом проходе и что осталось).
"@

$tasks = @(
  @{ id = "P1"; deps = @();
     title = "P1 Карточка товара slsbmb: Source → ДС → мастер в редакторе → вариант";
     spec = "Цель: показать сквозной сценарий из видео-разбора на реальном сайте https://slsbmb.com — компонент «карточка товара» в ноде «Редактор (DNA)», собранный из Source Import через Design System, плюс пользовательский вариант карточки, сохранённый из редактора. Сделать Playwright-скрипт tools/slsbmb_product_card.py (образец: app/ui_design_system_test.py, app/ui_flow_edit_test.py, API window.GraphDev и window.__flowStore; ОБЯЗАТЕЛЬНО page.route на **/api/project/load|save). Шаги скрипта: (1) нода sourceimport с url https://slsbmb.com, запуск импорта (runNode), дождаться блоков; (2) createDesignSystemFromSource → нода ДС, дождаться черновика; (3) AI-ревью/доводка мастеров (кнопки панели ДС или POST /api/design-system/master-review с repair) — провайдер Codex CLI, ждать до 10 минут; (4) найти компонент карточки товара (name/category/componentKey с card/product/tile/item/товар; если карточка только в reviewComponents — довести через ревью/доводку; если её нет вовсе — взять ближайший мастер карточки/плитки и зафиксировать это в отчёте); (5) опубликовать ДС (publishDesignSystem); (6) applyDesignSystemToEditor(dsNodeId, key) → открыть редактор на мастере, сделать скриншот; (7) через кнопку «Вариант в ДС» (data-act=save-ds-variant; window.prompt замокать page.on('dialog')) или напрямую POST /api/design-system/variant/save сохранить вариант «Со скидкой» (изменённая цена/бейдж в тексте IR); (8) проверить панель «Компоненты» (data-act=components → data-component-insert) — вставка секции с componentRef; (9) выгрузить артефакты: artifacts/slsbmb/design-system.json (полный документ, POST /api/design-system/get), artifacts/slsbmb/product-card.master.json, artifacts/slsbmb/product-card.variant.json, PNG мастера и варианта через app/ir_render.py render_png, скриншоты редактора; (10) отчёт results/slsbmb-product-card.md: какой компонент, fidelity/ревью, что получилось в редакторе, оценка судьи (POST /api/quality-pass на IR мастера, если доступен), найденные дефекты приложения (не чинить чужие файлы — описать). Владение: tools/slsbmb_product_card.py, artifacts/slsbmb/**, results/slsbmb-product-card.md. Сервер поднимать свой (порт 8431, DESIGNDNA_DATA_DIR=<worktree>/.tmp-data), фронт собрать заранее (npm --prefix frontend run build). $rules" },
  @{ id = "P2"; deps = @();
     title = "P2 Остаток плана: typeRole в промптах и эталонах, варианты в компиляторе ДС, вставка по выделению, стейл-тест ДС";
     spec = "Из $plan (раздел «Осталось после первого прохода»): (a) app/prompts/DESIGN.md — раздел «Текстовые стили»: у heading/text задавать typeRole вместо инлайновых fontSize/lineHeight/fontWeight; app/exemplars/*.json — проставить typeRole у заголовков/текстов (display/h1/h2/h3/lead/body/small/eyebrow), схема должна остаться валидной (pytest app/ir_* и exemplar-тесты). (b) app/design_system/compiler.py: в registry.components/registry.master.<key> отдавать компактный список вариантов компонента (key, label, origin) и правило «вариант выбирай по смыслу брифа»; app/design_system/resolver.py validate_generation: componentRef, чей masterHash совпадает с masterIr пользовательского варианта (variants[k].masterIr/masterHash), принимается как точная копия; тесты. (c) Панель «Компоненты» (frontend/src/editor/ComponentsPanel.svelte, функция insertDesignSystemSection в frontend/src/editor/controller.ts): вставка после выделенной секции (если выделение есть), иначе в конец; Playwright-тест app/ui_editor_components_panel_test.py с моками /api/design-system/get и /api/design-system/component-section (проверить порядок секций и componentRef). (d) app/ui_design_system_test.py: актуализировать под панель ДС после правок 09-03/09-04 (шаг «semantic suggestion can be explicitly promoted» падает из-за fidelity-гейта) — тест должен проходить на своём сервере; при необходимости добавить в TESTS app/ui_smoke.py. (e) app/design_system/document.py summary: variants считает и пользовательские варианты (origin user). Владение: app/prompts/DESIGN.md, app/exemplars/**, app/design_system/compiler.py, app/design_system/resolver.py, app/design_system/document.py (только summary), frontend/src/editor/ComponentsPanel.svelte, frontend/src/editor/controller.ts (только insertDesignSystemSection), app/ui_design_system_test.py, app/ui_smoke.py, новые тесты. $rules" },
  @{ id = "P3"; deps = @();
     title = "P3 Арт-дирекция и эталоны в пайплайне генерации";
     spec = "Сейчас app/art_direction.py create_design_brief и llm_client.load_exemplars не вызываются из _generate (app/server.py), плейсхолдеры {{DESIGN_BRIEF}}/{{EXEMPLARS}} в spike/system-prompt.md пусты, чипы направлений на ноде Генератора живут только на мок-ответе (app/ui_generator_directions_test.py). Сделать: в _generate для mode==generate стадия art-direction (run_registry.stage 'art-direction'), create_design_brief через быструю роль (llm_client, кэш по брифу+типу продукта+ДС), три направления с label/motivation/tradeoff; GenerateReq.selectedDirection ('all' | id) — при 'all' варианты получают разные направления, при выборе — все варианты в одном; llm.build_system_prompt(mode, design_brief=..., exemplars=...) с 2–3 эталонами из app/exemplars по типу продукта; ответ /api/generate содержит directions и variantDirections (форма, которую уже читает frontend/src/flow/store.ts generatorDirections/generatorVariantDirections), generationLog.direction; prepareOnly тоже несёт бриф. При отказе быстрой модели — деградация без арт-дирекции, не ошибка. Тесты с моком llm (app/generation_provider_test.py — расширить, не ломать существующие). Владение: app/server.py (только _generate и GenerateReq), app/art_direction.py, app/llm_client.py (build_system_prompt/exemplars), spike/system-prompt.md, тесты. Не трогать frontend. $rules" },
  @{ id = "P4"; deps = @();
     title = "P4 MCP со скиллами: высокоуровневые инструменты и SKILL.md";
     spec = "Из $analysis (эпик E1): внешний агент по MCP сейчас получает только project_get/put/validate/summary/live_command и собирает IR «руками». Добавить в app/designdna_mcp_server.py инструменты: designdna_generate (brief, designSystem {systemId, revision?, usageMode}, count, referenceIrs? → POST http://127.0.0.1:8420/api/generate локального сервера; вернуть variants + generationLog + qa; URL сервера из env DESIGNDNA_SERVER_URL, дефолт 8420), designdna_list_design_systems (реестр из design_system.store: systemId, name, status, revision, компоненты с ключами/категориями/вариантами, irTokens компактно), designdna_review (ir → POST /api/quality-gate strictTokens + при наличии ДС validate_generation через POST /api/design-system/resolve-context; вернуть violations/journal/fixed_ir), designdna_rules_get / designdna_rules_set (GET/POST /api/rules). Описания инструментов должны вести агента к ним, project_put пометить как служебный. Пакет навыка skills/designdna/SKILL.md для Claude Code/Codex/Cursor: когда какой инструмент звать, как не ломать токены и componentRef, когда звать review. Тесты app/designdna_mcp_server_test.py с моком HTTP (urllib/requests) — расширить существующие, не ломать. Документация: docs/MCP.md (или раздел в README). Владение: app/designdna_mcp_server.py, app/designdna_mcp_server_test.py, skills/designdna/**, docs/MCP.md. Не трогать server.py и frontend. $rules" }
)

function Invoke-Orca([string[]]$cli) {
  $out = & $orca @cli 2>&1
  if ($LASTEXITCODE -ne 0) { throw "orca $($cli -join ' ') failed: $out" }
  return ($out | Out-String | ConvertFrom-Json)
}

# Координатор: Claude Code запущен не из Orca-терминала, поэтому --from берём у живого
# терминала основного воркtree (создаём shell, если его нет).
$mainWt = "id:${repoId}::" + ($main -replace "\\", "/")
$terms = (Invoke-Orca @("terminal", "list", "--worktree", $mainWt, "--json")).result.terminals
$coord = ($terms | Where-Object { $_.status -ne "exited" } | Select-Object -First 1).handle
if (-not $coord) {
  $created = Invoke-Orca @("terminal", "create", "--worktree", $mainWt, "--title", "coordinator", "--json")
  $coord = $created.result.terminal.handle
}
Write-Host "coordinator terminal: $coord"

$stateFile = ".orca-ds-editor-tasks.json"
$ids = @{}
if (Test-Path $stateFile) {
  (Get-Content $stateFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $ids[$_.Name] = $_.Value }
}
if (-not $SkipCreate) {
  if (-not $ids["run"]) {
    $run = Invoke-Orca @("orchestration", "run-create", "--from", $coord, "--objective", "Редактор и генератор от дизайн-системы по плану $plan + карточка товара slsbmb", "--json")
    $ids["run"] = $run.result.run.id
    $ids | ConvertTo-Json | Set-Content -Encoding utf8 $stateFile
  }
  Write-Host "Run: $($ids['run'])"
  foreach ($t in $tasks) {
    if ($ids[$t.id]) { Write-Host "$($t.id) exists -> $($ids[$t.id])"; continue }
    $depIds = @($t.deps | ForEach-Object { $ids[$_] } | Where-Object { $_ })
    $cli = @("orchestration", "task-create", "--from", $coord, "--run", $ids["run"], "--spec", $t.spec, "--task-title", $t.title, "--display-name", $t.id, "--json")
    if ($depIds.Count) { $cli += @("--deps", ("[" + (($depIds | ForEach-Object { '\"' + $_ + '\"' }) -join ",") + "]")) }
    $res = Invoke-Orca $cli
    $ids[$t.id] = $res.result.task.id
    Write-Host "$($t.id) -> $($ids[$t.id])"
    $ids | ConvertTo-Json | Set-Content -Encoding utf8 $stateFile
  }
}

function Prepare-Worktree([string]$path) {
  # Дочерний воркtree ветвится от старого main; окружения в нём нет.
  git -C $path reset -q --hard $baseBranch
  foreach ($rel in @(".venv", "node_modules", "frontend\node_modules")) {
    $link = Join-Path $path $rel; $target = Join-Path $main $rel
    if (-not (Test-Path $link) -and (Test-Path $target)) { cmd /c mklink /J "$link" "$target" | Out-Null }
  }
  if (Test-Path (Join-Path $main ".env")) { Copy-Item (Join-Path $main ".env") (Join-Path $path ".env") -Force }
}

function Unblock-Codex([string]$handle) {
  # Codex TUI при старте показывает «Update available» — «2. Skip».
  $screen = ((Invoke-Orca @("terminal", "read", "--terminal", $handle, "--json")).result.terminal.tail -join " ")
  if ($screen -match "Update available") {
    Invoke-Orca @("terminal", "send", "--terminal", $handle, "--text", "2", "--json") | Out-Null
    Start-Sleep -Seconds 1
    Invoke-Orca @("terminal", "send", "--terminal", $handle, "--text", "", "--enter", "--json") | Out-Null
  }
  # tui-idle может не наступить (Codex рисует спиннер) — таймаут не фатален, dispatch --inject сам проверит готовность
  try { Invoke-Orca @("terminal", "wait", "--terminal", $handle, "--for", "tui-idle", "--timeout-ms", "90000", "--json") | Out-Null }
  catch { Write-Warning "tui-idle не дождались: $handle" }
}

foreach ($id in $Start) {
  $t = $tasks | Where-Object { $_.id -eq $id }
  if (-not $t) { Write-Warning "unknown task $id"; continue }
  $taskId = $ids[$id]
  $name = "dse-$($id.ToLower())"
  $cli = @("orchestration", "worker-start", "--from", $coord, "--run", $ids["run"], "--task", $taskId, "--worktree", "new-child", "--name", $name, "--agent", "codex", "--model", "gpt-5.6-sol", "--effort", "medium", "--timeout-ms", "600000", "--json")
  $out = & $orca @cli 2>&1 | Out-String
  try { $w = $out | ConvertFrom-Json } catch { Write-Warning "worker-start $id raw: $out"; continue }
  $handle = ($w.result.effects | Where-Object { $_.kind -eq "terminal" } | Select-Object -First 1).id
  $wtPath = (($w.result.effects | Where-Object { $_.kind -eq "worktree" } | Select-Object -First 1).id -split "::")[1]
  if ($wtPath) { Prepare-Worktree $wtPath; Write-Host "$id worktree: $wtPath" }
  if ($w.result.state -eq "ready") { Write-Host "$id started: dispatch $($w.result.dispatchId) terminal $handle"; continue }
  Write-Host "$id state=$($w.result.state) stage=$($w.result.stage) — снимаю промпт Codex и выдаю задачу заново"
  Unblock-Codex $handle
  Invoke-Orca @("orchestration", "task-update", "--from", $coord, "--id", $taskId, "--status", "ready", "--run", $ids["run"], "--json") | Out-Null
  $d = Invoke-Orca @("orchestration", "dispatch", "--from", $coord, "--run", $ids["run"], "--task", $taskId, "--to", $handle, "--inject", "--json")
  Write-Host "$id dispatched after unblock: $($d.result.dispatch.id) terminal $handle"
}
Write-Host "Далее: orca orchestration check --from $coord --wait --types worker_done,escalation,question --timeout-ms 900000 --json"
