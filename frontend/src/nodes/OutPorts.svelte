<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { portsOfNode } from "../flow/ports";
  import type { AnyNodeData, NodeType } from "../flow/types";
  import { cn } from "../lib/utils";
  import { kindClass } from "./portKind";

  /* Выходные порты — строки справа (зеркало .port-row.out) */
  let { type, data = undefined }: { type: NodeType; data?: AnyNodeData } = $props();

  let ports = $derived(portsOfNode({ type, data }).out);
</script>

{#each ports as p (p.name)}
  <div class="port-row out" data-port={p.name} data-kind={p.kind}>
    <span class="plabel">{p.label}</span>
    <Handle
      id={p.name}
      type="source"
      position={Position.Right}
      class={cn("port-dot", "pp-out-" + p.name, kindClass(p.kind))}
    />
  </div>
{/each}
