<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { PromptFlowNode } from "../flow/types";
  import { autogrow } from "./autogrow";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Промпт» — текст и есть результат: поле на всё тело (Weavy Prompt node),
   * ввод коммитится с дебаунсом, вызывает propagate() и автосейв. */
  let { id, data, selected }: NodeProps<PromptFlowNode> = $props();
  const textKey = $derived(`prompt:${id}:text`);
  let length = $derived((data.text || "").length);
</script>

<NodeShell {id} type="prompt" {selected}>
  {#snippet footer()}
    <div class="foot-left"><span>{length ? `${length} симв.` : "уходит в провод «текст»"}</span></div>
  {/snippet}
  <textarea
    class="f-text n-prompt-text nodrag nowheel"
    placeholder="Что нужно сделать? Например: шапка маркетплейса объявлений…"
    value={data.text}
    use:autogrow={240}
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

<style>
  .n-prompt-text { min-height: 96px; line-height: 1.5; font-weight: 500; resize: none; }
</style>
