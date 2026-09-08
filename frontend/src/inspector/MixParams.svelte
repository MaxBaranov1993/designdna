<script lang="ts">
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { MixNodeData } from "../flow/types";

  let { id, data }: { id: number; data: MixNodeData } = $props();
  let variants = $derived(Math.max(1, Math.min(8, Number(data.variants) || 1)));

  const bumpWeight = (name: string, d: number) => {
    const current = Math.max(0, Math.min(100, Math.round(data.weights[name] ?? 50)));
    const next = Math.max(0, Math.min(100, current + d));
    const others = data.inputs.filter((n) => n !== name);
    const othersSum = others.reduce((s, n) => s + (data.weights[n] ?? 50), 0);
    const rest = 100 - next;
    const weights: Record<string, number> = { [name]: next };
    let acc = 0;
    others.forEach((n, i) => {
      const share = othersSum > 0 ? (data.weights[n] ?? 50) / othersSum : 1 / others.length;
      const value = i === others.length - 1 ? rest - acc : Math.round(rest * share);
      weights[n] = Math.max(0, value);
      acc += value;
    });
    $flow.setNodeData(id, { weights });
  };
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Промпт микса</div>
    <textarea
      rows="3"
      placeholder="Например: лаконичность из a, цена и бейджи как в b"
      value={data.prompt || ""}
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`mix:${id}:prompt`, () => $flow.setNodeData(id, { prompt: value }));
      }}
      onblur={() => flushNodeText(`mix:${id}:prompt`)}
    ></textarea>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Веса входов</div>
    <div class="nrow-weights">
      {#each data.inputs as name (name)}
        {@const weight = Math.round(data.weights[name] ?? 50)}
        <div class="w-row">
          <span class="w-label">{name}</span>
          <span class="w-track"><span class="w-fill" style="width: {weight}%"></span></span>
          <span class="w-pct">{weight}%</span>
          <button class="w-step" title="−10" onclick={() => bumpWeight(name, -10)}>−</button>
          <button class="w-step" title="+10" onclick={() => bumpWeight(name, 10)}>+</button>
          <button class="w-x" title="Убрать вход" onclick={() => $flow.removeMixInput(id, name)}>✕</button>
        </div>
      {/each}
    </div>
    <button class="dna-btn-ghost" onclick={() => $flow.addMixInput(id)}>+ Вход</button>
  </div>
  <div class="nrow-variants">
    <span>Вариантов</span>
    <button class="v-step" onclick={() => $flow.setNodeData(id, { variants: Math.max(1, variants - 1) })}>−</button>
    <span class="v-count">{variants}</span>
    <button class="v-step" onclick={() => $flow.setNodeData(id, { variants: Math.min(8, variants + 1) })}>+</button>
  </div>
</div>
