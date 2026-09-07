<script lang="ts">
  import type { EdgeProps } from "@xyflow/svelte";
  import { flowBusy } from "./state";

  let {
    id,
    source,
    selected,
    sourceX,
    sourceY,
    targetX,
    targetY,
    markerEnd,
    markerStart,
    style,
  }: EdgeProps = $props();

  function resolveStroke(edgeStyle: unknown): string {
    if (typeof edgeStyle === "string") {
      return edgeStyle.match(/(?:^|;)\s*stroke\s*:\s*([^;]+)/i)?.[1]?.trim() || "#9b5cff";
    }

    if (edgeStyle && typeof edgeStyle === "object" && "stroke" in edgeStyle) {
      const stroke = (edgeStyle as { stroke?: unknown }).stroke;
      if (typeof stroke === "string" && stroke.trim()) return stroke.trim();
    }

    return "#9b5cff";
  }

  let stroke = $derived(resolveStroke(style));
  let path = $derived.by(() => {
    const dx = Math.max(56, Math.abs(targetX - sourceX) * 0.45);
    return `M ${sourceX} ${sourceY} C ${sourceX + dx} ${sourceY}, ${targetX - dx} ${targetY}, ${targetX} ${targetY}`;
  });
</script>

<path
  {id}
  d={path}
  class="svelte-flow__edge-path dna-wire-solid"
  marker-start={markerStart}
  marker-end={markerEnd}
  fill="none"
  stroke={stroke}
/>
<path d={path} class="dna-wire-dash" class:wire-active={selected || Boolean($flowBusy[Number(source)])} fill="none" stroke={stroke} pointer-events="none" />
<path d={path} class="svelte-flow__edge-interaction" fill="none" stroke-opacity="0" stroke-width="20" />
