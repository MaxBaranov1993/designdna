<script lang="ts">
  import { flow } from "../flow/state";
  import type { EditNodeData } from "../flow/types";

  let { id, data }: { id: number; data: EditNodeData } = $props();
  let inputs = $derived(data.inputs || ["ir"]);
  let sources = $derived(Object.values(data.sourceRegistry || {}));
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Входы · порядок сверху вниз</div>
    <div class="nrow-merge">
      {#each inputs as name, index (name)}
        <div class="merge-row" data-port={name} data-kind="ir">
          <span class="merge-n">{index + 1}</span>
          <span class="merge-name">{name}</span>
          <span class="merge-ctl">
            <button title="Выше" disabled={index === 0} onclick={() => $flow.reorderEditInputs(id, index, index - 1)}>↑</button>
            <button title="Ниже" disabled={index === inputs.length - 1} onclick={() => $flow.reorderEditInputs(id, index, index + 1)}>↓</button>
            <button title="Убрать вход" onclick={() => $flow.removeEditInput(id, name)}>✕</button>
          </span>
        </div>
      {/each}
    </div>
    <button class="dna-btn-ghost" onclick={() => $flow.addEditInput(id)}>+ Вход</button>
  </div>
  {#if sources.length}
    <div class="dna-field">
      <div class="dna-field-cap">Источники компонентов</div>
      {#each sources as source (source.id)}
        <div class="dna-field-value"><span>{source.symbol || "S"} · {source.label}</span><span class="dna-out-kind">{Math.round((source.confidence ?? 1) * 100)}%</span></div>
      {/each}
    </div>
  {/if}
</div>
