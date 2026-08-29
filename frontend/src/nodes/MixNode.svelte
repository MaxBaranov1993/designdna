<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { MixFlowNode } from "../flow/types";
  import InPorts from "./InPorts.svelte";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Микс» — run-based, дизайн-хендофф: промпт микса, интерактивные веса
   * (полоса + %, шаг ±10, автонормализация суммы к 100), счётчик вариантов
   * 1–8, «Смешать» + «+ Вход». POST /api/mix на каждый вариант (store.runMix). */
  let { id, data, selected }: NodeProps<MixFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  let variants = $derived(Math.max(1, Math.min(8, Number(data.variants) || 1)));
  let mixVariants = $derived(data.mixVariants || []);

  /* ±d к весу входа name, остальные пропорционально дожимаются до суммы 100 */
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
    $flow.setNodeData(Number(id), { weights });
  };

  const bumpVariants = (d: number) => {
    $flow.setNodeData(Number(id), { variants: Math.max(1, Math.min(8, variants + d)) });
  };

  const selectVariant = (index: number) => {
    if (busy) return;
    $flow.setNodeData(Number(id), { mixActive: index, ir: mixVariants[index] || null });
    $flow.propagate(Number(id));
  };
</script>

<NodeShell {id} type="mix" {selected}>
  <InPorts type="mix" {data} />
  <div class="nrow">
    <span class="nrow-cap">ПРОМПТ МИКСА</span>
    <input
      class="nrow-value nodrag"
      placeholder="Например: лаконичность из a, цена и бейджи как в b"
      value={data.prompt || ""}
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`mix:${id}:prompt`, () => $flow.setNodeData(Number(id), { prompt: value }));
      }}
      onblur={() => flushNodeText(`mix:${id}:prompt`)}
    />
  </div>
  <div class="nrow-weights nodrag">
    {#each data.inputs as name (name)}
      {@const weight = Math.round(data.weights[name] ?? 50)}
      <div class="w-row" data-port={name} data-kind="ir">
        <span class="w-label">{name}</span>
        <span class="w-track"><span class="w-fill" style="width: {weight}%"></span></span>
        <span class="w-pct">{weight}%</span>
        <button class="w-step" title="−10" onclick={() => bumpWeight(name, -10)}>−</button>
        <button class="w-step" title="+10" onclick={() => bumpWeight(name, 10)}>+</button>
        <button class="w-x" title="Убрать вход" onclick={() => $flow.removeMixInput(Number(id), name)}>✕</button>
      </div>
    {/each}
  </div>
  <div class="nrow-variants nodrag">
    <span>Вариантов</span>
    <button class="v-step" onclick={() => bumpVariants(-1)}>−</button>
    <span class="v-count">{variants}</span>
    <button class="v-step" onclick={() => bumpVariants(1)}>+</button>
  </div>
  <div class="nrow-note2">Результат — готовые компоненты для ноды Редактор (DNA).</div>
  <div class="ctl-row">
    <button
      class="btn-node primary small f-run nodrag"
      disabled={busy}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{/if} Смешать
    </button>
    <button class="btn-node small f-add-in nodrag" onclick={() => $flow.addMixInput(Number(id))}>+ Вход</button>
  </div>
  {#if mixVariants.length > 1}
    <div class="mix-variant-tabs nodrag">
      {#each mixVariants as _, index (index)}
        <button class={index === (data.mixActive || 0) ? "active" : ""} onclick={() => selectVariant(index)}>{index + 1}</button>
      {/each}
    </div>
  {/if}
  <IrPreview class="f-preview" ir={data.ir} height={160} empty="Подключите ≥2 IR-входа и нажмите «Смешать»" />
  <NodeStatus {id} />
  <OutPorts type="mix" {data} />
</NodeShell>
