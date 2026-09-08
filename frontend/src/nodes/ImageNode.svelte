<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow, flowBusy, flowEdges, flowNodes } from "../flow/state";
  import { pullInput } from "../flow/dataflow";
  import { downloadImage, isImageSource } from "../flow/image-assets";
  import { toast } from "../flow/toast";
  import type { ImageFlowNode, ImageStyle } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* Raster GPT Image and legacy SVG share previews, variant history and export.
   * Generation mode, output format and prompt live in ImageParams. */
  let { id, data, selected }: NodeProps<ImageFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flowBusy[nodeId]));
  let variants = $derived(data.variants || []);
  let activeIndex = $derived(Math.min(data.active || 0, Math.max(0, variants.length - 1)));
  let active = $derived(variants[activeIndex] || null);
  let selfNode = $derived($flowNodes.find((node) => node.id === id) || null);
  let hasReference = $derived.by(() => {
    if (!selfNode) return false;
    const value = pullInput($flowNodes, $flowEdges, selfNode, "reference");
    return isImageSource(value);
  });
  const STYLES: Array<[ImageStyle, string]> = [["vector", "Вектор"], ["texture", "Текстура"], ["icon", "Иконка"]];

  const download = async () => {
    if (!active) return;
    const name = `image-${nodeId}-${active.width}x${active.height}.${active.format === "jpeg" ? "jpg" : "png"}`;
    try { await downloadImage(active.png, name); }
    catch (error) { toast(String(error), "error"); }
  };
</script>

<NodeShell {id} type="image" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      <span>{active?.width || data.width}×{active?.height || data.height}{data.tileable ? " · тайл" : ""}{hasReference ? " · по референсу" : ""}</span>
      {#if active}<button class="btn-node small nodrag" onclick={() => void download()}>Скачать</button>{/if}
    </div>
    <div class="foot-right">
      <button class="btn-node primary small f-run nodrag" disabled={busy} onclick={() => $flow.runNode(nodeId)}>
        {#if busy}<span class="spinner"></span>{:else}<span>▶</span>{/if} Сгенерировать
      </button>
    </div>
  {/snippet}
  <InPorts type="image" />
  <div class="n-hero nodrag" style="aspect-ratio: {data.width} / {data.height}; max-height: 260px">
    {#if active}
      <img class="img-result" class:tile={data.tileable} alt="Сгенерированное изображение" src={active.png} />
      {#if variants.length > 1}<span class="n-hero-tag">{activeIndex + 1} / {variants.length}</span>{/if}
    {:else}
      <div class="n-hero-empty">{busy ? (data.engine === "raster" ? "GPT Image создаёт изображение…" : "Модель рисует SVG…") : hasReference ? "Референс подключён — нажмите «Сгенерировать»" : "Картинка появится после запуска"}</div>
    {/if}
  </div>
  {#if variants.length > 1}
    <div class="n-seg nodrag" role="group" aria-label="Варианты">
      {#each variants as _, index (index)}
        <button disabled={busy} class:active={index === activeIndex} onclick={() => { $flow.setNodeData(nodeId, { active: index }); $flow.propagate(nodeId); }}>{index + 1}</button>
      {/each}
    </div>
  {/if}
  {#if data.engine !== "raster"}<div class="n-seg grow nodrag" role="group" aria-label="Стиль">
    {#each STYLES as [value, label] (value)}
      <button class:active={data.style === value} disabled={busy} onclick={() => $flow.setNodeData(nodeId, { style: value })}>{label}</button>
    {/each}
  </div>{/if}
  <NodeStatus {id} />
  <OutPorts type="image" {data} />
</NodeShell>

<style>
  .img-result { display: block; width: 100%; height: 100%; object-fit: contain; background: repeating-conic-gradient(#1a1a1e 0 25%, #222226 0 50%) 0 0 / 16px 16px; }
  .img-result.tile { object-fit: cover; }
</style>
