<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { PromptFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Промпт» — живая текстовая нода: ввод коммитится с дебаунсом,
   * вызывает propagate() и автосейв (зеркало nodes.js:364-367). */
  let { id, data, selected }: NodeProps<PromptFlowNode> = $props();
  const textKey = $derived(`prompt:${id}:text`);
</script>

<NodeShell {id} type="prompt" {selected}>
  <textarea
    class="f-text nodrag nowheel"
    placeholder="Что нужно сделать? Например: шапка маркетплейса объявлений…"
    value={data.text}
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(textKey, () => {
        $flow.setNodeData(Number(id), { text: value });
        $flow.propagate(Number(id));
      });
    }}
    onblur={() => flushNodeText(textKey)}
  ></textarea>
  <NodeStatus {id} />
  <OutPorts type="prompt" />
</NodeShell>
