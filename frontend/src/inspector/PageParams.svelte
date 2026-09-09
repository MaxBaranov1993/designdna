<script lang="ts">
  import { NODE_DEFS } from "../flow/ports";
  import { flow, flowEdges, flowNodes } from "../flow/state";
  import type { FlowNode, PageNodeData, SourceViewport } from "../flow/types";
  import { PAGE_INPUT_LIMIT } from "../flow/types";

  let { id, data }: { id: number; data: PageNodeData } = $props();
  const VIEWPORTS: SourceViewport[] = ["desktop", "tablet", "mobile"];
  const nodeId = $derived(String(id));

  let rows = $derived(data.inputs.map((name) => {
    const edge = $flowEdges.find((e) => e.target === nodeId && e.targetHandle === name);
    const srcNode = edge ? $flowNodes.find((n) => n.id === edge.source) : undefined;
    if (!edge || !srcNode) return { name, block: name, src: "не подключён" };
    const def = NODE_DEFS[srcNode.type as FlowNode["type"]];
    const block = srcNode.type === "sourceimport" && edge.sourceHandle
      ? edge.sourceHandle
      : ((srcNode.data as { ir?: { meta?: { name?: string } } | null }).ir?.meta?.name || def.title);
    return { name, block, src: def.title };
  }));

  const setViewport = (viewport: SourceViewport) => {
    $flow.setNodeData(id, { activeViewport: viewport });
    queueMicrotask(() => $flow.propagate(id));
  };
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Вьюпорт превью</div>
    <div class="dna-insp-seg">
      {#each VIEWPORTS as viewport (viewport)}
        <button class:active={data.activeViewport === viewport} onclick={() => setViewport(viewport)}>{viewport === "desktop" ? "Desktop" : viewport === "tablet" ? "Tablet" : "Mobile"}</button>
      {/each}
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Блоки · порядок DOM</div>
    <div class="nrow-merge">
      {#each rows as row, idx (row.name)}
        <div class="merge-row" data-port={row.name} data-kind="ir">
          <span class="merge-n">{idx + 1}</span>
          <span class="merge-name">{row.block}</span>
          <span class="merge-src">{row.src}</span>
          <span class="merge-ctl">
            <button title="Выше" disabled={idx === 0} onclick={() => $flow.reorderPageInputs(id, idx, idx - 1)}>↑</button>
            <button title="Ниже" disabled={idx === rows.length - 1} onclick={() => $flow.reorderPageInputs(id, idx, idx + 1)}>↓</button>
            <button title="Убрать вход" onclick={() => $flow.removePageInput(id, row.name)}>✕</button>
          </span>
        </div>
      {/each}
    </div>
    <button class="dna-btn-ghost" disabled={data.inputs.length >= PAGE_INPUT_LIMIT} onclick={() => $flow.addPageInput(id)}>+ Вход</button>
  </div>
  <button class="dna-btn-ghost" disabled={!data.ir} onclick={() => $flow.sendToNode(id, "edit")}>→ Открыть в Редакторе</button>
</div>
