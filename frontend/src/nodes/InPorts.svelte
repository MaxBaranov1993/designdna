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

  function portHint(p: { name: string; label: string; kind: string; kinds?: string[] }): string {
    if (type === "generator" && p.name === "designSystem") {
      return "Design system · connect UI Kit purple port (full kit). Do not use Tokens here.";
    }
    if (type === "designsystem" && p.name === "artifact") {
      return "Source · connect Source Import output (screens + measured UI).";
    }
    return `${p.label} input · accepts ${(p.kinds || [p.kind]).join(" / ")}`;
  }
</script>

{#each ports as p, index (p.name)}
  <div
    class="port-row dna-port in"
    data-port={p.name}
    data-kind={p.kind}
    data-kinds={(p.kinds || [p.kind]).join(",")}
    title={portHint(p)}
    style={`top: ${44 + index * 22}px`}
  >
    <span class="plabel">{p.label}</span>
    <Handle
      id={p.name}
      type="target"
      position={Position.Left}
      aria-label={`${p.label} input`}
      class={cn("port-dot", "pp-in-" + p.name, kindClass(p.kind))}
    />
  </div>
{/each}
