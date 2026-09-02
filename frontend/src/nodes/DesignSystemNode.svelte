<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flowNodes } from "../flow/state";
  import type { DesignSystemFlowNode, SourceArtifact } from "../flow/types";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";

  let { id, data, selected }: NodeProps<DesignSystemFlowNode> = $props();

  let summary = $derived((data.summary || {}) as Record<string, any>);
  let lastError = $derived(String(data.lastError || ""));
  let sourceArtifact = $derived.by((): SourceArtifact | null => {
    const source = $flowNodes.find((node) => Number(node.id) === Number(data.sourceNodeId));
    if (source?.type === "sourceimport") return source.data.sourceArtifact || null;
    const document = (data.document || {}) as { sourceArtifact?: SourceArtifact | null };
    return document.sourceArtifact || null;
  });
  /* Обе стороны воронки считают одно и то же — компоненты каталога против
   * принятых мастеров. Прежний фолбэк на sourceArtifact.componentSetCount
   * подставлял ЧИСЛО БЛОКОВ страницы, поэтому воронка всегда выглядела
   * дырявой. Пока каталог не построен, показываем «—», а не чужую метрику. */
  let detectedComponents = $derived(
    summary.catalogComponents == null ? null : Number(summary.catalogComponents));
  let detectedVariants = $derived(
    summary.catalogVariants == null ? null : Number(summary.catalogVariants));
  let acceptedMasters = $derived(Number(summary.components || 0));
  let acceptedVariants = $derived(Number(summary.variants || 0));
  let canOpen = $derived(!!data.systemId);

  const openEditor = () => {
    if (!canOpen) return;
    window.dispatchEvent(new CustomEvent("designdna:open-ds-editor", { detail: { nodeId: Number(id) } }));
  };
</script>

<NodeShell {id} type="designsystem" {selected}>
  <InPorts type="designsystem" />
  <div class="ds-head">
    <span class="ds-icon" aria-hidden="true">◈</span>
    <div class="ds-title">
      <strong>{data.name || "Design System / UI Kit"}</strong>
      <small>
        {data.status === "published" ? `Published · v${data.revision}` : data.status === "draft" ? "Draft" : data.status}
        {data.defaultSet ? " · project default" : ""}
      </small>
    </div>
  </div>

  {#if data.systemId}
    <div class="ds-funnel" aria-label="Source detected to system accepted">
      <div class="source-side">
        <span>Source detected</span>
        <strong>{detectedComponents ?? "—"}</strong>
        <small>{detectedVariants ?? "—"} variants</small>
      </div>
      <div class="funnel-arrow" aria-hidden="true"><i></i><b>→</b></div>
      <div class="system-side">
        <span>System accepted</span>
        <strong>{acceptedMasters}</strong>
        <small>{acceptedVariants} variants</small>
      </div>
    </div>
    <div class="ds-metrics">
      <span>{sourceArtifact?.summary.screenCount ?? sourceArtifact?.screens?.length ?? 0} screens</span>
      <span>{sourceArtifact?.summary.viewportCount ?? 0} viewports</span>
      {#if Number(summary.reviewMasters || 0)}<span>{Number(summary.reviewMasters)} review</span>{/if}
      <span>{Math.round(Number(summary.stateCoverage || 0))}% states</span>
      <span>Quality {Math.round(Number(summary.qualityScore || 0))}/100</span>
    </div>
  {:else}
    <div class="ds-empty">Create this UI Kit from a completed Source import.</div>
  {/if}

  {#if data.sourceUpdate}
    <div class="ds-update" role="status"><strong>Source changed.</strong> Review and Sync before publishing.</div>
  {/if}
  {#if lastError}
    <div class="ds-error" role="alert">{lastError}</div>
  {/if}

  <!-- Хендофф: на ноде только «Открыть» — Sync и публикация живут внутри
       панели Design System, система активна по умолчанию. -->
  <div class="ds-actions">
    <button type="button" class="btn-node primary small nodrag" data-ds-action="open"
      aria-label="Открыть редактор Design System и Source UI" disabled={!canOpen} onclick={openEditor}>Открыть</button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="designsystem" />
</NodeShell>

<style>
  .ds-head { display: flex; gap: 9px; align-items: center; }
  .ds-icon { color: #8b7cf6; font-size: 18px; }
  .ds-title { display: flex; min-width: 0; flex: 1; flex-direction: column; }
  .ds-title strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-title small { margin-top: 2px; color: #8b8fa3; font-size: 9px; }
  .ds-funnel {
    display: grid;
    grid-template-columns: 1fr 36px 1fr;
    align-items: stretch;
    margin-top: 9px;
    border: 1px solid var(--flow-border);
    border-radius: 10px;
    overflow: hidden;
    background: color-mix(in srgb, var(--flow-surface-2), transparent 8%);
  }
  .ds-funnel > div:not(.funnel-arrow) { padding: 8px 9px; }
  .ds-funnel span, .ds-funnel small { display: block; font-size: 8px; }
  .ds-funnel span { color: #9096a8; font-weight: 650; letter-spacing: .03em; }
  .ds-funnel strong { display: block; margin: 2px 0 1px; font-size: 18px; line-height: 1; }
  .ds-funnel small { color: #747b8d; }
  .source-side { box-shadow: inset 2px 0 #32b6a0; }
  .source-side strong { color: #58d1bc; }
  .system-side { box-shadow: inset -2px 0 #8b7cf6; text-align: right; }
  .system-side strong { color: #a99cff; }
  .funnel-arrow { position: relative; display: grid; place-items: center; color: #777f91; }
  .funnel-arrow i { position: absolute; width: 100%; height: 1px; background: linear-gradient(90deg, #32b6a0, #8b7cf6); opacity: .55; }
  .funnel-arrow b { position: relative; padding: 0 3px; background: var(--flow-surface-2); font-size: 12px; }
  .ds-metrics { display: flex; flex-wrap: wrap; gap: 4px 9px; margin-top: 7px; color: #9da3b3; font-size: 9px; }
  .ds-empty { padding: 9px 0; color: #8b8fa3; font-size: 10px; }
  .ds-update, .ds-error { margin-top: 7px; border-radius: 7px; padding: 6px 7px; font-size: 9px; }
  .ds-update { background: color-mix(in srgb, #d9a441, transparent 87%); color: #e2b85e; }
  .ds-error { background: color-mix(in srgb, #f87171, transparent 88%); color: #f87171; }
  .ds-actions { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .ds-actions button:disabled { cursor: not-allowed; opacity: .5; }
</style>
