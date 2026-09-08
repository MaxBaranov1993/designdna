<script lang="ts">
  import { flow, flowBusy } from "../flow/state";
  import type { MotionDesignNodeData, MotionDesignPlanner } from "../flow/types";

  let { id, data }: { id: number; data: MotionDesignNodeData } = $props();
  let busy = $derived(!!$flowBusy[id]);
  let hasReference = $derived(Boolean(data.sourceVideo));

  function patchSettings(patch: Partial<MotionDesignNodeData["settings"]>) {
    $flow.setNodeData(id, { settings: { ...data.settings, ...patch }, job: null, video: null });
  }
</script>

<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Источник</div>
    <div class="dna-insp-seg">
      {#each [["auto", "Auto"], ["prompt", "Prompt"], ["reference", "Video"]] as option}
        <button class:active={data.inputMode === option[0]} onclick={() => $flow.setNodeData(id, { inputMode: option[0], plannedPrompt: "" })}>{option[1]}</button>
      {/each}
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Задача / отдельный prompt</div>
    <textarea rows="4" value={data.prompt}
      placeholder={hasReference ? "Например: продолжи ролик и добавь плавный пролёт камеры" : "Опишите сцену, движение, камеру и ограничения"}
      oninput={(event) => $flow.setNodeData(id, { prompt: event.currentTarget.value, plannedPrompt: "" })}></textarea>
  </div>
  <div class="dna-insp-row">
    <div class="dna-field">
      <div class="dna-field-cap">Планировщик</div>
      <select value={data.planner} onchange={(event) => $flow.setNodeData(id, { planner: event.currentTarget.value as MotionDesignPlanner, plannedPrompt: "" })}>
        <option value="direct">Direct</option>
        <option value="openai">GPT-5.6 Sol</option>
        <option value="astra">GPT-6 Astra</option>
        <option value="claude">Claude Code</option>
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Усилие</div>
      <select value={data.effort} disabled={data.planner === "direct"} onchange={(event) => $flow.setNodeData(id, { effort: event.currentTarget.value, plannedPrompt: "" })}>
        <option value="medium">Medium</option><option value="high">High</option><option value="max">Max</option>
      </select>
    </div>
  </div>
  <div class="dna-insp-row">
    <div class="dna-field">
      <div class="dna-field-cap">Длительность</div>
      <select value={String(data.settings.duration)} onchange={(event) => patchSettings({ duration: Number(event.currentTarget.value) })}>
        {#each [4, 6, 8, 10, 12, 15, 20, 30] as duration}<option value={String(duration)}>{duration} s</option>{/each}
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Пропорция</div>
      <select value={data.settings.aspectRatio} onchange={(event) => patchSettings({ aspectRatio: event.currentTarget.value as typeof data.settings.aspectRatio })}>
        {#each ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"] as ratio}<option value={ratio}>{ratio}</option>{/each}
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Качество</div>
      <select value={data.settings.resolution} onchange={(event) => patchSettings({ resolution: event.currentTarget.value as "480p" | "720p" })}>
        <option value="720p">720p</option><option value="480p">480p</option>
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Seed</div>
      <input type="number" min="0" max="4294967295" value={data.settings.seed ?? ""} placeholder="auto" onchange={(event) => patchSettings({ seed: event.currentTarget.value === "" ? null : Number(event.currentTarget.value) })} />
    </div>
  </div>
  <label class="dna-insp-check">
    <input type="checkbox" checked={data.settings.generateAudio} onchange={(event) => patchSettings({ generateAudio: event.currentTarget.checked })} />
    <span>Синхронный звук</span>
  </label>
  <div class="dna-field">
    <button class="dna-btn-ghost" disabled={busy} onclick={() => void $flow.planMotionDesign(id)}>{data.plannedPrompt ? "Обновить prompt" : "Подготовить prompt"}</button>
    {#if data.plannedPrompt}
      <div class="dna-insp-log" title={data.plannedPrompt}>{data.plannedPrompt}</div>
    {/if}
  </div>
  {#if data.job}
    <div class="dna-field">
      <div class="dna-field-cap">Задание Seedance</div>
      <div class="dna-field-value"><span>{data.job.id.slice(0, 18)}</span><span class="dna-out-kind">{data.job.status}{#if Number.isFinite(Number(data.job.usage?.cost))} · ${Number(data.job.usage?.cost).toFixed(3)}{/if}</span></div>
      {#if !["completed", "failed", "cancelled", "expired"].includes(data.job.status)}
        <button class="dna-btn-ghost" disabled={busy} onclick={() => void $flow.refreshMotionDesign(id)}>Обновить статус</button>
      {/if}
    </div>
  {/if}
</div>
