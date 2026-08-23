<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import type { TimelineFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<TimelineFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flow.busy[nodeId]));
  let open = $state(false);
  let TimelineWorkspace = $state<any>(null);
  let timeline = $derived(data.timeline as Record<string, any> | null);
  let layers = $derived(Array.isArray(timeline?.layers) ? timeline.layers.length : 0);
  let duration = $derived(Number(timeline?.composition?.duration || 0));

  const openWorkspace = async () => {
    open = true;
    if (!TimelineWorkspace) TimelineWorkspace = (await import("../editor/TimelineWorkspace.svelte")).default;
  };
</script>

<NodeShell {id} type="timeline" {selected}>
  <InPorts type="timeline" />
  <div class="timeline-node-body nodrag">
    <div class="timeline-node-meta">
      <span>{layers} слоёв</span>
      <span>{(duration / 1000).toFixed(1)}s · {data.settings.fps} fps</span>
    </div>
    <div class="timeline-node-format">{data.settings.width}×{data.settings.height}</div>
  </div>
  <div class="ctl-row">
    <button class="btn-node primary small nodrag" disabled={busy || !data.ir} onclick={() => $flow.runNode(nodeId)}>
      {#if busy}<span class="spinner"></span>{/if} Собрать таймлайн
    </button>
    <button class="btn-node small nodrag" disabled={!timeline} onclick={() => void openWorkspace()}>Открыть редактор</button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="timeline" {data} />
  {#if open && TimelineWorkspace}
    <TimelineWorkspace {nodeId} {data} onClose={() => (open = false)} />
  {/if}
</NodeShell>

<style>
  .timeline-node-body { padding: 8px 10px 4px; font-size: 12px; color: var(--c-text, #d7dae0); }
  .timeline-node-meta { display: flex; justify-content: space-between; gap: 8px; }
  .timeline-node-format { margin-top: 4px; color: var(--c-text-dim, #8b909a); font-size: 11px; }
</style>
