<script lang="ts">
  import { NODE_DEFS, portsOfNode } from "./flow/ports";
  import { flow, flowBusy, flowNodes, flowStatuses } from "./flow/state";
  import { loadEditorController } from "./editor/runtime";
  import { toast } from "./flow/toast";

  type InspectorTab = "params" | "outputs" | "logs";
  let tab = $state<InspectorTab>("params");
  let selectedNode = $derived($flowNodes.find((node) => node.selected) ?? null);
  let nodeId = $derived(selectedNode ? Number(selectedNode.id) : null);
  let def = $derived(selectedNode ? NODE_DEFS[selectedNode.type] : null);
  let status = $derived(nodeId == null ? null : $flowStatuses[nodeId] ?? null);
  let busy = $derived(nodeId == null ? false : Boolean($flowBusy[nodeId]));
  let ports = $derived(selectedNode ? portsOfNode(selectedNode) : { in: [], out: [] });

  const preferredKeys: Record<string, string[]> = {
    sourceimport: ["url", "activeViewport", "previewMode", "authenticatedSession"],
    generator: ["provider", "effort", "count", "active"],
    mix: ["inputs", "weights", "variants"],
    edit: ["inputs", "sourceRegistry", "nodeSources"],
    page: ["inputs", "activeViewport"],
    designsystem: ["name", "status", "revision", "defaultSet"],
    recorder: ["mode", "liveUrl", "recording", "selectedTarget"],
    motion: ["selectedScene", "composition", "renderSettings"],
  };

  let fields = $derived.by(() => {
    if (!selectedNode) return [] as Array<{ key: string; value: string }>;
    const data = selectedNode.data as Record<string, unknown>;
    const keys = preferredKeys[selectedNode.type] ?? Object.keys(data).filter((key) => !key.startsWith("_") && key !== "ir").slice(0, 5);
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

  const statusClass = () => busy ? "run" : status?.kind === "err" ? "err" : status?.kind === "ok" ? "ok" : "";
  const statusText = () => busy ? "выполняется" : status?.text || "готова";

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
</script>

<aside class="dna-insp">
  {#if selectedNode && def && nodeId != null}
    <div class="dna-insp-head">
      <div class="dna-insp-icon" style="background: color-mix(in srgb, {def.accent}, transparent 86%); color: {def.accent}">{def.icon}</div>
      <div class="dna-insp-title">
        <strong>{def.title}</strong>
        <small>{def.sub}</small>
      </div>
      <span class={`n-badge ${statusClass()}`}>{statusText()}</span>
    </div>
    <div class="dna-insp-tabs" role="tablist">
      <button class:active={tab === "params"} class="dna-insp-tab" onclick={() => (tab = "params")}>Параметры</button>
      <button class:active={tab === "outputs"} class="dna-insp-tab" onclick={() => (tab = "outputs")}>Выходы</button>
      <button class:active={tab === "logs"} class="dna-insp-tab" onclick={() => (tab = "logs")}>Логи</button>
    </div>

    {#if tab === "params"}
      <div class="dna-insp-fields">
        {#each fields as field (field.key)}
          <div class="dna-field">
            <div class="dna-field-cap">{field.key.replaceAll("_", " ").toUpperCase()}</div>
            <div class="dna-field-value"><span>{field.value}</span><span class="dna-field-chevron">⌄</span></div>
          </div>
        {/each}
        {#if !fields.length}<div class="dna-insp-empty">У этой ноды нет настраиваемых параметров.</div>{/if}
      </div>
      <div class="dna-lastrun">
        <div class="dna-lastrun-cap">ПОСЛЕДНИЙ ЗАПУСК</div>
        <div class="dna-lastrun-rows">
          <div class="dna-lastrun-row"><span>Статус</span><span class:good={status?.kind !== "err"}>{statusText()}</span></div>
          <div class="dna-lastrun-row"><span>Входы</span><span>{ports.in.length}</span></div>
          <div class="dna-lastrun-row"><span>Выходы</span><span>{ports.out.length}</span></div>
        </div>
      </div>
    {:else if tab === "outputs"}
      <div class="dna-insp-fields">
        {#each ports.out as port (port.name)}
          <div class="dna-out-row">
            <span class="dna-out-dot" style="background: {port.kind === 'tokens' ? '#FF691D' : port.kind === 'artifact' ? '#35B8A0' : port.kind === 'interaction' ? '#2FBF9F' : port.kind === 'motion' ? '#E05FB0' : port.kind === 'text' ? '#8A8A93' : '#9B5CFF'}"></span>
            <span class="dna-out-label">{port.label}</span>
            <span class="dna-out-kind">{port.kind}</span>
          </div>
        {/each}
        {#if !ports.out.length}<div class="dna-insp-empty">Выходные порты не объявлены.</div>{/if}
      </div>
    {:else}
      <div class="dna-insp-fields">
        <div class:err={status?.kind === "err"} class="dna-insp-log">{status?.text || "Запусков в этой сессии ещё не было."}</div>
      </div>
    {/if}

    <div class="dna-insp-actions">
      <button class="dna-btn-ghost" disabled={selectedNode.type !== "edit" && selectedNode.type !== "designsystem"} onclick={openSelected}>Открыть в DNA</button>
      <button class="dna-btn-primary" disabled={busy} onclick={() => $flow.runNode(nodeId)}>{busy ? "Выполняется" : "Запустить"}</button>
    </div>
  {:else}
    <div class="dna-insp-head">
      <div class="dna-insp-icon" style="background: rgba(155,92,255,.14); color: #9B5CFF">✦</div>
      <div class="dna-insp-title"><strong>Инспектор</strong><small>Ничего не выбрано</small></div>
    </div>
    <div class="dna-insp-empty">Выберите ноду, чтобы увидеть её параметры, выходы и журнал последнего запуска.</div>
  {/if}
</aside>
