<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import type { MotionFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";
  import { scenesOf, durationOf, previewFor } from "./motion-utils";

  let { id, data, selected }: NodeProps<MotionFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flow.busy[nodeId]));
  let open = $state(false);
  let MotionWorkspace = $state<any>(null);
  let scenes = $derived(scenesOf(data));
  let scene = $derived(scenes[data.selectedScene || 0]);
  let preview = $derived(previewFor(data, scene));

  const openWorkspace = async () => {
    open = true;
    if (!MotionWorkspace) MotionWorkspace = (await import("./MotionWorkspace.svelte")).default;
  };
</script>

<NodeShell {id} type="motion" {selected}>
  <InPorts type="motion" />
  <div class="motion-node-preview nodrag">
    <IrPreview ir={preview} height={180} fitHeight empty="Build Motion IR to materialize scenes" />
    <div><span>{scenes.length} scenes</span><span>{(durationOf(data) / 1000).toFixed(1)}s · {data.composition.fps} fps</span></div>
  </div>
  <div class="ctl-row">
    <button class="btn-node primary small nodrag" disabled={busy || !data.ir || !data.interaction} onclick={() => $flow.runNode(nodeId)}>{#if busy}<span class="spinner"></span>{/if} Build timeline</button>
    <button class="btn-node small nodrag" disabled={!data.motion} onclick={() => void openWorkspace()}>Open editor</button>
  </div>
  {#if scenes.length > 1}
    <div class="motion-node-scenes nodrag">
      {#each scenes as item, index (item.id)}
        <button class={index === data.selectedScene ? "active" : ""} onclick={() => $flow.setNodeData(nodeId, { selectedScene: index })}>{index + 1}</button>
      {/each}
    </div>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="motion" {data} />
  {#if open && MotionWorkspace}
    <MotionWorkspace {nodeId} {data} onClose={() => (open = false)} />
  {/if}
</NodeShell>
