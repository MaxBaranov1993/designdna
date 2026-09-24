<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import { portsOfNode } from "../flow/ports";
  import { outValue } from "../flow/dataflow";
  import { flowNodes, flowEdges } from "../flow/state";
  import type { AnyNodeData, NodeType } from "../flow/types";
  import { cn } from "../lib/utils";
  import { kindClass } from "./portKind";

  /* Выходные порты — точки на правой кромке, выровнены по верху как входы. */
  let { id, type, data = undefined }: { id: string; type: NodeType; data?: AnyNodeData } = $props();

  let ports = $derived(portsOfNode({ type, data }).out);
  let readyPorts = $derived.by(() => {
    const node = $flowNodes.find(node => node.id === id);
    return new Set(ports.filter(port => {
      const value = node ? outValue(node, port.name, $flowNodes, $flowEdges) : null;
      return value != null && value !== "";
    }).map(port => port.name));
  });

  function portHint(p: { name: string; label: string; kind: string }, ready: boolean): string {
    if (type === "designsystem" && p.name === "system") {
      return `Design system · wire to Generator${ready ? "" : " · open UI Kit / publish when ready"}`;
    }
    if (type === "designsystem" && p.name === "tokens") {
      return "Tokens · palette only · wire to Reskin, Derive, or Page — not Generator";
    }
    if (type === "sourceimport" && p.name === "artifact") {
      return `Source · wire to UI Kit${ready ? "" : " · run import first"}`;
    }
    return `${p.label} output · ${ready ? "Data available" : "No output yet — connect now, run when ready"}`;
  }
</script>

{#each ports as p, index (p.name)}
  <div
    class="port-row dna-port out"
    data-port={p.name}
    data-kind={p.kind}
    data-ready={readyPorts.has(p.name)}
    title={portHint(p, readyPorts.has(p.name))}
    style={`top: ${44 + index * 22}px`}
  >
    <span class="plabel">{p.label}</span>
    <Handle
      id={p.name}
      type="source"
      position={Position.Right}
      aria-label={`${p.label} output · ${readyPorts.has(p.name) ? "Data available" : "No output yet"}`}
      class={cn("port-dot", "pp-out-" + p.name, kindClass(p.kind))}
    />
  </div>
{/each}
