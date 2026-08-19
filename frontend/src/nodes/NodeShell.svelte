<script lang="ts">
  import type { Snippet } from "svelte";
  import { NODE_DEFS } from "../flow/ports";
  import { flow } from "../flow/state";
  import type { NodeType } from "../flow/types";
  import { cn } from "../lib/utils";

  /* Общий каркас ноды: шапка (иконка, название, ✕) и тело.
   * Зеркало .node-head/.node-body legacy; классы n-<type>, f-* и data-id
   * сохранены для тестов (dataset.id на .node — контракт buildNodeDom legacy). */
  let {
    id,
    type,
    selected = false,
    children,
  }: {
    id: string;
    type: NodeType;
    selected?: boolean;
    children?: Snippet;
  } = $props();

  let def = $derived(NODE_DEFS[type]);
</script>

<div class={cn("fnode node", "n-" + type, selected && "selected")} data-id={id} style="width: {def.w}px">
  <div class="node-head">
    <span class="n-icon">{def.icon}</span>
    <span class="n-title">{def.title}</span>
    <button class="n-x nodrag" title="Удалить ноду (Del)" onclick={() => $flow.deleteNode(Number(id))}>✕</button>
  </div>
  <div class="node-body">{@render children?.()}</div>
</div>
