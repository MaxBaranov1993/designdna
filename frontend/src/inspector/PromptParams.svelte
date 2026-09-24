<script lang="ts">
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { PromptNodeData } from "../flow/types";

  let { id, data }: { id: number; data: PromptNodeData } = $props();
  const key = $derived(`prompt:${id}:text`);
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Task text</div>
    <textarea
      rows="6"
      value={data.text}
      placeholder="What would you like to create? For example: a marketplace header…"
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(key, () => {
          $flow.setNodeData(id, { text: value });
          $flow.propagate(id);
        });
      }}
      onblur={() => flushNodeText(key)}
    ></textarea>
    <div class="dna-field-hint">{(data.text || "").length} chars · sent through the text output</div>
  </div>
</div>
