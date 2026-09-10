<script lang="ts">
  import type { Component } from "svelte";
  import { NODE_DEFS, portsOfNode } from "./flow/ports";
  import { flow, flowBusy, flowNodes, flowStatusLog, flowStatuses } from "./flow/state";
  import { loadEditorController } from "./editor/runtime";
  import { toast } from "./flow/toast";
  import { deselectAllNodes, inspectorHidden } from "./flow/ui";
  import { KIND_COLORS } from "./nodes/portKind";
  import type { NodeType } from "./flow/types";

  import PromptParams from "./inspector/PromptParams.svelte";
  import ReferenceParams from "./inspector/ReferenceParams.svelte";
  import GeneratorParams from "./inspector/GeneratorParams.svelte";
  import EditParams from "./inspector/EditParams.svelte";
  import MixParams from "./inspector/MixParams.svelte";
  import PageParams from "./inspector/PageParams.svelte";
  import SourceImportParams from "./inspector/SourceImportParams.svelte";
  import DesignSystemParams from "./inspector/DesignSystemParams.svelte";
  import TimelineParams from "./inspector/TimelineParams.svelte";
  import MotionDesignParams from "./inspector/MotionDesignParams.svelte";
  import PageBridgeParams from "./inspector/PageBridgeParams.svelte";
  import ImageParams from "./inspector/ImageParams.svelte";
  import RemoveBackgroundParams from "./inspector/RemoveBackgroundParams.svelte";

  /* Плавающий инспектор (Weavy): появляется только при выделении одной ноды,
   * закрывается Esc / ✕ / кликом по канвасу. Вкладка «Параметры» — настоящие
   * контролы, переехавшие из тел нод; пишут в тот же setNodeData. */
  type InspectorTab = "params" | "outputs" | "logs";
  type ParamsComponent = Component<{ id: number; data: any }>;
  const PANELS: Partial<Record<NodeType, ParamsComponent>> = {
    prompt: PromptParams,
    reference: ReferenceParams,
    generator: GeneratorParams,
    edit: EditParams,
    mix: MixParams,
    page: PageParams,
    sourceimport: SourceImportParams,
    designsystem: DesignSystemParams,
    timeline: TimelineParams,
    motiondesign: MotionDesignParams,
    pagebridge: PageBridgeParams,
    image: ImageParams,
    removebackground: RemoveBackgroundParams,
  };

  let tab = $state<InspectorTab>("params");
  let selected = $derived($flowNodes.filter((node) => node.selected));
  let selectedNode = $derived(selected.length === 1 ? selected[0] : null);
  let nodeId = $derived(selectedNode ? Number(selectedNode.id) : null);
  let def = $derived(selectedNode ? NODE_DEFS[selectedNode.type] : null);
  let status = $derived(nodeId == null ? null : $flowStatuses[nodeId] ?? null);
  let busy = $derived(nodeId == null ? false : Boolean($flowBusy[nodeId]));
  let log = $derived(nodeId == null ? [] : ($flowStatusLog[nodeId] ?? []).slice().reverse());
  let ports = $derived(selectedNode ? portsOfNode(selectedNode) : { in: [], out: [] });
  let Panel = $derived(selectedNode ? PANELS[selectedNode.type] || null : null);

  /* Новое выделение снова показывает панель, даже если её закрыли крестиком. */
  let lastSelectedId: string | null = null;
  $effect(() => {
    const id = selectedNode?.id ?? null;
    if (id !== lastSelectedId) {
      lastSelectedId = id;
      if (id) inspectorHidden.set(false);
    }
  });

  let fields = $derived.by(() => {
    if (!selectedNode) return [] as Array<{ key: string; value: string }>;
    const data = selectedNode.data as Record<string, unknown>;
    const keys = Object.keys(data).filter((key) => !key.startsWith("_") && key !== "ir").slice(0, 6);
    return keys.filter((key) => key in data).map((key) => ({ key, value: formatValue(data[key]) }));
  });

  function formatValue(value: unknown): string {
    if (value == null || value === "") return "—";
    if (typeof value === "boolean") return value ? "Включено" : "Выключено";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) return `${value.length} элементов`;
    if (typeof value === "object") return `${Object.keys(value as Record<string, unknown>).length} полей`;
    return String(value);
  }

  const statusClass = () => busy ? "run" : status?.kind === "err" ? "err" : status?.kind === "warn" ? "warn" : status?.kind === "ok" ? "ok" : "";
  const statusText = () => busy ? "выполняется" : status?.text || "готова";
  const canOpen = $derived(selectedNode?.type === "edit" || selectedNode?.type === "designsystem");

  const openSelected = async () => {
    if (!selectedNode || nodeId == null) return;
    if (selectedNode.type === "designsystem") {
      window.dispatchEvent(new CustomEvent("designdna:open-ds-editor", { detail: { nodeId } }));
      return;
    }
    if (selectedNode.type !== "edit") return;
    if (!(selectedNode.data as Record<string, unknown>).ir) {
      toast("Сначала подключите IR к входу ноды", "error");
      return;
    }
    window.dispatchEvent(new Event("designdna:ensure-editor"));
    try {
      await loadEditorController();
      const { useEditorStore } = await import("./editor/store");
      useEditorStore.getState().openEditor(nodeId);
    } catch (error) {
      toast(`Не удалось открыть редактор: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  };

  const onKey = (event: KeyboardEvent) => {
    if (event.key !== "Escape" || !selected.length) return;
    const target = event.target as HTMLElement | null;
    if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) {
      target.blur();
      return;
    }
    if (document.querySelector('[role="dialog"][aria-modal="true"], .dna-editor[data-editor-open="true"], #ctx-menu, #node-ctx-menu')) return;
    deselectAllNodes();
  };
</script>

<svelte:window onkeydown={onKey} />

{#if selected.length > 1}
  <div class="dna-insp-multi" role="toolbar" aria-label="Выделено несколько нод">
    <span>{selected.length} нод</span>
    <button class="dna-btn-ghost" style="padding: 6px 10px" onclick={() => selected.forEach((node) => $flow.runNode(Number(node.id)))}>Запустить все</button>
    <button class="dna-btn-ghost" style="padding: 6px 10px" onclick={() => selected.forEach((node) => $flow.deleteNode(Number(node.id)))}>Удалить</button>
    <button class="dna-insp-close" title="Снять выделение (Esc)" aria-label="Снять выделение" onclick={deselectAllNodes}>✕</button>
  </div>
{:else if selectedNode && def && nodeId != null && !$inspectorHidden}
  <aside class="dna-insp" aria-label="Инспектор ноды">
    <div class="dna-insp-head">
      <div class="dna-insp-icon" style="background: color-mix(in srgb, {def.accent}, transparent 84%); color: {def.accent}">{def.icon}</div>
      <div class="dna-insp-title">
        <strong>{def.title}</strong>
        <small>{def.sub}</small>
      </div>
      <span class={`n-badge ${statusClass()}`} title={statusText()}>{statusText()}</span>
      <button class="dna-insp-close" title="Скрыть инспектор (Esc — снять выделение)" aria-label="Скрыть инспектор" onclick={() => inspectorHidden.set(true)}>✕</button>
    </div>
    <div class="dna-insp-tabs" role="tablist">
      <button class:active={tab === "params"} class="dna-insp-tab" role="tab" aria-selected={tab === "params"} onclick={() => (tab = "params")}>Параметры</button>
      <button class:active={tab === "outputs"} class="dna-insp-tab" role="tab" aria-selected={tab === "outputs"} onclick={() => (tab = "outputs")}>Выходы</button>
      <button class:active={tab === "logs"} class="dna-insp-tab" role="tab" aria-selected={tab === "logs"} onclick={() => (tab = "logs")}>Журнал</button>
    </div>

    <div class="dna-insp-body">
      {#if tab === "params"}
        {#if Panel}
          {#key selectedNode.id}
            <Panel id={nodeId} data={selectedNode.data} />
          {/key}
        {:else}
          <div class="dna-insp-fields">
            {#each fields as field (field.key)}
              <div class="dna-field">
                <div class="dna-field-cap">{field.key.replaceAll("_", " ")}</div>
                <div class="dna-field-value"><span>{field.value}</span></div>
              </div>
            {/each}
            {#if !fields.length}<div class="dna-insp-empty">У этой ноды нет настраиваемых параметров.</div>{/if}
          </div>
        {/if}
        <div class="dna-lastrun">
          <div class="dna-lastrun-cap">Последний запуск</div>
          <div class="dna-lastrun-rows">
            <div class="dna-lastrun-row"><span>Статус</span><span class:good={status?.kind === "ok"}>{statusText()}</span></div>
            <div class="dna-lastrun-row"><span>Входы</span><span>{ports.in.length}</span></div>
            <div class="dna-lastrun-row"><span>Выходы</span><span>{ports.out.length}</span></div>
          </div>
        </div>
      {:else if tab === "outputs"}
        <div class="dna-insp-fields">
          {#each ports.out as port (port.name)}
            <div class="dna-out-row">
              <span class="dna-out-dot" style="background: {KIND_COLORS[port.kind] || KIND_COLORS.text}"></span>
              <span class="dna-out-label">{port.label}</span>
              <span class="dna-out-kind">{port.kind}</span>
            </div>
          {/each}
          {#if !ports.out.length}<div class="dna-insp-empty">Выходные порты не объявлены.</div>{/if}
          {#if ports.in.length}
            <div class="dna-field-cap" style="margin-top: 4px">Входы</div>
            {#each ports.in as port (port.name)}
              <div class="dna-out-row">
                <span class="dna-out-dot" style="background: {KIND_COLORS[port.kind] || KIND_COLORS.text}"></span>
                <span class="dna-out-label">{port.label}</span>
                <span class="dna-out-kind">{(port.kinds || [port.kind]).join(" · ")}</span>
              </div>
            {/each}
          {/if}
        </div>
      {:else}
        <div class="dna-insp-fields">
          {#each log as entry (entry.at + entry.text)}
            <div class:err={entry.kind === "err"} class="dna-insp-log">
              <span class="dna-insp-log-time">{new Date(entry.at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
              {entry.text}
            </div>
          {/each}
          {#if !log.length}<div class="dna-insp-log">Запусков в этой сессии ещё не было.</div>{/if}
        </div>
      {/if}
    </div>

    <div class="dna-insp-actions">
      {#if canOpen}
        <button class="dna-btn-ghost" onclick={openSelected}>Открыть редактор</button>
      {/if}
      <button class="dna-btn-primary" disabled={busy} onclick={() => $flow.runNode(nodeId)}>{busy ? "Выполняется…" : "Запустить"}</button>
    </div>
  </aside>
{/if}
