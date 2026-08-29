<script lang="ts">
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

  /* «Редактор (DNA)» в графе — thin node.
   * Нода не дублирует Figma/Pen.dev-инструменты: внутри графа только read-only
   * превью, а вся работа с GeoEdit/Inspector/Layers/Tools/Undo живёт в
   * полноэкранном DNA Editor (frontend/src/editor). Одна редактирующая
   * поверхность и один контракт сохранения IR. */
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
    // DNA Editor: snapshot/save/propagate — внутри editor store.
    window.dispatchEvent(new Event("designdna:ensure-editor"));
    try {
      await loadEditorController();
      const { useEditorStore } = await import("../editor/store");
      useEditorStore.getState().openEditor(nodeId);
    } catch (error) {
      toast(`Не удалось открыть DNA-редактор: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  };
</script>

<NodeShell {id} type="edit" {selected}>
  <InPorts type="edit" data={data} />
  <div class="nrow-cap">КОМПОНЕНТЫ · ПОРЯДОК СВЕРХУ ВНИЗ</div>
  {#each inputs as name, index (name)}
    <div
      class="merge-row"
      data-port={name}
      data-kind="ir"
      role="listitem"
      draggable="true"
      ondragstart={() => {
        dragFrom = index;
      }}
      ondragover={(event) => event.preventDefault()}
      ondrop={(event) => {
        event.preventDefault();
        if (dragFrom !== null) $flow.reorderEditInputs(nodeId, dragFrom, index);
        dragFrom = null;
      }}
    >
      <span class="merge-n">{index + 1}</span>
      <span class="merge-name">{name}</span>
      <span class="merge-ctl nodrag">
        <button title="Выше" disabled={index === 0} onclick={() => $flow.reorderEditInputs(nodeId, index, index - 1)}>↑</button>
        <button title="Ниже" disabled={index === inputs.length - 1} onclick={() => $flow.reorderEditInputs(nodeId, index, index + 1)}>↓</button>
        <button title="Убрать вход" onclick={() => $flow.removeEditInput(nodeId, name)}>✕</button>
      </span>
    </div>
  {/each}
  <button class="btn-node small edit-add-input nodrag" onclick={() => $flow.addEditInput(nodeId)}>+ Вход</button>
  <div class="edit-preview-card nodrag">
    <IrPreview
      ir={data.ir}
      height={240}
      fitHeight
      class="f-preview"
      empty="Подключите IR — здесь будет только превью"
    />
    <div class="edit-preview-meta">
      <span>{hasIr ? `${sources.length || 1} источн.` : "Нет IR на входе"}</span>
      <span>{hasIr ? "Source Lens внутри" : "подключите компоненты"}</span>
    </div>
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
  <button class="btn-node primary small f-open-editor nodrag" style="width: 100%" onclick={openEditor}>
    ✦ Открыть DNA-редактор
  </button>
  <NodeStatus {id} />
  <OutPorts type="edit" />
</NodeShell>
