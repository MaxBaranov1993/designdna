<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow, flowBusy } from "../flow/state";
    import type { DesignSystemFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";

  /* Design System-нода (ТЗ §11): карточка системы + действия. Портов нет —
   * использование через registry и DesignSystemPicker, не через провода. */
  let { id, data, selected }: NodeProps<DesignSystemFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  let busyAction = $derived(String((data as { busyAction?: string }).busyAction || ""));
  const summary = $derived((data.summary || {}) as Record<string, any>);
  const originLabel = $derived((summary.origins || {}) as Record<string, number>);
  const lastError = $derived(String((data as { lastError?: string }).lastError || ""));
  const canPublish = $derived(!!data.systemId && !busy);
  const canDefault = $derived(!!data.systemId && data.status === "published" && !data.defaultSet && !busy);
  const canSync = $derived(!!data.sourceNodeId && !busy);
  const canOpen = $derived(!!data.systemId);

  const run = (action: "publish" | "default" | "sync") => {
    if (action === "publish") void $flow.publishDesignSystem(Number(id));
    else if (action === "default") void $flow.setDefaultDesignSystem(Number(id));
    else void $flow.rebuildDesignSystemFromSource(Number(id));
  };

  const openEditor = () => {
    if (!canOpen) return;
    window.dispatchEvent(new CustomEvent("designdna:open-ds-editor", { detail: { nodeId: Number(id) } }));
  };
</script>

<NodeShell {id} type="designsystem" {selected}>
  <div class="ds-head">
    <span class="ds-icon" aria-hidden="true">◈</span>
    <div class="ds-title">
      <strong>{data.name || "Design System"}</strong>
      <small>{data.status === "published" ? `Published · v${data.revision}` : data.status === "draft" ? "Draft" : data.status}{data.defaultSet ? " · проект по умолчанию" : ""}</small>
    </div>
  </div>
  {#if data.systemId && summary.components}
    <div class="ds-stats" aria-label="Сводка дизайн-системы">
      <span>{summary.components} masters</span>
      <span>{summary.verifiedMasters || 0} verified</span>
      <span>{summary.suggestions || 0} suggestions</span>
      <span>{summary.variants} вариантов</span>
      <span>{Math.round(summary.stateCoverage || 0)}% states</span>
      <span>{summary.mockSchemas} mock-схем</span>
      <span>Quality {Math.round(summary.qualityScore || 0)}/100</span>
      <span class="ds-origins" title="observed / suggested / user / generated">
        {originLabel.observed || 0}⬤ {originLabel.suggested || 0}◐ {originLabel.user || 0}◆ {originLabel.generated || 0}◇
      </span>
    </div>
  {:else if !data.systemId}
    <div class="ds-empty">Создайте из Source-ноды: «UI Kit & Design System»</div>
  {/if}
  {#if data.sourceUpdate}
    <div class="ds-update" role="status">Source изменился — доступна синхронизация</div>
  {/if}
  {#if lastError}
    <div class="ds-error" role="alert">{lastError}</div>
  {/if}
  <div class="ds-actions">
    <button
      type="button"
      class="btn-node primary small nodrag"
      data-ds-action="open"
      aria-label="Открыть редактор дизайн-системы"
      disabled={!canOpen}
      onclick={openEditor}
    >Открыть</button>
    {#if data.systemId}
      <button
        type="button"
        class="btn-node small nodrag"
        data-ds-action="publish"
        aria-label="Опубликовать immutable-ревизию дизайн-системы"
        aria-busy={busyAction === "publish"}
        onclick={() => run("publish")}
        disabled={!canPublish}
      >
        {busyAction === "publish" ? "Публикация…" : "Опубликовать"}
      </button>
      <button
        type="button"
        class="btn-node small nodrag"
        data-ds-action="default"
        aria-label="Назначить дизайн-систему проектом по умолчанию"
        aria-busy={busyAction === "default"}
        onclick={() => run("default")}
        disabled={!canDefault}
      >
        {busyAction === "default" ? "Назначаю…" : "По умолчанию"}
      </button>
      {#if data.sourceNodeId}
        <button
          type="button"
          class="btn-node small nodrag"
          data-ds-action="sync"
          aria-label="Пересобрать черновик из Source"
          aria-busy={busyAction === "sync"}
          onclick={() => run("sync")}
          disabled={!canSync}
        >
          {busyAction === "sync" ? "Сборка…" : "Sync"}
        </button>
      {/if}
    {/if}
  </div>
  <NodeStatus {id} />
</NodeShell>

<style>
  .ds-head { display: flex; gap: 10px; align-items: center; }
  .ds-icon { font-size: 18px; color: #7c6cf0; }
  .ds-title { display: flex; flex-direction: column; min-width: 0; }
  .ds-title strong { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ds-title small { font-size: 10px; color: #8b8fa3; }
  .ds-stats { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 10.5px; color: #aab0c0; margin-top: 8px; }
  .ds-origins { margin-left: auto; letter-spacing: 1px; }
  .ds-empty { font-size: 11px; color: #8b8fa3; padding: 8px 0; }
  .ds-update { font-size: 10.5px; color: #d9a441; margin-top: 6px; }
  .ds-error { font-size: 10.5px; color: #f87171; margin-top: 6px; }
  .ds-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .ds-actions button:disabled { opacity: .5; cursor: not-allowed; }
</style>
