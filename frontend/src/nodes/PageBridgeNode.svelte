<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { PageBridgeFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<PageBridgeFlowNode> = $props();

  let hasComponent = $derived(Boolean(data.ir));
</script>

<NodeShell {id} type="pagebridge" {selected}>
  {#snippet footer()}
    <div class="foot-left"><span>{hasComponent ? "компонент готов" : "канал пуст"}</span></div>
    <div class="foot-right">
      <button class="btn-node primary small f-run nodrag" onclick={() => $flow.runNode(Number(id))}>
        {data.mode === "send" ? "Передать" : "Получить"}
      </button>
    </div>
  {/snippet}
  <InPorts type="pagebridge" {data} />
  <div class="n-seg grow nodrag" role="group" aria-label="Режим">
    <button class={data.mode === "send" ? "active" : ""} onclick={() => $flow.setNodeData(Number(id), { mode: "send" })}>Передать</button>
    <button class={data.mode === "receive" ? "active" : ""} onclick={() => $flow.setNodeData(Number(id), { mode: "receive" })}>Получить</button>
  </div>
  <input
    class="nodrag"
    type="text"
    value={data.channel}
    aria-label="Канал"
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(`pagebridge:${id}:channel`, () => $flow.setNodeData(Number(id), { channel: value }));
    }}
    onblur={() => {
      flushNodeText(`pagebridge:${id}:channel`);
      $flow.runNode(Number(id));
    }}
    placeholder="shared-component"
  />
  <NodeStatus {id} />
  <OutPorts type="pagebridge" {data} />
</NodeShell>
