<script lang="ts">
  import { onMount } from "svelte";
  import type { NodeProps } from "@xyflow/svelte";
  import { flow, flowBusy } from "../flow/state";
  import type { MotionDesignFlowNode, MotionDesignPlanner } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<MotionDesignFlowNode> = $props();

  let nodeId = $derived(Number(id));
  let busy = $derived(Boolean($flowBusy[nodeId]));
  let paidConfirmed = $state(false);
  let hasReference = $derived(Boolean(data.sourceVideo));
  let hasMotionData = $derived(Boolean(data.sourceMotion || data.sourceTimeline));
  let terminal = $derived(Boolean(data.job && ["completed", "failed", "cancelled", "expired"].includes(data.job.status)));

  function patchSettings(patch: Partial<MotionDesignFlowNode["data"]["settings"]>) {
    $flow.setNodeData(nodeId, { settings: { ...data.settings, ...patch }, job: null, video: null });
  }

  function changePlanner(planner: MotionDesignPlanner) {
    $flow.setNodeData(nodeId, { planner, plannedPrompt: "" });
  }

  onMount(() => {
    if (data.job && !terminal) void $flow.refreshMotionDesign(nodeId);
  });
</script>

<NodeShell {id} type="motiondesign" {selected}>
  <InPorts type="motiondesign" />
  <div class="motion-design-body nodrag">
    <div class="md-source-row">
      <span class:active={hasReference}>VIDEO {hasReference ? "READY" : "—"}</span>
      <span class:active={hasMotionData}>PARAMS {hasMotionData ? "READY" : "—"}</span>
      <span class="md-model">SEEDANCE 2.5</span>
    </div>

    <div class="md-mode-row" aria-label="Input mode">
      {#each [["auto", "Auto"], ["prompt", "Prompt"], ["reference", "Video"]] as option}
        <button class:active={data.inputMode === option[0]} onclick={() => $flow.setNodeData(nodeId, { inputMode: option[0], plannedPrompt: "" })}>{option[1]}</button>
      {/each}
    </div>

    <label class="md-field">
      <span>Задача / отдельный prompt</span>
      <textarea
        rows="3"
        value={data.prompt}
        placeholder={hasReference ? "Например: продолжи ролик и добавь плавный пролёт камеры" : "Опишите сцену, движение, камеру и ограничения"}
        oninput={(event) => $flow.setNodeData(nodeId, { prompt: event.currentTarget.value, plannedPrompt: "" })}
      ></textarea>
    </label>

    <div class="md-planner-row">
      <label><span>Prompt planner</span><select value={data.planner} onchange={(event) => changePlanner(event.currentTarget.value as MotionDesignPlanner)}>
        <option value="direct">Direct</option>
        <option value="openai">GPT-5.6 Sol</option>
        <option value="astra">GPT-6 Astra</option>
        <option value="claude">Claude Code</option>
      </select></label>
      {#if data.planner !== "direct"}
        <label><span>Effort</span><select value={data.effort} onchange={(event) => $flow.setNodeData(nodeId, { effort: event.currentTarget.value, plannedPrompt: "" })}>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="max">Max</option>
        </select></label>
      {/if}
    </div>

    <div class="md-settings">
      <label><span>Duration</span><select value={data.settings.duration} onchange={(event) => patchSettings({ duration: Number(event.currentTarget.value) })}>
        {#each [4, 6, 8, 10, 12, 15, 20, 30] as duration}<option value={duration}>{duration}s</option>{/each}
      </select></label>
      <label><span>Ratio</span><select value={data.settings.aspectRatio} onchange={(event) => patchSettings({ aspectRatio: event.currentTarget.value as typeof data.settings.aspectRatio })}>
        {#each ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"] as ratio}<option value={ratio}>{ratio}</option>{/each}
      </select></label>
      <label><span>Quality</span><select value={data.settings.resolution} onchange={(event) => patchSettings({ resolution: event.currentTarget.value as "480p" | "720p" })}>
        <option value="720p">720p</option><option value="480p">480p</option>
      </select></label>
      <label><span>Seed</span><input type="number" min="0" max="4294967295" value={data.settings.seed ?? ""} placeholder="auto" onchange={(event) => patchSettings({ seed: event.currentTarget.value === "" ? null : Number(event.currentTarget.value) })} /></label>
    </div>

    <label class="md-audio"><input type="checkbox" checked={data.settings.generateAudio} onchange={(event) => patchSettings({ generateAudio: event.currentTarget.checked })} /> Generate synchronized audio</label>

    <button class="md-plan" disabled={busy} onclick={() => void $flow.planMotionDesign(nodeId)}>
      {data.plannedPrompt ? "Обновить prompt" : "Подготовить prompt"}
    </button>

    {#if data.plannedPrompt}
      <div class="md-preview" title={data.plannedPrompt}>{data.plannedPrompt}</div>
    {/if}

    <label class="md-paid"><input type="checkbox" bind:checked={paidConfirmed} />
      <span><strong>Подтверждаю платный вызов</strong><small>OpenRouter · видео не поддерживает ZDR</small></span>
    </label>

    <div class="md-actions">
      <button class="btn-node primary small" disabled={busy || !paidConfirmed} onclick={() => void $flow.runMotionDesign(nodeId, paidConfirmed)}>
        {#if busy}<span class="spinner"></span>{/if} Generate video
      </button>
      {#if data.job && !terminal}
        <button class="btn-node small" disabled={busy} onclick={() => void $flow.refreshMotionDesign(nodeId)}>Refresh</button>
      {/if}
      {#if data.video}
        <a class="btn-node small md-download" href={data.video.downloadUrl} download={data.video.filename}>Download</a>
      {/if}
    </div>
    {#if data.job}
      <div class="md-job"><span>{data.job.id.slice(0, 18)}</span><span>{data.job.status}{#if Number.isFinite(Number(data.job.usage?.cost))} · ${Number(data.job.usage?.cost).toFixed(3)}{/if}</span></div>
    {/if}
  </div>
  <NodeStatus {id} />
  <OutPorts type="motiondesign" {data} />
</NodeShell>

<style>
  .motion-design-body { padding: 88px 10px 8px; display: grid; gap: 8px; color: var(--dna-text-2); }
  .md-source-row { display: flex; gap: 5px; align-items: center; }
  .md-source-row span { padding: 3px 6px; border: 1px solid var(--dna-border); border-radius: 999px; color: var(--dna-dim); font-size: 8px; font-weight: 800; letter-spacing: .07em; }
  .md-source-row span.active { color: #8ba9ff; border-color: color-mix(in srgb, #4f7cff, transparent 45%); background: color-mix(in srgb, #4f7cff, transparent 90%); }
  .md-source-row .md-model { margin-left: auto; color: #a9baff; border-color: transparent; padding-right: 0; }
  .md-mode-row { display: grid; grid-template-columns: repeat(3, 1fr); padding: 3px; border: 1px solid var(--dna-border); border-radius: 9px; background: var(--dna-sunken); }
  .md-mode-row button { border: 0; border-radius: 6px; padding: 5px 4px; background: transparent; color: var(--dna-dim); font: 700 10px "Manrope Variable", sans-serif; }
  .md-mode-row button.active { color: #eef2ff; background: #26345a; box-shadow: inset 0 0 0 1px #4566b6; }
  .md-field, .md-planner-row label, .md-settings label { display: grid; gap: 4px; }
  .md-field > span, .md-planner-row span, .md-settings span { color: var(--dna-dim); font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
  .md-field textarea { min-height: 58px; max-height: 120px; }
  .md-planner-row { display: grid; grid-template-columns: 1fr 92px; gap: 6px; }
  .md-planner-row:has(label:only-child) { grid-template-columns: 1fr; }
  .md-settings { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; }
  .md-settings select, .md-settings input, .md-planner-row select { min-width: 0; padding: 6px 5px; font-size: 10px; }
  .md-audio { display: flex; align-items: center; gap: 7px; color: var(--dna-faint-2); font-size: 10px; }
  .md-audio input, .md-paid input { accent-color: #4f7cff; }
  .md-plan { border: 1px solid #34436d; border-radius: 8px; padding: 7px; background: #161d31; color: #b7c7ff; font: 700 10px "Manrope Variable", sans-serif; }
  .md-plan:disabled { opacity: .5; }
  .md-preview { max-height: 68px; overflow: auto; padding: 8px; border-left: 2px solid #4f7cff; border-radius: 3px 7px 7px 3px; background: #0d1220; color: #aeb9d8; font-size: 9px; line-height: 1.45; }
  .md-paid { display: flex; gap: 8px; align-items: flex-start; padding: 8px; border: 1px solid #5d4329; border-radius: 8px; background: #20170f; }
  .md-paid span { display: grid; gap: 2px; }
  .md-paid strong { color: #ffb270; font-size: 10px; }
  .md-paid small { color: #98795f; font-size: 8px; }
  .md-actions { display: flex; gap: 6px; align-items: center; }
  .md-download { display: inline-flex; align-items: center; text-decoration: none; }
  .md-job { display: flex; justify-content: space-between; gap: 8px; color: var(--dna-dim); font: 700 8px ui-monospace, monospace; }
</style>
