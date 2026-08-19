<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import type { PromptFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Промпт» — живая текстовая нода: каждый ввод пишет data.text,
   * вызывает propagate() и автосейв (зеркало nodes.js:364-367). */
  let { id, data, selected }: NodeProps<PromptFlowNode> = $props();
</script>

<NodeShell {id} type="prompt" {selected}>
  <textarea
    class="f-text nodrag nowheel"
    placeholder="Что нужно сделать? Например: шапка маркетплейса объявлений…"
    value={data.text}
    oninput={(e) => {
      $flow.setNodeData(Number(id), { text: e.currentTarget.value });
      $flow.propagate(Number(id));
    }}
  ></textarea>
  <NodeStatus {id} />
  <OutPorts type="prompt" />
</NodeShell>
