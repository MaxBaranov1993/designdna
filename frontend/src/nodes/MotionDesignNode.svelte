<script lang="ts">
  import { onMount } from "svelte";
  import type { NodeProps } from "@xyflow/svelte";
  import { flow, flowBusy } from "../flow/state";
  import type { MotionDesignFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";
  import VideoPlayer from "./VideoPlayer.svelte";

  /* Motion Design — результат-первый: готовое видео Seedance с транспортом,
   * до него — пустой кадр с готовностью источников; сегмент Auto / Prompt /
   * Video, слот подтверждения платного вызова, футер «Сгенерировать».
   * Промпт, планировщик и параметры рендера — в инспекторе. */
  let { id, data, selected }: NodeProps<MotionDesignFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flowBusy[nodeId]));
  let paidConfirmed = $state(false);
  let hasReference = $derived(Boolean(data.sourceVideo));
  let hasMotionData = $derived(Boolean(data.sourceMotion || data.sourceTimeline));
  let terminal = $derived(Boolean(data.job && ["completed", "failed", "cancelled", "expired"].includes(data.job.status)));
  let ratio = $derived(data.settings.aspectRatio.replace(":", " / "));

  onMount(() => {
    if (data.job && !terminal) void $flow.refreshMotionDesign(nodeId);
  });
</script>

<NodeShell {id} type="motiondesign" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      {#if data.job}
        <span title={data.job.id}>{data.job.status}{#if Number.isFinite(Number(data.job.usage?.cost))} · ${Number(data.job.usage?.cost).toFixed(3)}{/if}</span>
      {:else}
        <span>Seedance 2.5 · {data.settings.duration} s · {data.settings.resolution}</span>
      {/if}
    </div>
    <div class="foot-right">
      {#if data.job && !terminal}
        <button class="btn-node small nodrag" disabled={busy} onclick={() => void $flow.refreshMotionDesign(nodeId)}>Обновить</button>
      {/if}
      {#if data.video}
        <a class="btn-node small md-download nodrag" href={data.video.downloadUrl} download={data.video.filename}>Скачать</a>
      {/if}
      <button class="btn-node primary small nodrag" disabled={busy || !paidConfirmed} onclick={() => void $flow.runMotionDesign(nodeId, paidConfirmed)}>
        {#if busy}<span class="spinner"></span>{/if} Сгенерировать
      </button>
    </div>
  {/snippet}
  <InPorts type="motiondesign" />
  {#if data.video?.downloadUrl}
    <VideoPlayer src={data.video.downloadUrl} label="Видео Seedance" />
  {:else}
    <div class="n-hero nodrag" style="aspect-ratio: {ratio}; max-height: 220px">
      <div class="n-hero-empty md-empty">
        <div class="md-source-row">
          <span class:active={hasReference}>video {hasReference ? "✓" : "—"}</span>
          <span class:active={hasMotionData}>params {hasMotionData ? "✓" : "—"}</span>
        </div>
        <span>{busy ? "Генерируем ролик…" : data.plannedPrompt ? "Prompt подготовлен — подтвердите вызов и запустите" : "Опишите сцену в инспекторе или подайте видео на вход"}</span>
      </div>
    </div>
  {/if}
  <div class="md-mode-row n-seg grow nodrag" role="group" aria-label="Источник">
    {#each [["auto", "Auto"], ["prompt", "Prompt"], ["reference", "Video"]] as option}
      <button class:active={data.inputMode === option[0]} onclick={() => $flow.setNodeData(nodeId, { inputMode: option[0], plannedPrompt: "" })}>{option[1]}</button>
    {/each}
  </div>
  {#if data.plannedPrompt}
    <div class="md-preview nodrag nowheel" title={data.plannedPrompt}>{data.plannedPrompt}</div>
  {/if}
  <label class="md-paid nodrag"><input type="checkbox" bind:checked={paidConfirmed} />
    <span><strong>Подтверждаю платный вызов</strong><small>OpenRouter · видео не поддерживает ZDR</small></span>
  </label>
  <NodeStatus {id} />
  <OutPorts type="motiondesign" {data} />
</NodeShell>

<style>
  .md-empty { display: grid; gap: 10px; place-items: center; width: 100%; height: 100%; min-height: 120px; }
  .md-source-row { display: flex; gap: 5px; align-items: center; }
  .md-source-row span { padding: 3px 8px; border: 1px solid var(--dna-border); border-radius: 999px; color: var(--dna-dim); font-size: 9px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
  .md-source-row span.active { color: var(--dna-text); border-color: var(--dna-border-strong); }
  .md-preview { max-height: 68px; overflow: auto; padding: 7px 9px; border-radius: 7px; background: var(--dna-sunken); border: 1px solid var(--dna-border); color: var(--dna-muted); font-size: 10px; line-height: 1.45; }
  .md-paid { display: flex; gap: 8px; align-items: flex-start; padding: 7px 9px; border: 1px solid var(--dna-border); border-radius: 7px; background: var(--dna-sunken); cursor: pointer; }
  .md-paid input { accent-color: var(--dna-action); margin-top: 1px; }
  .md-paid span { display: grid; gap: 2px; }
  .md-paid strong { color: var(--dna-action-text); font-size: 10.5px; }
  .md-paid small { color: var(--dna-dim); font-size: 9.5px; }
  .md-download { text-decoration: none; }
</style>
