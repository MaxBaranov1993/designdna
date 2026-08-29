<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { NODE_DEFS } from "../flow/ports";
  import { flow, flowEdges, flowNodes } from "../flow/state";
  import type { FlowNode, PageFlowNode, SourceViewport } from "../flow/types";
  import InPorts from "./InPorts.svelte";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Страница» — компоновщик, дизайн-хендофф: нумерованный merge-список блоков
   * в порядке DOM с источником каждого (Source Import / UI Kit / Генератор…).
   * Детерминированно, без LLM (composePage): порядок строк = порядок секций,
   * «+ Вход» (макс. 8), «✕» снимает провода входа. Вход tokens — style DNA. */
  let { id, data, selected }: NodeProps<PageFlowNode> = $props();

  let dragFrom: number | null = null;

  const VIEWPORTS: SourceViewport[] = ["desktop", "tablet", "mobile"];

  /* Кто питает вход: имя блока + название ноды-источника для колонки src */
  let mergeRows = $derived(data.inputs.map((name) => {
    const edge = $flowEdges.find((e) => e.target === id && e.targetHandle === name);
    const srcNode = edge ? $flowNodes.find((n) => n.id === edge.source) : undefined;
    if (!edge || !srcNode) return { name, block: name, src: "не подключён" };
    const def = NODE_DEFS[srcNode.type as FlowNode["type"]];
    const block = srcNode.type === "sourceimport" && edge.sourceHandle
      ? edge.sourceHandle
      : ((srcNode.data as { ir?: { meta?: { name?: string } } | null }).ir?.meta?.name || def.title);
    return { name, block, src: def.title };
  }));

  const setViewport = (viewport: SourceViewport) => {
    $flow.setNodeData(Number(id), { activeViewport: viewport });
    // вьюпорт едет вниз по графу через outValue → meta.activeViewport
    queueMicrotask(() => $flow.propagate(Number(id)));
  };
</script>

<NodeShell {id} type="page" {selected}>
  <InPorts type="page" {data} />
  <div class="nrow">
    <span class="nrow-cap">ЛИСТ · ПОРЯДОК DOM</span>
    <div class="nrow-merge" role="list">
      {#each mergeRows as row, idx (row.name)}
        <div
          class="merge-row"
          data-port={row.name}
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
          <span class="merge-n">{idx + 1}</span>
          <span class="merge-name">{row.block}</span>
          <span class="merge-src">{row.src}</span>
          <span class="merge-ctl nodrag">
            <button title="Выше" disabled={idx === 0} onclick={() => $flow.reorderPageInputs(Number(id), idx, idx - 1)}>↑</button>
            <button title="Ниже" disabled={idx === mergeRows.length - 1} onclick={() => $flow.reorderPageInputs(Number(id), idx, idx + 1)}>↓</button>
            <button title="Убрать вход" onclick={() => $flow.removePageInput(Number(id), row.name)}>✕</button>
          </span>
        </div>
      {/each}
    </div>
  </div>
  <div class="ctl-row">
    <button
      class="btn-node primary small f-run nodrag"
      onclick={() => $flow.runNode(Number(id))}
    >
      ▤ Собрать лист
    </button>
    <button class="btn-node small f-add-in nodrag" onclick={() => $flow.addPageInput(Number(id))}>+ Вход</button>
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
    empty="Подключите блоки и нажмите «Собрать лист»"
  />
  <div class="gen-actions">
    <button class="btn-node small f-to-editor nodrag" onclick={() => $flow.sendToNode(Number(id), "edit")}>
      → Editor
    </button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="page" {data} />
</NodeShell>
