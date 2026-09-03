# Design Studio v3 — запуск Orca-оркестрации (координатор: Claude Fable 5.1 в текущем терминале).
# Использование (из Orca-терминала координатора):
#   powershell -File tools/orca/design-studio-run.ps1            # создать Run + задачи + стартовать T1/T4
#   powershell -File tools/orca/design-studio-run.ps1 -Start T2,T3   # стартовать конкретные задачи
# GLM 5.3: положите ключ z.ai в %USERPROFILE%\.designdna\zai.env строкой ANTHROPIC_AUTH_TOKEN=...
param(
  [string[]]$Start = @("T1", "T4"),
  [switch]$SkipCreate
)
$ErrorActionPreference = "Stop"
$Start = @($Start | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$orca = if ($env:ORCA_CLI_COMMAND) { $env:ORCA_CLI_COMMAND } else { "orca" }
$spec = "docs/DESIGN-STUDIO-V3.md"

$rules = @"
Правила: работать только в своём воркtree и своей ветке, не пушить. Перед worker_done: .venv\Scripts\python -m pytest app -q; npm --prefix frontend run check; npm --prefix frontend run build; затронутые app/ui_*_test.py гонять на СВОЁМ сервере (uvicorn server:app --port 8421+, DESIGNDNA_DATA_DIR во временной папке), не на 8420. Чужие файлы из таблицы владения не трогать, спорное — через orca orchestration ask. Отчёт в worker_done: что сделано, как проверено, что не удалось. Спецификация: $spec (§3 архитектура, §4 задачи).
"@

$tasks = @(
  @{ id = "T1"; agent = "codex"; model = "gpt-5.6-sol"; effort = "medium"; deps = @();
     title = "T1 Art direction stage + oklch palette";
     spec = "Задача T1 из ${spec}: схема schema/design-brief.schema.json (DesignBrief: audience, tone из именованного списка, typePair, palette-семя oklch, rhythm с одним риском, copyDeck), модуль app/art_direction.py (вызов быстрой модели через llm_client с ролью 'art-direction', кэш по брифу+типу продукта), расширенный курируемый список типографских пар в app/typography.py (характерные display+body с fallback-стеками, не Inter/Roboto/Arial), генерация тональной палитры из oklch-семени в app/colorutils.py с проверкой WCAG всех пар текст/фон. Юнит-тесты на схему, палитру (контраст) и кэш. Владение: schema/design-brief.schema.json, app/art_direction.py, app/typography.py, app/colorutils.py, новые тесты. $rules" },
  @{ id = "T4"; agent = "codex"; model = "gpt-5.6-sol"; effort = "medium"; deps = @();
     title = "T4 Vision judge on rendered pixels";
     spec = "Задача T4 из ${spec}: серверный рендер IR в PNG (переиспользовать офлайн-путь timeline_render.py / headless Chromium, функция app/ir_render.py:render_png(ir, width=1440)), рубрика судьи app/prompts/RUBRIC.md (иерархия, ритм, плотность, типографика, цвет, слоп-тропы, соответствие брифу; примеры плохо/хорошо), _quality_scorecard в app/server.py получает скриншот через llm_client.chat_vision, score 0-100 и адресные правки; стадии 'render'/'judge' публикуются в run_registry; порог по умолчанию 80 в QualityPassReq. Тесты с моком vision-модели. Владение: app/ir_render.py, app/prompts/RUBRIC.md, функции _quality_scorecard/_quality_repair в app/server.py, новые тесты. $rules" },
  @{ id = "T2"; agent = "claude"; model = "opus"; effort = ""; deps = @("T1");
     title = "T2 Tokens v2 + role-based renderer";
     spec = "Задача T2 из ${spec}: tokens.v2 (color bg/bg2/surface/surface2/ink/ink2/inkMuted/line/accent/accentInk/accent2; type-роли display/h1/h2/h3/lead/body/small/eyebrow с size/lineHeight/tracking/weight; space, radius, shadow, motion), обратно совместимая миграция в app/ir/migrate.py, рендерер frontend/src/engine/renderer.ts читает роли вместо calc(17px*var(--fs)), инспектор и DesignSystemPanel показывают новые роли. Тесты: миграция v1→v2, ui_renderer_frame_test и ui_style_projection_test зелёные. Владение: schema/design-ir.schema.json (tokens), app/ir/migrate.py, frontend/src/engine/renderer.ts (tokens/typography), frontend/src/editor/inspector/*, frontend/src/editor/DesignSystemPanel.svelte. $rules" },
  @{ id = "T3"; agent = "claude"; model = "opus"; effort = ""; deps = @("T1");
     title = "T3 Composition block + generate-first prompt + exemplars";
     spec = "Задача T3 из ${spec}: блок composition (дерево примитивов с auto-layout frame) в схеме, BLOCKS.md и рендерере; новые характерные варианты hero (editorial-stack, poster, split-offset, numbered) и feature (list-rail, bento-asym, two-col-manifest); заглушки изображений в тоне палитры; переписанный spike/system-prompt.md: generate — основной режим, DesignBrief в контексте, few-shot из app/exemplars/*.json, варианты = разные направления с подписью; 3 первых эталона (SaaS-лендинг, маркетплейс, ресторан) ручной работы. Тесты: схема, рендер новых вариантов, промпт-сборка. Владение: spike/system-prompt.md, app/prompts/BLOCKS.md, app/prompts/DESIGN.md, app/exemplars/, frontend/src/engine/renderer.ts (секции), schema/design-ir.schema.json (blocks). $rules" },
  @{ id = "T5"; agent = "glm"; model = ""; effort = ""; deps = @("T1", "T4");
     title = "T5 Generator node UI: direction chips + verdict";
     spec = "Задача T5 из ${spec}: в GeneratorNode.svelte чипы 3 направлений из стадии арт-дирекции (мотивация + компромисс), выбор одного или всех, подписи вариантов направлением вместо 'Вариант 1/2', статус 'нужна доработка' с причинами судьи, запоминание выбранного направления в taste-профиле. Playwright-тест ui_generator_directions_test.py с моками /api/generate. Владение: frontend/src/nodes/GeneratorNode.svelte, frontend/src/flow/store.ts (runGenerator UI-часть), новый тест. $rules" },
  @{ id = "T6"; agent = "glm"; model = ""; effort = ""; deps = @("T3", "T4");
     title = "T6 Exemplar library + before/after quality report";
     spec = "Задача T6 из ${spec}: довести app/exemplars до 10+ страниц по типам продуктов, каждая ≥90 у vision-судьи; скрипт tools/quality_report.py — 5 фиксированных брифов (SaaS, маркетплейс, ресторан, портфолио, финтех), генерация до/после, PNG и баллы в results/quality-report.md. Владение: app/exemplars/, tools/quality_report.py, results/quality-report.md. $rules" }
)

function Invoke-Orca([string[]]$cli) {
  $out = & $orca @cli 2>&1
  if ($LASTEXITCODE -ne 0) { throw "orca $($cli -join ' ') failed: $out" }
  return ($out | Out-String | ConvertFrom-Json)
}

$stateFile = ".orca-design-studio-tasks.json"
$ids = @{}
if (Test-Path $stateFile) {
  (Get-Content $stateFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $ids[$_.Name] = $_.Value }
}
if (-not $SkipCreate) {
  if (-not $ids["run"]) {
    $run = Invoke-Orca @("orchestration", "run-create", "--objective", "Design Studio v3: первоклассный дизайн в ноде Генератор (docs/DESIGN-STUDIO-V3.md)", "--json")
    $ids["run"] = $run.result.run.id
  }
  Write-Host "Run: $($ids['run'])"
  foreach ($t in $tasks) {
    if ($ids[$t.id]) { Write-Host "$($t.id) exists -> $($ids[$t.id])"; continue }
    $depIds = @($t.deps | ForEach-Object { $ids[$_] } | Where-Object { $_ })
    $cli = @("orchestration", "task-create", "--spec", $t.spec, "--task-title", $t.title, "--display-name", $t.id, "--run", $ids["run"], "--json")
    if ($depIds.Count) { $cli += @("--deps", ("[" + (($depIds | ForEach-Object { '\"' + $_ + '\"' }) -join ",") + "]")) }
    $res = Invoke-Orca $cli
    $ids[$t.id] = $res.result.task.id
    Write-Host "$($t.id) -> $($ids[$t.id])"
    $ids | ConvertTo-Json | Set-Content -Encoding utf8 $stateFile
  }
}

$zaiEnv = Join-Path $env:USERPROFILE ".designdna\zai.env"
foreach ($id in $Start) {
  $t = $tasks | Where-Object { $_.id -eq $id }
  if (-not $t) { Write-Warning "unknown task $id"; continue }
  $taskId = $ids[$id]
  if ($t.agent -eq "glm") {
    if (-not (Test-Path $zaiEnv)) {
      Write-Warning "${id}: ключ z.ai не найден ($zaiEnv) — запустите на Codex: worker-start --task $taskId --worktree new-child --agent codex --model gpt-5.6-sol --effort medium"
      continue
    }
    $token = (Get-Content $zaiEnv | Where-Object { $_ -match "^ANTHROPIC_AUTH_TOKEN=" }) -replace "^ANTHROPIC_AUTH_TOKEN=", ""
    $wt = Invoke-Orca @("worktree", "create", "--name", "ds-$($id.ToLower())", "--parent-worktree", "active", "--json")
    $wtId = $wt.result.worktree.id
    $cmd = "`$env:ANTHROPIC_BASE_URL='https://api.z.ai/api/anthropic'; `$env:ANTHROPIC_AUTH_TOKEN='$token'; `$env:ANTHROPIC_MODEL='glm-5.3'; claude"
    $term = Invoke-Orca @("terminal", "create", "--worktree", "id:$wtId", "--title", "GLM $id", "--command", $cmd, "--json")
    $handle = $term.result.terminal.handle
    Invoke-Orca @("terminal", "wait", "--terminal", $handle, "--for", "tui-idle", "--timeout-ms", "120000", "--json") | Out-Null
    $d = Invoke-Orca @("orchestration", "dispatch", "--task", $taskId, "--to", $handle, "--inject", "--json")
    Write-Host "$id (GLM) dispatched: $($d.result.dispatch.id)"
  } else {
    $cli = @("orchestration", "worker-start", "--task", $taskId, "--worktree", "new-child", "--name", "ds-$($id.ToLower())", "--agent", $t.agent, "--model", $t.model, "--timeout-ms", "600000", "--json")
    if ($t.effort) { $cli += @("--effort", $t.effort) }
    $w = Invoke-Orca $cli
    Write-Host "$id ($($t.agent) $($t.model)) started: dispatch $($w.result.dispatch.id)"
  }
}
Write-Host "Далее: orca orchestration check --wait --timeout-ms 600000 --json ; orca orchestration worker-read --dispatch <id> --json"
