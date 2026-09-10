<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy, flowDesignSystemPicker, flowDesignSystems, flowEdges, flowNodes } from "../flow/state";
  import { pinnedDesignSystemRef } from "../flow/store";
  import { generatorInputKey } from "../flow/generator-inputs";
  import { flowActivePageId } from "../flow/state";
  import { pullInput } from "../flow/dataflow";
  import type { GeneratorFlowNode, GeneratorNodeData } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Генератор» — результат-первый: превью активного варианта как герой,
   * миниатюры вариантов и арт-дирекция под ним, строка модели, футер
   * «Сгенерировать». Свой промпт, тип экрана, направление, ДС и действия
   * с вариантом живут в инспекторе (GeneratorParams). Бриф тянет из входов
   * prompt/style (pull-based, fallback ownPrompt), POST /api/generate. */
  let { id, data, selected }: NodeProps<GeneratorFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  let selfNode = $derived($flowNodes.find((node) => Number(node.id) === Number(id)) || null);
  let wiredDs = $derived.by(() => {
    if (!selfNode) return null;
    const raw = pullInput($flowNodes, $flowEdges, selfNode, "designSystem") as
      { systemId?: string; status?: string; name?: string; revision?: number } | null;
    return raw && raw.systemId ? raw : null;
  });
  let hasReference = $derived.by(() => {
    if (!selfNode) return false;
    const raw = pullInput($flowNodes, $flowEdges, selfNode, "reference") as { tree?: unknown } | null;
    return !!(raw && Array.isArray(raw.tree));
  });
  let pinnedRef = $derived(pinnedDesignSystemRef(
    data as unknown as Record<string, unknown>,
    $flowDesignSystems,
    $flowDesignSystemPicker,
  ));
  let usageMode = $derived(String(data.designSystemUsageMode || $flowDesignSystemPicker?.usageMode || "strict"));
  let dsRef = $derived(wiredDs
    ? { systemId: wiredDs.systemId, usageMode, wired: true, published: wiredDs.status === "published" }
    : pinnedRef ? { ...pinnedRef, usageMode, wired: false, published: true } : null);
  let dsId = $derived(dsRef ? String(dsRef.systemId || "") : "");
  let dsName = $derived(
    wiredDs ? String(wiredDs.name || wiredDs.systemId || "")
      : dsId ? ($flowDesignSystems.systems?.find((s) => s.systemId === dsId)?.name || dsId) : "",
  );
  let dsOptedOut = $derived(!wiredDs && String((data as Record<string, unknown>).designSystemSelection || "") === "none");
  type LogVariant = { index?: number; autofixes?: number; journal?: string[]; lint?: { rule: string; severity?: string; path?: string; message?: string }[] };
  type GenerationLog = {
    policy?: { surfaceLabel?: string; effectiveMode?: string; version?: string };
    product?: string; tokensLocked?: boolean; projectRules?: boolean; referenceScreens?: number; strictFallback?: string;
    designSystem?: {
      name?: string; usageMode?: string; componentsAvailable?: number; mastersInContext?: string[];
      summariesInContext?: string[]; decorSignatures?: string[]; archetypeSelection?: string;
      estimatedTokens?: number; tokenBudget?: number;
      referenceImages?: Array<{ kind?: string; componentKey?: string; label?: string; attached?: boolean; skipped?: string }>;
      identityScores?: Array<number | null>; artDirectionAware?: boolean;
      pinnedMaster?: string | null; strictReady?: boolean; errors?: number; warnings?: number; recovered?: unknown;
    } | null;
    variants?: LogVariant[];
  };
  let generationLog = $derived((data.generationLog || null) as GenerationLog | null);
  let logOpen = $state(false);
  let activeLog = $derived(generationLog?.variants?.[data.active] || null);
  let lintWarnings = $derived((activeLog?.lint || []).filter((v) => v.severity === "warning"));
  let lintErrors = $derived((activeLog?.lint || []).filter((v) => v.severity !== "warning"));
  let activeIr = $derived(data.variants.length ? data.variants[data.active] || null : null);
  function emptyContainer(node: any): boolean {
    if (!node || !["composition", "frame"].includes(node.type)) return false;
    if (["heading", "title", "text", "subheading"].some(key => node.props?.[key])) return false;
    if (["background", "backgroundColor", "backgroundImage", "borderColor", "boxShadow"].some(key => ![undefined, null, "", "none", "transparent"].includes(node.style?.[key]))) return false;
    return (node.children || []).every(emptyContainer);
  }
  let emptyResult = $derived(!!activeIr && (!Array.isArray(activeIr.tree) || !activeIr.tree.length || activeIr.tree.every(emptyContainer)));
  let effort = $derived(["medium", "high", "max"].includes(data.effort) ? data.effort : "medium");
  let count = $derived(Math.max(1, Math.min(2, Number(data.count) || 1)));
  type Direction = { id: string; label: string; motivation: string; tradeoff: string };
  type QualityReview = { score: number | null; passed: boolean | null; reasons: string[] };
  let generatorData = $derived(data as unknown as GeneratorNodeData & {
    directions?: Direction[];
    selectedDirection?: string;
    variantDirections?: string[];
    qualityReviews?: QualityReview[];
  });
  let directions = $derived(Array.isArray(generatorData.directions) ? generatorData.directions.slice(0, 3) : []);
  let selectedDirection = $derived(generatorData.selectedDirection || "all");
  let resultCurrent = $derived(!!selfNode && data.generationContext?.pageId === $flowActivePageId
    && data.generationContext?.inputKey === generatorInputKey($flowNodes, $flowEdges, selfNode, $flowDesignSystemPicker));
  let activeReview = $derived(!busy && resultCurrent ? generatorData.qualityReviews?.[data.active] || null : null);
  const surfaceOptions = [
    ["auto", "Определить по задаче"], ["landing", "Лендинг"], ["catalog", "Поиск и каталог"],
    ["detail", "Карточка объекта"], ["checkout", "Запись и оформление"], ["dashboard", "Кабинет и аналитика"],
    ["form", "Форма и настройки"], ["editor", "Редактор"], ["ai-workspace", "AI-интерфейс"],
    ["article", "Статья и журнал"], ["feed", "Лента"], ["component", "Один компонент"],
  ];
  const styleOptions = [
    ["auto", "По задаче и дизайн-системе"], ["minimal", "Спокойный минимализм"], ["enterprise", "Информационный"],
    ["marketplace", "Поиск на первом месте"], ["editorial", "Редакционный"], ["swiss", "Строгая сетка"],
    ["product-led", "Демонстрация продукта"], ["luxury", "Сдержанный предметный"], ["organic", "Материальный"],
    ["playful", "Иллюстративный"], ["brutal", "Плакатный"], ["industrial", "Технический"],
    ["soft-pastel", "Мягкая палитра"], ["bento", "Модульный"], ["glass", "Многослойный"],
    ["immersive", "Иммерсивный"], ["retro", "Ретро"],
  ];

  async function selectDirection(direction: string) {
    if (busy || direction === selectedDirection) return;
    $flow.setNodeData(Number(id), { selectedDirection: direction } as unknown as Partial<GeneratorNodeData>);
    try {
      await fetch("/api/project/taste/outcome", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "accepted",
          payload: { style: { tags: [`art-direction:${direction}`] } },
        }),
      });
    } catch {
      // Выбор уже сохранён в проекте; недоступная Taste Memory не блокирует UI.
    }
  }
</script>

<NodeShell {id} type="generator" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      <select
        class="f-count gen-count nodrag"
        aria-label="Число вариантов"
        title="Число вариантов"
        value={String(count)}
        onchange={(e) => $flow.setNodeData(Number(id), { count: Number(e.currentTarget.value) })}
      >
        <option value="1">1 вариант</option>
        <option value="2">2 варианта</option>
      </select>
    </div>
    <div class="foot-right">
      <button class="btn-node primary small f-run nodrag" disabled={busy} onclick={() => $flow.runNode(Number(id))}>
        {#if busy}<span class="spinner"></span>{:else}<span>▶</span>{/if} Сгенерировать
      </button>
    </div>
  {/snippet}
  <InPorts type="generator" />
  {#if activeIr && (!resultCurrent || busy)}
    <div class="dna-field-hint" style="padding: 8px 12px">{busy ? "Идёт новый запуск · оценка появится после проверки" : "Результат предыдущего запуска · запустите ноду для текущего промпта"}</div>
  {/if}
  <div class="n-hero nodrag">
    <IrPreview class="f-preview" ir={emptyResult ? null : activeIr} height={220} fitHeight empty={emptyResult ? "В прошлом ответе нет содержимого макета" : "Варианты появятся после запуска"} />
    {#if data.variants.length > 1}
      <span class="n-hero-tag">{data.active + 1} / {data.variants.length}</span>
    {/if}
  </div>
  {#if data.variants.length}
    <div class="thumbs">
      {#each data.variants as v, i (i)}
        <div
          class={"thumb nodrag" + (i === data.active ? " active" : "")}
          title={generatorData.variantDirections?.[i] || directions[i]?.label || `Направление ${i + 1}`}
          role="button"
          tabindex="0"
          onkeydown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            if (busy) return;
            $flow.setNodeData(Number(id), { active: i });
            $flow.propagate(Number(id));
          }}
          onclick={() => {
            if (busy) return;
            $flow.setNodeData(Number(id), { active: i });
            $flow.propagate(Number(id));
          }}
        >
          <span class="tbadge">{generatorData.variantDirections?.[i] || directions[i]?.label || `Направление ${i + 1}`}</span>
          <IrPreview ir={v} height={72} empty="" />
        </div>
      {/each}
    </div>
  {/if}
  {#if directions.length}
    <section class="direction-picker nodrag" aria-label="Направление арт-дирекции">
      <div class="direction-heading">
        <span>Арт-дирекция</span>
        <button
          class:active={selectedDirection === "all"}
          class="direction-all"
          type="button"
          disabled={busy}
          onclick={() => void selectDirection("all")}
        >Все направления</button>
      </div>
      <div class="direction-chips">
        {#each directions as direction (direction.id)}
          <button
            type="button"
            class:active={selectedDirection === direction.id}
            class="direction-chip"
            data-direction-id={direction.id}
            disabled={busy}
            aria-pressed={selectedDirection === direction.id}
            onclick={() => void selectDirection(direction.id)}
          >
            <strong>{direction.label}</strong>
            {#if direction.motivation}<span>{direction.motivation}</span>{/if}
            {#if direction.tradeoff}<small>Компромисс: {direction.tradeoff}</small>{/if}
          </button>
        {/each}
      </div>
    </section>
  {/if}
  {#if activeReview && activeReview.passed === null}
    <div class="gen-policy-summary nodrag" role="status">Предпросмотр создан. Визуальная проверка не завершена.</div>
  {:else if activeReview && activeReview.passed === false}
    <div class="revision-status nodrag" role="status">
      <strong>Нужна доработка{activeReview.score == null ? "" : ` · ${activeReview.score}/100`}</strong>
      {#if activeReview.reasons.length}
        <ul>
          {#each activeReview.reasons as reason}
            <li>{reason}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
  <div class="generator-model-row">
    <ProviderPicker
      provider={data.provider || "openai"}
      {effort}
      onChange={(next) => $flow.setNodeData(Number(id), next)}
    />
  </div>
  {#if dsRef}
    <div class="gen-ds-row nodrag" data-ds-source={dsRef.wired ? "wire" : "project"}
      title={dsRef.wired ? "Дизайн-система пришла по проводу: генерация собирается из её токенов и мастеров" : "Дизайн-система придёт в генерацию из глобального выбора проекта"}>
      <span class="gen-ds-label">◈ {dsName} · {dsRef.wired ? "провод" : "проект"}</span>
      <select
        class="gen-ds-mode f-ds-mode"
        title="Режим: strict — только мастера и токены; extend — мастера + новое в токенах; style-only — токены и характер"
        value={usageMode}
        onchange={(e) => $flow.setNodeData(Number(id), { designSystemUsageMode: e.currentTarget.value })}
      >
        <option value="strict">strict</option>
        <option value="extend">extend</option>
        <option value="style-only">style-only</option>
      </select>
      {#if !dsRef.wired}
        <button
          class="gen-ds-off"
          title="Генерировать без дизайн-системы"
          onclick={() => $flow.setNodeData(Number(id), { designSystemSelection: "none" })}
        >×</button>
      {/if}
    </div>
    {#if dsRef.wired && !dsRef.published}
      <div class="gen-ds-warn nodrag" role="status">ДС черновик — опубликуется автоматически при запуске.</div>
    {/if}
  {:else if dsOptedOut}
    <div class="gen-ds-row nodrag">
      <span class="gen-ds-label">ДС отключена для этой ноды</span>
      <button
        class="gen-ds-off"
        title="Вернуть дизайн-систему проекта"
        onclick={() => $flow.setNodeData(Number(id), { designSystemSelection: "inherit" })}
      >↺</button>
    </div>
  {/if}
  {#if hasReference}
    <div class="gen-ref-row nodrag" title="Экраны с порта reference уйдут в промпт как паттерн: те же мастера, плотность и роли текста">▣ Референс-экраны подключены</div>
  {/if}
  <details class="n-details gen-design-options nodrag nowheel">
    <summary>Задача и направление{generationLog?.policy?.surfaceLabel ? ` · ${generationLog.policy.surfaceLabel}` : ""}</summary>
    <div class="gen-design-body">
      <label>Тип экрана
        <select aria-label="Тип экрана" disabled={busy} value={data.surface || "auto"}
          onchange={(event) => $flow.setNodeData(Number(id), { surface: event.currentTarget.value, selectedDirection: "all", directions: [] })}>
          {#each surfaceOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
        </select>
      </label>
      <label>Визуальное направление
        <select aria-label="Визуальное направление" disabled={busy || !!dsRef} value={data.designStyle || "auto"}
          onchange={(event) => $flow.setNodeData(Number(id), { designStyle: event.currentTarget.value, selectedDirection: "all" })}>
          {#each styleOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
        </select>
      </label>
      <small>{dsRef ? "Внешний вид задаёт выбранная дизайн-система." : "Без дизайн-системы генератор создаст согласованные основы под задачу."}</small>
    </div>
  </details>
  {#if generationLog}
    <section class="gen-log nodrag f-gen-log" aria-label="Журнал решений генерации">
      <button type="button" class="gen-log-head" onclick={() => (logOpen = !logOpen)} aria-expanded={logOpen}>
        <span>Журнал решений</span>
        <span class="gen-log-sum">
          {#if generationLog.designSystem}◈ {generationLog.designSystem.usageMode}{/if}
          {#if generationLog.strictFallback}· fallback {generationLog.strictFallback}{/if}
          {#if activeLog}· автофиксов {activeLog.autofixes || 0} · линт {lintWarnings.length}{lintErrors.length ? ` · ошибок ${lintErrors.length}` : ""}{/if}
          {logOpen ? " ▴" : " ▾"}
        </span>
      </button>
      {#if logOpen}
        <dl class="gen-log-body">
          <dt>Тип продукта</dt><dd>{generationLog.product || "—"}</dd>
          <dt>Токены</dt><dd>{generationLog.tokensLocked ? "залочены из ДС / style DNA" : "подобраны из design KB"}</dd>
          {#if generationLog.designSystem}
            <dt>Дизайн-система</dt>
            <dd>{generationLog.designSystem.name || "—"} · {generationLog.designSystem.usageMode}
              · мастеров доступно {generationLog.designSystem.componentsAvailable ?? 0}, точных в контексте {(generationLog.designSystem.mastersInContext || []).length}
              {#if (generationLog.designSystem.summariesInContext || []).length}· сводок {(generationLog.designSystem.summariesInContext || []).length}{/if}
              {#if (generationLog.designSystem.decorSignatures || []).length}· декор-сигнатур {(generationLog.designSystem.decorSignatures || []).length}{/if}
              {#if generationLog.designSystem.estimatedTokens}· контекст ≈{generationLog.designSystem.estimatedTokens}/{generationLog.designSystem.tokenBudget} ток.{/if}
              {#if generationLog.designSystem.errors}· отказов strict {generationLog.designSystem.errors}{/if}
              {#if generationLog.designSystem.recovered}· материализован точный мастер{/if}
            </dd>
            {#if (generationLog.designSystem.mastersInContext || []).length}
              <dt>Мастера в контексте</dt><dd>{(generationLog.designSystem.mastersInContext || []).join(", ")}</dd>
            {/if}
            {#if (generationLog.designSystem.referenceImages || []).length}
              <dt>Референсы ДС</dt>
              <dd>{(generationLog.designSystem.referenceImages || []).map((item) => `${item.attached === false ? "✗ " : ""}${item.label || item.componentKey || ""}${item.skipped ? ` (${item.skipped})` : ""}`).join("; ")}</dd>
            {/if}
            {#if (generationLog.designSystem.identityScores || []).some((score) => typeof score === "number")}
              <dt>Identity</dt>
              <dd>{(generationLog.designSystem.identityScores || []).map((score, i) => `вариант ${i + 1}: ${typeof score === "number" ? `${score}/100` : "—"}`).join(", ")}{(generationLog.designSystem.identityScores || []).some((score) => typeof score === "number" && score < 70) ? " · ниже 70: результат отходит от характера системы" : ""}</dd>
            {/if}
            {#if generationLog.designSystem.pinnedMaster}
              <dt>Референс</dt><dd>пиннутый мастер: {generationLog.designSystem.pinnedMaster}</dd>
            {/if}
            {#if generationLog.strictFallback}
              <dt>Strict fallback</dt><dd>{generationLog.strictFallback === "extend" ? "мастера не использованы, результат принят в режиме extend" : generationLog.strictFallback}</dd>
            {/if}
          {:else}
            <dt>Дизайн-система</dt><dd>не подключена</dd>
          {/if}
          <dt>Правила проекта</dt><dd>{generationLog.projectRules ? "применены" : "не заданы"}</dd>
          <dt>Референс-экраны</dt><dd>{generationLog.referenceScreens || 0}</dd>
          {#if activeLog}
            {#if (activeLog.journal || []).length}
              <dt>Автофиксы</dt>
              <dd><ul>{#each (activeLog.journal || []).slice(0, 8) as line}<li>{line}</li>{/each}</ul></dd>
            {/if}
            {#if lintWarnings.length || lintErrors.length}
              <dt>DS-lint</dt>
              <dd><ul>{#each [...lintErrors, ...lintWarnings].slice(0, 8) as v}<li><b>{v.rule}</b> {v.message}</li>{/each}</ul></dd>
            {/if}
          {/if}
        </dl>
      {/if}
    </section>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="generator" />
</NodeShell>

<style>
  .gen-count { width: auto; padding: 4px 6px; font-size: 11px; color: var(--dna-muted); background: transparent; border-color: transparent; }
  .gen-count:hover { border-color: var(--dna-border); }
  .gen-design-body { display: grid; gap: 6px; }
  .gen-design-body label { display: grid; gap: 4px; font-size: 10.5px; color: var(--dna-muted); }
  .gen-design-body select { width: 100%; min-height: 28px; padding: 4px 8px; color: var(--dna-text-2); background: var(--dna-node); border: 1px solid var(--dna-border); border-radius: 6px; font-size: 11px; }
  .gen-design-body select:focus-visible { outline: 2px solid var(--dna-text); outline-offset: 2px; }
  .gen-design-body small, .gen-policy-summary { font-size: 10px; line-height: 1.4; color: var(--dna-muted); }
  .direction-picker { display: grid; gap: 6px; }
  .direction-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--dna-dim); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
  .direction-all, .direction-chip { border: 1px solid var(--dna-border); background: transparent; color: inherit; cursor: pointer; }
  .direction-all { border-radius: 999px; padding: 3px 8px; font-size: 10px; text-transform: none; letter-spacing: 0; color: var(--dna-muted); }
  .direction-chips { display: grid; gap: 5px; }
  .direction-chip { display: grid; gap: 2px; width: 100%; border-radius: 8px; padding: 7px 8px; text-align: left; }
  .direction-chip strong { font-size: 11px; }
  .direction-chip span, .direction-chip small { color: var(--dna-muted); font-size: 10px; line-height: 1.3; }
  .direction-chip.active, .direction-all.active { border-color: var(--dna-text); background: color-mix(in srgb, var(--dna-text), transparent 92%); color: var(--dna-text); }
  .direction-chip:disabled, .direction-all:disabled { cursor: default; opacity: .65; }
  .revision-status { border: 1px solid color-mix(in srgb, var(--dna-danger), transparent 65%); border-radius: 8px; background: color-mix(in srgb, var(--dna-danger), transparent 90%); padding: 8px; color: var(--dna-danger-text); font-size: 10px; line-height: 1.35; }
  .revision-status ul { margin: 4px 0 0; padding-left: 16px; }
  .tbadge { max-width: calc(100% - 8px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .gen-ds-mode { flex: none; border: 1px solid var(--dna-border); border-radius: 6px; background: var(--dna-node); color: inherit; font-size: 10px; padding: 2px 4px; }
  .gen-ds-warn { border: 1px solid color-mix(in srgb, var(--dna-amber), transparent 60%); border-radius: 8px; background: color-mix(in srgb, var(--dna-amber), transparent 92%); padding: 6px 8px; color: var(--dna-amber); font-size: 10px; line-height: 1.35; }
  .gen-ref-row { color: var(--dna-muted); font-size: 10px; }
  .gen-log { border: 1px solid var(--dna-border); border-radius: 8px; background: var(--dna-sunken); font-size: 10px; }
  .gen-log-head { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; border: 0; background: transparent; color: var(--dna-muted); padding: 7px 9px; cursor: pointer; font-weight: 700; font-size: 10.5px; }
  .gen-log-head:hover { color: var(--dna-text); }
  .gen-log-sum { color: var(--dna-dim); font-weight: 600; }
  .gen-log-body { display: grid; grid-template-columns: auto 1fr; gap: 3px 8px; margin: 0; padding: 0 9px 9px; }
  .gen-log-body dt { color: var(--dna-dim); }
  .gen-log-body dd { margin: 0; color: var(--dna-text-2); line-height: 1.35; overflow-wrap: anywhere; }
  .gen-log-body ul { margin: 0; padding-left: 12px; }
</style>
