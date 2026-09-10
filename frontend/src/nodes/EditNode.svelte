<script lang="ts">
  import { bindPageState, captureNodeScope } from "../flow/store";
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { toast } from "../flow/toast";
  import { flow } from "../flow/state";
  import { loadEditorController } from "../editor/runtime";
  import type { EditFlowNode } from "../flow/types";
  import InPorts from "./InPorts.svelte";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Редактор (DNA)» в графе — thin node: превью IR как герой, компактный
   * список входов, футер «+ вход» и «Открыть редактор». Вся работа с
   * инструментами живёт в полноэкранном DNA Editor (frontend/src/editor). */
  let { id, data, selected }: NodeProps<EditFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let hasIr = $derived(Boolean(data.ir));
  let inputs = $derived(data.inputs || ["ir"]);
  let sources = $derived(Object.values(data.sourceRegistry || {}));
  let dragFrom: number | null = null;

  const openEditor = async () => {
    if (!data.ir) {
      toast("Сначала подключите IR к входу ноды", "error");
      return;
    }
    window.dispatchEvent(new Event("designdna:ensure-editor"));
    try {
      const scope = captureNodeScope(bindPageState(), nodeId);
      await loadEditorController();
      const { useEditorStore } = await import("../editor/store");
      if (scope.visible()) useEditorStore.getState().openEditor(nodeId);
    } catch (error) {
      toast(`Не удалось открыть DNA-редактор: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  };
</script>

<NodeShell {id} type="edit" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      <button class="btn-node small add-input edit-add-input nodrag" onclick={() => $flow.addEditInput(nodeId)}>+ Вход</button>
    </div>
    <div class="foot-right">
      <button class="btn-node primary small f-open-editor nodrag" disabled={!hasIr} onclick={openEditor}>Открыть редактор</button>
    </div>
  {/snippet}
  <InPorts type="edit" data={data} />
  <div class="edit-preview-card n-hero nodrag">
    <IrPreview
      ir={data.ir}
      height={240}
      fitHeight
      class="f-preview"
      empty="Подключите IR — здесь будет превью"
    />
  </div>
  <div class="n-meta">
    <span>{hasIr ? `${sources.length || 1} источн.` : "нет IR на входе"}</span>
    <span>{hasIr ? "Source Lens внутри" : `${inputs.length} вх.`}</span>
  </div>
  <div class="nrow-merge nodrag" role="list" aria-label="Компоненты · порядок сверху вниз">
    {#each inputs as name, index (name)}
      <div
        class="merge-row"
        data-port={name}
        data-kind="ir"
        role="listitem"
        draggable="true"
        ondragstart={() => { dragFrom = index; }}
        ondragover={(event) => event.preventDefault()}
        ondrop={(event) => {
          event.preventDefault();
          if (dragFrom !== null) $flow.reorderEditInputs(nodeId, dragFrom, index);
          dragFrom = null;
        }}
      >
        <span class="merge-n">{index + 1}</span>
        <span class="merge-name">{name}</span>
        <span class="merge-ctl">
          <button title="Выше" disabled={index === 0} onclick={() => $flow.reorderEditInputs(nodeId, index, index - 1)}>↑</button>
          <button title="Ниже" disabled={index === inputs.length - 1} onclick={() => $flow.reorderEditInputs(nodeId, index, index + 1)}>↓</button>
          <button title="Убрать вход" onclick={() => $flow.removeEditInput(nodeId, name)}>✕</button>
        </span>
      </div>
    {/each}
  </div>
  {#if sources.length}
    <div class="edit-source-list" aria-label="Источники компонентов">
      {#each sources as source (source.id)}
        <span class="edit-source-chip" title={`${source.label} · confidence ${Math.round((source.confidence ?? 1) * 100)}%`}>
          <b>{source.symbol || "S"}</b>{source.label}
        </span>
      {/each}
    </div>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="edit" />
</NodeShell>
