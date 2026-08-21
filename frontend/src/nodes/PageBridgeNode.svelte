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
  <InPorts type="pagebridge" {data} />
  <div class="bridge-mode nodrag">
    <button class={data.mode === "send" ? "active" : ""} onclick={() => $flow.setNodeData(Number(id), { mode: "send" })}>
      Send
    </button>
    <button class={data.mode === "receive" ? "active" : ""} onclick={() => $flow.setNodeData(Number(id), { mode: "receive" })}>
      Receive
    </button>
  </div>
  <label class="field">
    <span>Channel</span>
    <input
      class="nodrag"
      value={data.channel}
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
  </label>
  <button class="btn-node primary small f-run nodrag" onclick={() => $flow.runNode(Number(id))}>
    {data.mode === "send" ? "Передать" : "Получить"}
  </button>
  <div class="bridge-chip">{hasComponent ? "component ready" : "empty channel"}</div>
  <NodeStatus {id} />
  <OutPorts type="pagebridge" {data} />
</NodeShell>
