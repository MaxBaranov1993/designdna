<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import AssetRunDetails from "../components/AssetRunDetails.svelte";
  import ConceptRunDetails from "../components/ConceptRunDetails.svelte";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy, flowDesignSystemPicker, flowDesignSystems, flowEdges, flowNodes } from "../flow/state";
  import { pinnedDesignSystemRef } from "../flow/store";
  import { generatorInputKey } from "../flow/generator-inputs";
  import { flowActivePageId } from "../flow/state";
  import { pullInput } from "../flow/dataflow";
  import { nodeInputHint } from "../flow/node-readiness";
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
  let inputHint = $derived(nodeInputHint($flowNodes, $flowEdges, selfNode));
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
    ["auto", "Infer from task"], ["landing", "Landing page"], ["catalog", "Search and catalog"],
    ["detail", "Detail page"], ["checkout", "Booking and checkout"], ["dashboard", "Dashboard and analytics"],
    ["form", "Form and settings"], ["editor", "Editor"], ["ai-workspace", "AI interface"],
    ["article", "Article and journal"], ["feed", "Feed"], ["component", "Single component"],
  ];
  const styleOptions = [
    ["auto", "From task and design system"], ["minimal", "Quiet minimalism"], ["enterprise", "Information-focused"],
    ["marketplace", "Search-first"], ["editorial", "Editorial"], ["swiss", "Strict grid"],
    ["product-led", "Product showcase"], ["luxury", "Restrained and tangible"], ["organic", "Material"],
    ["playful", "Illustrative"], ["brutal", "Poster"], ["industrial", "Technical"],
    ["soft-pastel", "Soft palette"], ["bento", "Modular"], ["glass", "Layered"],
    ["immersive", "Immersive"], ["retro", "Retro"],
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
        aria-label="Number of variants"
        title="Number of variants"
        value={String(count)}
        onchange={(e) => $flow.setNodeData(Number(id), { count: Number(e.currentTarget.value) })}
      >
        <option value="1">1 variant</option>
        <option value="2">2 variants</option>
      </select>
    </div>
    <div class="foot-right">
      <button class="btn-node primary small f-run nodrag" disabled={busy || !!inputHint} title={inputHint || "Generate variants"} onclick={() => $flow.runNode(Number(id))}>
        {#if busy}<span class="spinner"></span>{:else}<span>▶</span>{/if} Generate
      </button>
    </div>
  {/snippet}
  <InPorts type="generator" />
  {#if activeIr && (!resultCurrent || busy)}
    <div class="dna-field-hint" style="padding: 8px 12px">{busy ? "New run in progress · score appears after verification" : "Previous run result · run the node for the current prompt"}</div>
  {/if}
  <div class="n-hero nodrag">
    <IrPreview class="f-preview" ir={emptyResult ? null : activeIr} height={220} fitHeight empty={emptyResult ? "Previous response contains no layout content" : "Variants appear after running"} />
    {#if data.variants.length > 1}
      <span class="n-hero-tag">{data.active + 1} / {data.variants.length}</span>
    {/if}
  </div>
  {#if data.variants.length}
    <div class="thumbs">
      {#each data.variants as v, i (i)}
        <div
          class={"thumb nodrag" + (i === data.active ? " active" : "")}
          title={generatorData.variantDirections?.[i] || directions[i]?.label || `Direction ${i + 1}`}
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
          <span class="tbadge">{generatorData.variantDirections?.[i] || directions[i]?.label || `Direction ${i + 1}`}</span>
          <IrPreview ir={v} height={72} empty="" />
        </div>
      {/each}
    </div>
  {/if}
  {#if directions.length}
    <section class="direction-picker nodrag" aria-label="Art direction">
      <div class="direction-heading">
        <span>Art direction</span>
        <button
          class:active={selectedDirection === "all"}
          class="direction-all"
          type="button"
          disabled={busy}
          onclick={() => void selectDirection("all")}
        >All directions</button>
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
            {#if direction.tradeoff}<small>Tradeoff: {direction.tradeoff}</small>{/if}
          </button>
        {/each}
      </div>
    </section>
  {/if}
  {#if activeReview && activeReview.passed === null}
    <div class="gen-policy-summary nodrag" role="status">Preview created. Visual verification incomplete.</div>
  {:else if activeReview && activeReview.passed === false}
    <div class="revision-status nodrag" role="status">
      <strong>Needs refinement{activeReview.score == null ? "" : ` · ${activeReview.score}/100`}</strong>
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
  <AssetRunDetails runs={data.assetRuns} generationStartedAt={data.generationContext?.startedAt} {busy} onRetry={(slotId) => void $flow.retryGeneratorAssets(Number(id), slotId)} />
  <ConceptRunDetails runs={data.conceptRuns} />
  {#if dsRef?.wired}
    {#if !dsRef.published}
      <div class="gen-ds-warn nodrag" role="status">DS draft — will publish automatically when run.</div>
    {/if}
  {:else if dsRef}
    <div class="gen-ds-row nodrag" data-ds-source="project"
      title="No Design system wire — using project default. Prefer wiring UI Kit → Design system.">
      <span class="gen-ds-label">◈ {dsName} · project</span>
      <select
        class="gen-ds-mode f-ds-mode"
        title="Mode: strict — masters and tokens only; extend — masters + new content; style-only — tokens and character"
        value={usageMode}
        onchange={(e) => $flow.setNodeData(Number(id), { designSystemUsageMode: e.currentTarget.value })}
      >
        <option value="strict">strict</option>
        <option value="extend">extend</option>
        <option value="style-only">style-only</option>
      </select>
      <button
        class="gen-ds-off"
        title="Generate without a design system"
        onclick={() => $flow.setNodeData(Number(id), { designSystemSelection: "none" })}
      >×</button>
    </div>
  {:else if dsOptedOut}
    <div class="gen-ds-row nodrag">
      <span class="gen-ds-label">DS disabled</span>
      <button
        class="gen-ds-off"
        title="Restore project design system"
        onclick={() => $flow.setNodeData(Number(id), { designSystemSelection: "inherit" })}
      >↺</button>
    </div>
  {/if}
  {#if hasReference}
    <div class="gen-ref-row nodrag" title="Screens from the reference port become prompt patterns: the same masters, density, and text roles">▣ Reference screens connected</div>
  {/if}
  <details class="n-details gen-design-options nodrag nowheel">
    <summary>Task and direction{generationLog?.policy?.surfaceLabel ? ` · ${generationLog.policy.surfaceLabel}` : ""}</summary>
    <div class="gen-design-body">
      <label>Screen type
        <select aria-label="Screen type" disabled={busy} value={data.surface || "auto"}
          onchange={(event) => $flow.setNodeData(Number(id), { surface: event.currentTarget.value, selectedDirection: "all", directions: [] })}>
          {#each surfaceOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
        </select>
      </label>
      <label>Visual direction
        <select aria-label="Visual direction" disabled={busy || !!dsRef} value={data.designStyle || "auto"}
          onchange={(event) => $flow.setNodeData(Number(id), { designStyle: event.currentTarget.value, selectedDirection: "all" })}>
          {#each styleOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
        </select>
      </label>
      <small>{dsRef ? "The selected design system defines the visual style." : "Without a design system, Generator creates consistent foundations for the task."}</small>
    </div>
  </details>
  {#if generationLog}
    <section class="gen-log nodrag f-gen-log" aria-label="Generation decision log">
      <button type="button" class="gen-log-head" onclick={() => (logOpen = !logOpen)} aria-expanded={logOpen}>
        <span>Decision log</span>
        <span class="gen-log-sum">
          {#if generationLog.designSystem}◈ {generationLog.designSystem.usageMode}{/if}
          {#if generationLog.strictFallback}· fallback {generationLog.strictFallback}{/if}
          {#if activeLog}· automatic fixes {activeLog.autofixes || 0} · lint {lintWarnings.length}{lintErrors.length ? ` · errors ${lintErrors.length}` : ""}{/if}
          {logOpen ? " ▴" : " ▾"}
        </span>
      </button>
      {#if logOpen}
        <dl class="gen-log-body">
          <dt>Product type</dt><dd>{generationLog.product || "—"}</dd>
          <dt>Tokens</dt><dd>{generationLog.tokensLocked ? "locked from Design System" : "selected from design KB"}</dd>
          {#if generationLog.designSystem}
            <dt>Design system</dt>
            <dd>{generationLog.designSystem.name || "—"} · {generationLog.designSystem.usageMode}
              · masters available {generationLog.designSystem.componentsAvailable ?? 0}, exact in context {(generationLog.designSystem.mastersInContext || []).length}
              {#if (generationLog.designSystem.summariesInContext || []).length}· summaries {(generationLog.designSystem.summariesInContext || []).length}{/if}
              {#if (generationLog.designSystem.decorSignatures || []).length}· decoration signatures {(generationLog.designSystem.decorSignatures || []).length}{/if}
              {#if generationLog.designSystem.estimatedTokens}· context ≈{generationLog.designSystem.estimatedTokens}/{generationLog.designSystem.tokenBudget} tokens{/if}
              {#if generationLog.designSystem.errors}· strict rejections {generationLog.designSystem.errors}{/if}
              {#if generationLog.designSystem.recovered}· exact master materialized{/if}
            </dd>
            {#if (generationLog.designSystem.mastersInContext || []).length}
              <dt>Masters in context</dt><dd>{(generationLog.designSystem.mastersInContext || []).join(", ")}</dd>
            {/if}
            {#if (generationLog.designSystem.referenceImages || []).length}
              <dt>DS references</dt>
              <dd>{(generationLog.designSystem.referenceImages || []).map((item) => `${item.attached === false ? "✗ " : ""}${item.label || item.componentKey || ""}${item.skipped ? ` (${item.skipped})` : ""}`).join("; ")}</dd>
            {/if}
            {#if (generationLog.designSystem.identityScores || []).some((score) => typeof score === "number")}
              <dt>Identity</dt>
              <dd>{(generationLog.designSystem.identityScores || []).map((score, i) => `variant ${i + 1}: ${typeof score === "number" ? `${score}/100` : "—"}`).join(", ")}{(generationLog.designSystem.identityScores || []).some((score) => typeof score === "number" && score < 70) ? " · below 70: result deviates from the system character" : ""}</dd>
            {/if}
            {#if generationLog.designSystem.pinnedMaster}
              <dt>Reference</dt><dd>pinned master: {generationLog.designSystem.pinnedMaster}</dd>
            {/if}
            {#if generationLog.strictFallback}
              <dt>Strict fallback</dt><dd>{generationLog.strictFallback === "extend" ? "masters were not used; result accepted in extend mode" : generationLog.strictFallback}</dd>
            {/if}
          {:else}
            <dt>Design system</dt><dd>not connected</dd>
          {/if}
          <dt>Project rules</dt><dd>{generationLog.projectRules ? "applied" : "not set"}</dd>
          <dt>Reference screens</dt><dd>{generationLog.referenceScreens || 0}</dd>
          {#if activeLog}
            {#if (activeLog.journal || []).length}
              <dt>Automatic fixes</dt>
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
  {#if inputHint}<div class="n-hint nodrag">{inputHint}</div>{/if}
  <NodeStatus {id} />
  <OutPorts {id} type="generator" />
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
