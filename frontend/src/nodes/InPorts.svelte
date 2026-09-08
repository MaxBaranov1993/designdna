<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { portsOfNode } from "../flow/ports";
  import type { AnyNodeData, NodeType } from "../flow/types";
  import { cn } from "../lib/utils";
  import { kindClass } from "./portKind";

  /* Входные порты — точки на левой кромке от 44px с шагом 22px (Weavy:
   * порты у верхнего края, подписи только по наведению / при выделении /
   * во время протягивания провода — см. .plabel в index.css). */
  let { type, data = undefined }: { type: NodeType; data?: AnyNodeData } = $props();

  let ports = $derived(portsOfNode({ type, data }).in);
</script>

{#each ports as p, index (p.name)}
  <div
    class="port-row dna-port in"
    data-port={p.name}
    data-kind={p.kind}
    data-kinds={(p.kinds || [p.kind]).join(",")}
    style={`top: ${44 + index * 22}px`}
  >
    <span class="plabel">{p.label}</span>
    <Handle
      id={p.name}
      type="target"
      position={Position.Left}
      class={cn("port-dot", "pp-in-" + p.name, kindClass(p.kind))}
    />
  </div>
{/each}
