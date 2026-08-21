<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { MixFlowNode } from "../flow/types";
  import { cn } from "../lib/utils";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Микс» — run-based. Входы динамические из data.inputs (зеркало renderMixInputs,
   * nodes.js:781-813): handle kind "ir" на каждый вход, слайдер веса 0..100,
   * «+ вход» (макс. 4) и «✕» со снятием проводов удалённого входа.
   * POST /api/mix с нормированными весами (payload — зеркало runMix, nodes.js:815-836). */
  let { id, data, selected }: NodeProps<MixFlowNode> = $props();

  let busy = $derived(!!$flow.busy[Number(id)]);
</script>

<NodeShell {id} type="mix" {selected}>
  {#each data.inputs as name (name)}
    {@const weight = data.weights[name] ?? 50}
    <div class="mix-row port-row in" data-port={name} data-kind="ir">
      <Handle id={name} type="target" position={Position.Left} class={cn("port-dot port-ir", "pp-in-" + name)} />
      <span class="cap">{name}</span>
      <input
        type="range"
        min={0}
        max={100}
        value={weight}
        class="nodrag"
        oninput={(e) => {
          const value = Number(e.currentTarget.value);
          commitNodeText(`mix:${id}:w:${name}`, () =>
            $flow.setNodeData(Number(id), { weights: { ...data.weights, [name]: value } }),
          );
        }}
        onchange={() => flushNodeText(`mix:${id}:w:${name}`)}
      />
      <span class="wv">{weight}</span>
      <button class="mx nodrag" title="Убрать вход" onclick={() => $flow.removeMixInput(Number(id), name)}>✕</button>
    </div>
  {/each}
  <div class="ctl-row">
    <button class="btn-node small f-add-in nodrag" onclick={() => $flow.addMixInput(Number(id))}>+ вход</button>
    <button
      class="btn-node primary small f-run nodrag"
      style="margin-left: auto"
      disabled={busy}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{/if} Смешать по весам
    </button>
  </div>
  <IrPreview class="f-preview" ir={data.ir} height={160} empty="Подключите ≥2 IR-входа и нажмите «Смешать»" />
  <NodeStatus {id} />
  <OutPorts type="mix" {data} />
</NodeShell>
