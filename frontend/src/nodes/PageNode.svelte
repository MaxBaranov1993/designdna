<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import type { PageFlowNode, SourceViewport } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Страница» — компоновщик: собирает подключённые блоки (Генератор/Source
   * Import/Редактор) в одну страницу. Детерминированно, без LLM (composePage).
   * Входы динамические из data.inputs (паттерн MixNode): drag-порядок строк =
   * порядок секций на странице, «+ вход» (макс. 8), «✕» снимает провода входа.
   * Вход tokens (style DNA) задаёт токены страницы; без него — токены последнего
   * стилизованного блока (main content, а не Header). Артборд 1440, секции width:"fill", responsive-override'ы сохраняются. */
  let { id, data, selected }: NodeProps<PageFlowNode> = $props();

  let dragFrom: number | null = null;

  const VIEWPORTS: SourceViewport[] = ["desktop", "tablet", "mobile"];

  const setViewport = (viewport: SourceViewport) => {
    $flow.setNodeData(Number(id), { activeViewport: viewport });
    // вьюпорт едет вниз по графу через outValue → meta.activeViewport
    queueMicrotask(() => $flow.propagate(Number(id)));
  };
</script>

<NodeShell {id} type="page" {selected}>
  <div class="port-row in" data-port="tokens" data-kind="tokens">
    <Handle id="tokens" type="target" position={Position.Left} class="port-dot port-tokens pp-in-tokens" />
    <span class="plabel">style DNA</span>
  </div>
  {#each data.inputs as name, idx (name)}
    <div
      class="mix-row port-row in page-row"
      data-port={name}
      data-kind="ir"
      role="listitem"
      draggable="true"
      ondragstart={(e) => {
        dragFrom = idx;
        e.dataTransfer!.effectAllowed = "move";
      }}
      ondragover={(e) => e.preventDefault()}
      ondrop={(e) => {
        e.preventDefault();
        if (dragFrom !== null) $flow.reorderPageInputs(Number(id), dragFrom, idx);
        dragFrom = null;
      }}
      title="Порядок строк = порядок секций на странице (таскайте)"
    >
      <Handle id={name} type="target" position={Position.Left} class={"port-dot port-ir pp-in-" + name} />
      <span class="page-grip nodrag">⠿</span>
      <span class="cap">{name}</span>
      <span class="page-row-ctl nodrag">
        <button class="mx" title="Выше" disabled={idx === 0} onclick={() => $flow.reorderPageInputs(Number(id), idx, idx - 1)}>↑</button>
        <button class="mx" title="Ниже" disabled={idx === data.inputs.length - 1} onclick={() => $flow.reorderPageInputs(Number(id), idx, idx + 1)}>↓</button>
        <button class="mx" title="Убрать вход" onclick={() => $flow.removePageInput(Number(id), name)}>✕</button>
      </span>
    </div>
  {/each}
  <div class="ctl-row">
    <button class="btn-node small f-add-in nodrag" onclick={() => $flow.addPageInput(Number(id))}>+ вход</button>
    <button
      class="btn-node primary small f-run nodrag"
      style="margin-left: auto"
      onclick={() => $flow.runNode(Number(id))}
    >
      ▤ Собрать страницу
    </button>
  </div>
  <div class="source-viewports nodrag" aria-label="Page viewport">
    {#each VIEWPORTS as viewport (viewport)}
      <button
        class={"source-viewport" + (data.activeViewport === viewport ? " active" : "")}
        onclick={() => setViewport(viewport)}
        title={viewport === "desktop" ? "1440 px" : viewport === "tablet" ? "768 px" : "390 px"}
      >
        {viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}
      </button>
    {/each}
  </div>
  <IrPreview
    class="f-preview"
    ir={data.ir}
    height={320}
    fitHeight
    viewport={data.activeViewport}
    empty="Подключите блоки и нажмите «Собрать страницу»"
  />
  <div class="gen-actions">
    <button class="btn-node small f-to-editor nodrag" onclick={() => $flow.sendToNode(Number(id), "edit")}>
      → Editor
    </button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="page" {data} />
</NodeShell>
