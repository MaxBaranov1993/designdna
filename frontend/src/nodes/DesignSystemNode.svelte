<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow, flowBusy, flowNodes, flowEdges } from "../flow/state";
  import type { DesignSystemFlowNode, SourceArtifact } from "../flow/types";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import { designSystemIdleStatus } from './designSystemStatus';

  /* Дизайн-система — результат-первый: имя системы в шапке, воронка
   * «источник → система» и метрики как содержимое, футер «Собрать» / «Открыть».
   * Загрузка JSON, автопубликация и AI-аккаунт — в инспекторе. */
  let { id, data, selected }: NodeProps<DesignSystemFlowNode> = $props();

  let summary = $derived((data.summary || {}) as Record<string, any>);
  let lastError = $derived(String(data.lastError || ""));
  let sourceArtifact = $derived.by((): SourceArtifact | null => {
    const wire = $flowEdges.find((edge) => edge.target === id && edge.targetHandle === "artifact");
    const source = $flowNodes.find((node) => node.id === wire?.source);
    if (source?.type === "sourceimport") return source.data.sourceArtifact || null;
    const document = (data.document || {}) as { sourceArtifact?: SourceArtifact | null };
    return document.sourceArtifact || null;
  });
  /* Обе стороны воронки считают одно и то же — компоненты каталога против
   * принятых мастеров. Пока каталог не построен, показываем «—». */
  let detectedComponents = $derived(
    summary.catalogComponents == null ? null : Number(summary.catalogComponents));
  let detectedVariants = $derived(
    summary.catalogVariants == null ? null : Number(summary.catalogVariants));
  let acceptedMasters = $derived(Number(summary.components || 0));
  let acceptedVariants = $derived(Number(summary.variants || 0));
  let canOpen = $derived(!!data.systemId);
  let canBuild = $derived.by(() => {
    const edge = $flowEdges.find((e) => e.target === id && e.targetHandle === "artifact");
    const source = $flowNodes.find((n) => n.id === edge?.source);
    return source?.type === "sourceimport" && source.data.blocks.some((b) => !!b.ir && !b.error);
  });
  let busy = $derived(!!$flowBusy[Number(id)] || !!data._dsFinishing);
  let statusLabel = $derived(data.status === "published" ? `опубликована · v${data.revision}` : data.status === "draft" ? "черновик" : String(data.status));

  const openEditor = () => {
    if (!canOpen) return;
    window.dispatchEvent(new CustomEvent("designdna:open-ds-editor", { detail: { nodeId: Number(id) } }));
  };
</script>

<NodeShell {id} type="designsystem" {selected} title={data.name || undefined} idleStatus={designSystemIdleStatus(data)}>
  {#snippet footer()}
    <div class="foot-left"><span>{statusLabel}{data.defaultSet ? " · по умолчанию" : ""}</span></div>
    <div class="foot-right">
      {#if canOpen && data.status !== "published"}
        <button type="button" class="btn-node primary small nodrag" data-ds-action="finish"
          disabled={busy} onclick={() => $flow.finishDesignSystem(Number(id))}>{busy ? 'ИИ дорабатывает…' : 'Довести до готового'}</button>
      {/if}
      {#if !canOpen}
        <button type="button" class="btn-node primary small nodrag" data-ds-action="build"
          disabled={!canBuild || busy} onclick={() => $flow.rebuildDesignSystemFromSource(Number(id))}>Собрать из Source</button>
      {/if}
      <button type="button" class="btn-node small nodrag" class:primary={canOpen} data-ds-action="open"
        aria-label="Открыть редактор Design System и Source UI" disabled={!canOpen} onclick={openEditor}>Открыть</button>
    </div>
  {/snippet}
  <InPorts type="designsystem" />

  {#if data.systemId}
    <div class="ds-funnel" aria-label="Source detected to system accepted">
      <div class="source-side">
        <span>В источнике</span>
        <strong>{detectedComponents ?? "—"}</strong>
        <small>{detectedVariants ?? "—"} вариантов</small>
      </div>
      <div class="funnel-arrow" aria-hidden="true"><i></i><b>→</b></div>
      <div class="system-side">
        <span>В системе</span>
        <strong>{acceptedMasters}</strong>
        <small>{acceptedVariants} вариантов</small>
      </div>
    </div>
    <div class="ds-metrics">
      <span>{sourceArtifact?.summary.screenCount ?? sourceArtifact?.screens?.length ?? 0} экранов</span>
      <span>{sourceArtifact?.summary.viewportCount ?? 0} вьюпорта</span>
      {#if Number(summary.reviewMasters || 0)}<span>{Number(summary.reviewMasters)} на ревью</span>{/if}
      <span>{Math.round(Number(summary.stateCoverage || 0))}% состояний</span>
      <span>Качество {Math.round(Number(summary.qualityScore || 0))}/100</span>
    </div>
  {:else}
    <div class="n-hero-empty">Соберите кит из Source Import или загрузите JSON в инспекторе: документ DesignDNA, токены Figma / Tokens Studio, карту shadcn.</div>
  {/if}

  {#if data.sourceUpdate}
    <div class="ds-update" role="status"><strong>Источник изменился.</strong> Проверьте и синхронизируйте перед публикацией.</div>
  {/if}
  {#if lastError}
    <details class="ds-error nodrag"><summary>Последнее сообщение</summary><div>{lastError}</div></details>
  {/if}
  {#each Object.entries(data.pipelineStatus || {}) as [stage, result]}
    {#if result.status === "failed" || result.status === "warning" || result.status === "cancelled"}
      <details class="ds-error nodrag" data-ds-pipeline-stage={stage} data-status={result.status}>
        <summary>{stage}: {result.status === 'warning' ? 'нужно ревью' : result.status === 'cancelled' ? 'не завершено' : 'ошибка'}</summary>
        <div>{result.message}</div>
      </details>
    {/if}
  {/each}
  <NodeStatus {id} />
  <OutPorts type="designsystem" />
</NodeShell>

<style>
  .ds-funnel {
    display: grid;
    grid-template-columns: 1fr 36px 1fr;
    align-items: stretch;
    border: 1px solid var(--dna-border);
    border-radius: var(--r-ctl);
    overflow: hidden;
    background: var(--dna-sunken);
  }
  .ds-funnel > div:not(.funnel-arrow) { padding: 8px 9px; }
  .ds-funnel span, .ds-funnel small { display: block; font-size: 9.5px; }
  .ds-funnel span { color: var(--dna-dim); font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
  .ds-funnel strong { display: block; margin: 2px 0 1px; font-size: 18px; line-height: 1; font-variant-numeric: tabular-nums; }
  .ds-funnel small { color: var(--dna-muted); }
  .source-side { box-shadow: inset 2px 0 var(--dna-artifact); }
  .source-side strong { color: var(--dna-text); }
  .system-side { box-shadow: inset -2px 0 #8b7cf6; text-align: right; }
  .system-side strong { color: var(--dna-text); }
  .funnel-arrow { position: relative; display: grid; place-items: center; color: var(--dna-dim); }
  .funnel-arrow i { position: absolute; width: 100%; height: 1px; background: linear-gradient(90deg, var(--dna-artifact), #8b7cf6); opacity: .45; }
  .funnel-arrow b { position: relative; padding: 0 3px; background: var(--dna-sunken); font-size: 12px; }
  .ds-metrics { display: flex; flex-wrap: wrap; gap: 4px 9px; color: var(--dna-muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .ds-update, .ds-error { border-radius: 7px; padding: 6px 8px; font-size: 10px; }
  .ds-update { background: color-mix(in srgb, var(--dna-amber), transparent 88%); color: var(--dna-amber); }
  .ds-error { background: color-mix(in srgb, var(--dna-danger), transparent 90%); color: var(--dna-danger-text); }
  .ds-error summary { cursor: pointer; }
  .ds-error > div { max-height: 160px; overflow: auto; padding-top: 6px; white-space: pre-wrap; }
</style>
