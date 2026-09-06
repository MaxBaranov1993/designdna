<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy, flowDesignSystemPicker, flowDesignSystems, flowEdges, flowNodes } from "../flow/state";
  import { pinnedDesignSystemRef } from "../flow/store";
  import { pullInput } from "../flow/dataflow";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { GeneratorFlowNode, GeneratorNodeData } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Генератор» — run-based: бриф тянет из входов prompt/style (pull-based,
   * fallback ownPrompt), POST /api/generate (payload — зеркало runGenerator,
   * nodes.js:498-518). Варианты — миниатюрами, активный — в IrPreview и на
   * выход ir (outValue). Пресеты стиля сняты по хендоффу: стиль приходит
   * из style DNA источника. */
  let { id, data, selected }: NodeProps<GeneratorFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  /* ДС по проводу (порт designSystem) — граф говорит, от какой системы
   * генерировать: загруженной файлом или собранной из Source. Без провода —
   * глобальный выбор проекта, иначе strict-ошибки выглядят беспричинными. */
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
    designSystem?: { name?: string; usageMode?: string; componentsAvailable?: number; mastersInContext?: string[]; pinnedMaster?: string | null; strictReady?: boolean; errors?: number; warnings?: number; recovered?: unknown } | null;
    variants?: LogVariant[];
  };
  let generationLog = $derived((data.generationLog || null) as GenerationLog | null);
  let logOpen = $state(false);
  let activeLog = $derived(generationLog?.variants?.[data.active] || null);
  let lintWarnings = $derived((activeLog?.lint || []).filter((v) => v.severity === "warning"));
  let lintErrors = $derived((activeLog?.lint || []).filter((v) => v.severity !== "warning"));
  let activeIr = $derived(data.variants.length ? data.variants[data.active] || null : null);
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
  let activeReview = $derived(generatorData.qualityReviews?.[data.active] || null);
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
  <InPorts type="generator" />
  <textarea
    class="f-own nodrag nowheel"
    placeholder="Свой промпт (если нет провода)"
    value={data.ownPrompt}
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(`generator:${id}:ownPrompt`, () => $flow.setNodeData(Number(id), { ownPrompt: value }));
    }}
    onblur={() => flushNodeText(`generator:${id}:ownPrompt`)}
  ></textarea>
  <div class="generator-model-row">
    <ProviderPicker
      provider={data.provider || "openai"}
      {effort}
      onChange={(next) => $flow.setNodeData(Number(id), next)}
    />
  </div>
  <details class="gen-design-options nodrag nowheel">
    <summary>Задача и направление</summary>
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
  </details>
  {#if generationLog?.policy?.surfaceLabel}
    <div class="gen-policy-summary nodrag" role="status">{generationLog.policy.surfaceLabel} · {generationLog.policy.effectiveMode === "freeform" ? "самостоятельный дизайн" : generationLog.policy.effectiveMode}</div>
  {/if}
  {#if dsRef}
    <div class="gen-ds-row nodrag" data-ds-source={dsRef.wired ? "wire" : "project"}
      title={dsRef.wired ? "Дизайн-система пришла по проводу: генерация собирается из её токенов и мастеров" : "Дизайн-система придёт в генерацию из глобального выбора проекта"}>
      <span class="gen-ds-label">◈ ДС: {dsName} · {dsRef.wired ? "провод" : "проект"}</span>
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
  <div class="ctl-row">
    <select
      class="f-count nodrag"
      value={String(count)}
      onchange={(e) => $flow.setNodeData(Number(id), { count: Number(e.currentTarget.value) })}
    >
      <option value="1">1</option>
      <option value="2">2</option>
    </select>
    <button
      class="btn-node primary small f-run nodrag"
      disabled={busy}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{:else}<span>▶</span>{/if} Сгенерировать
    </button>
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
          <IrPreview ir={v} height={96} empty="" />
        </div>
      {/each}
    </div>
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
  {#if hasReference}
    <div class="gen-ref-row nodrag" title="Экраны с порта reference уйдут в промпт как паттерн: те же мастера, плотность и роли текста">▣ Референс-экраны подключены</div>
  {/if}
  <IrPreview class="f-preview" ir={activeIr} height={180} empty="Варианты появятся после запуска" />
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
              · мастеров доступно {generationLog.designSystem.componentsAvailable ?? 0}, в контексте {(generationLog.designSystem.mastersInContext || []).length}
              {#if generationLog.designSystem.errors}· отказов strict {generationLog.designSystem.errors}{/if}
              {#if generationLog.designSystem.recovered}· материализован точный мастер{/if}
            </dd>
            {#if (generationLog.designSystem.mastersInContext || []).length}
              <dt>Мастера в контексте</dt><dd>{(generationLog.designSystem.mastersInContext || []).join(", ")}</dd>
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
  <div class="gen-actions">
    <button class="btn-node small f-to-editor nodrag" onclick={() => $flow.sendToNode(Number(id), "edit")}>
      → Editor
    </button>
    <button class="btn-node small f-to-reference nodrag" onclick={() => $flow.sendToNode(Number(id), "reference")}>
      → Reference
    </button>
    <button class="btn-node small nodrag" title="Запомнить как удачный вариант" disabled={busy || !activeIr} onclick={() => void $flow.recordVariantTaste(Number(id), "accepted")}>
      ✓ Принять
    </button>
    <button class="btn-node small nodrag" title="Запомнить как неудачный вариант" disabled={busy || !activeIr} onclick={() => void $flow.recordVariantTaste(Number(id), "rejected")}>
      × Отклонить
    </button>
    <button class="btn-node small primary nodrag" title="Сделать этот вариант дизайн-системой" disabled={busy || !activeIr} onclick={() => void $flow.promoteVariantToDesignSystem(Number(id))}>
      ◈ Закрепить стиль
    </button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="generator" />
</NodeShell>

<style>
  .gen-design-options { font-size: 11px; padding: 6px 0; }
  .gen-design-options summary { cursor: pointer; padding: 4px 0; }
  .gen-design-options label { display: grid; gap: 4px; margin: 8px 0; }
  .gen-design-options select { width: 100%; min-height: 30px; padding: 4px 8px; color: inherit; background: var(--dna-sunken); border: 1px solid var(--dna-border); border-radius: 5px; }
  .gen-design-options select:focus-visible { outline: 2px solid var(--n-accent); outline-offset: 2px; }
  .gen-design-options small, .gen-policy-summary { font-size: 10px; line-height: 1.4; color: var(--dna-muted); }
  .direction-picker { display: grid; gap: 6px; }
  .direction-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--dna-muted); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
  .direction-all, .direction-chip { border: 1px solid var(--dna-border); background: var(--dna-sunken); color: inherit; cursor: pointer; }
  .direction-all { border-radius: 999px; padding: 3px 8px; font-size: 10px; text-transform: none; letter-spacing: 0; }
  .direction-chips { display: grid; gap: 5px; }
  .direction-chip { display: grid; gap: 2px; width: 100%; border-radius: 8px; padding: 7px 8px; text-align: left; }
  .direction-chip strong { font-size: 11px; }
  .direction-chip span, .direction-chip small { color: var(--dna-muted); font-size: 10px; line-height: 1.3; }
  .direction-chip.active, .direction-all.active { border-color: var(--dna-violet-l); background: rgba(155, 92, 255, .1); box-shadow: 0 0 0 2px rgba(155, 92, 255, .12); }
  .direction-chip:disabled, .direction-all:disabled { cursor: default; opacity: .65; }
  .revision-status { border: 1px solid rgba(239, 68, 68, .35); border-radius: 8px; background: rgba(239, 68, 68, .08); padding: 8px; color: #b91c1c; font-size: 10px; line-height: 1.35; }
  .revision-status ul { margin: 4px 0 0; padding-left: 16px; }
  .tbadge { max-width: calc(100% - 8px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .gen-ds-mode { flex: none; border: 1px solid var(--dna-border); border-radius: 6px; background: var(--dna-sunken); color: inherit; font-size: 10px; padding: 2px 4px; }
  .gen-ds-warn { border: 1px solid rgba(245, 166, 35, .4); border-radius: 8px; background: rgba(245, 166, 35, .08); padding: 6px 8px; color: var(--dna-amber); font-size: 10px; line-height: 1.35; }
  .gen-ref-row { color: var(--dna-muted); font-size: 10px; }
  .gen-log { border: 1px solid var(--dna-border); border-radius: 8px; background: var(--dna-sunken); font-size: 10px; }
  .gen-log-head { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; border: 0; background: transparent; color: var(--dna-text-2); padding: 6px 8px; cursor: pointer; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; font-size: 9.5px; }
  .gen-log-sum { color: var(--dna-muted); font-weight: 600; text-transform: none; letter-spacing: 0; }
  .gen-log-body { display: grid; grid-template-columns: auto 1fr; gap: 3px 8px; margin: 0; padding: 0 8px 8px; }
  .gen-log-body dt { color: var(--dna-dim); }
  .gen-log-body dd { margin: 0; color: var(--dna-text-2); line-height: 1.35; overflow-wrap: anywhere; }
  .gen-log-body ul { margin: 0; padding-left: 12px; }
</style>
