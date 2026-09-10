<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import type { RemoveBackgroundFlowNode } from "../flow/types";
  import { flow, flowBusy, flowNodes, flowEdges } from "../flow/state";
  import { pullInput } from "../flow/dataflow";
  import { downloadImage, isImageSource } from "../flow/image-assets";
  import { toast } from "../flow/toast";
  import NodeShell from "./NodeShell.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";
  import NodeStatus from "./NodeStatus.svelte";

  let { id, data, selected }: NodeProps<RemoveBackgroundFlowNode> = $props();
  let nodeId = $derived(Number(id));
  let busy = $derived(!!$flowBusy[nodeId]);
  let active = $derived(data.variants?.[data.active] || null);
  let source = $derived.by(() => {
    const node = $flowNodes.find(node => node.id === id);
    const value = node ? pullInput($flowNodes, $flowEdges, node, "image") : null;
    return isImageSource(value) ? value : data.image;
  });
  let view = $state<'result' | 'source' | 'mask' | 'edge'>('result');
  async function download() {
    if (!active) return;
    try { await downloadImage(active.png, `cutout-${nodeId}.png`); }
    catch (error) { toast(String(error), "error"); }
  }
</script>

<NodeShell {id} type="removebackground" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      {#if active}<button class="btn-node small nodrag" onclick={() => void download()}>Скачать PNG</button>{:else}<span>Прозрачный PNG</span>{/if}
    </div>
    <div class="foot-right"><button class="btn-node primary small nodrag" disabled={busy || !source} onclick={() => $flow.runNode(nodeId)}>
      {#if busy}<span class="spinner"></span>{/if} Удалить фон
    </button></div>
  {/snippet}
  <InPorts type="removebackground" />
  <div class="n-hero nodrag">
    {#if active && view !== 'source'}<img class="cutout" src={(view === 'mask' ? active.mask : view === 'edge' ? active.edge : '') || active.png} alt={view === 'mask' ? 'Маска: белое сохраняется' : view === 'edge' ? 'Контур прозрачности' : 'Изображение без фона'} />
    {:else if source}<img class="cutout" src={source} alt="Исходное изображение" />
    {:else}<div class="n-hero-empty">Подключите картинку или загрузите файл в параметрах</div>{/if}
  </div>
  {#if active}
    <div class="n-seg grow nodrag" role="group" aria-label="Сравнение">
      <button class:active={view === 'source'} onclick={() => view = 'source'}>Оригинал</button>
      <button class:active={view === 'result'} onclick={() => view = 'result'}>Без фона</button>
      {#if active.mask}<button class:active={view === 'mask'} onclick={() => view = 'mask'}>Маска</button>{/if}
      {#if active.edge}<button class:active={view === 'edge'} onclick={() => view = 'edge'}>Край</button>{/if}
    </div>
  {/if}
  {#if data.variants.length > 1}
    <div class="n-seg nodrag" role="group" aria-label="Варианты">
      {#each data.variants as _, index (index)}<button disabled={busy} class:active={index === data.active} onclick={() => { $flow.setNodeData(nodeId, { active: index }); $flow.propagate(nodeId); }}>{index + 1}</button>{/each}
    </div>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="removebackground" {data} />
</NodeShell>

<style>
  .cutout { display:block; width:100%; max-height:260px; object-fit:contain; background:repeating-conic-gradient(#1a1a1e 0 25%,#222226 0 50%) 0 0 / 16px 16px; }
</style>
