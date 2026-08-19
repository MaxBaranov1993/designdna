<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { portsOfNode } from "../flow/ports";
  import type { AnyNodeData, NodeType } from "../flow/types";
  import { cn } from "../lib/utils";
  import { kindClass } from "./portKind";

  /* Входные порты — строки слева (зеркало .port-row.in). У mix входы динамические
   * и рендерятся прямо в MixNode вместе со слайдерами весов; у page —
   * тоже динамические, с drag-порядком прямо в PageNode. */
  let { type, data = undefined }: { type: NodeType; data?: AnyNodeData } = $props();

  let ports = $derived(
    type === "mix" || type === "page" || type === "edit" ? [] : portsOfNode({ type, data }).in,
  );
</script>

{#each ports as p (p.name)}
  <div class="port-row in" data-port={p.name} data-kind={p.kind}>
    <Handle
      id={p.name}
      type="target"
      position={Position.Left}
      class={cn("port-dot", "pp-in-" + p.name, kindClass(p.kind))}
    />
    <span class="plabel">{p.label}</span>
  </div>
{/each}
