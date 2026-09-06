<script lang="ts">
  import { onMount } from "svelte";
  import { apiGet } from "../flow/api";
  import type { VideoEffort } from "../flow/types";
  type Choice = { provider: "codex" | "claude"; id: string; label: string; efforts: VideoEffort[]; defaultEffort: VideoEffort };
  let { provider, model, effort, onChange }: {
    provider: "codex" | "claude"; model?: string; effort: VideoEffort;
    onChange: (choice: { provider: "codex" | "claude"; model: string; effort: VideoEffort }) => void;
  } = $props();
  let choices = $state<Choice[]>([
    {provider: "codex", id: "gpt-5.6-sol", label: "GPT-5.6 Sol", efforts: ["medium", "high", "max"], defaultEffort: "medium"},
    {provider: "codex", id: "gpt-6-astra", label: "GPT-6 Astra", efforts: ["medium", "high", "max"], defaultEffort: "medium"},
    {provider: "claude", id: "opus", label: "Claude Opus", efforts: ["medium", "high", "max"], defaultEffort: "medium"},
  ]);
  let hint = $state("");
  const models = $derived(choices.filter(choice => choice.provider === provider));
  const selected = $derived(model || (provider === "claude" ? "opus" : "gpt-5.6-sol"));
  const current = $derived(models.find(choice => choice.id === selected));
  const levels = $derived(current?.efforts || [effort]);
  const labels: Record<VideoEffort, string> = {low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max", ultra: "Ultra"};
  onMount(() => {
    let alive = true;
    apiGet<{models: Choice[]; source: string}>("/api/timeline/models").then(result => {
      if (alive && result.models?.length) { choices = result.models; hint = result.source === "codex-cache" ? "" : "Базовый список моделей"; }
    }).catch(() => { if (alive) hint = "Каталог недоступен · базовый список"; });
    return () => { alive = false; };
  });
  function pick(nextProvider: "codex" | "claude", nextModel?: string) {
    const next = choices.find(choice => choice.provider === nextProvider && choice.id === (nextModel || (nextProvider === "claude" ? "opus" : "gpt-5.6-sol")))
      || choices.find(choice => choice.provider === nextProvider)!;
    onChange({provider: nextProvider, model: next.id, effort: next.efforts.includes(effort) ? effort : next.defaultEffort});
  }
</script>

<div class="video-model-picker nodrag">
  <select class="account" aria-label="Провайдер" value={provider} onchange={event => pick(event.currentTarget.value as "codex" | "claude")}>
    <option value="codex">GPT · мой аккаунт</option><option value="claude">Claude · мой аккаунт</option>
  </select>
  <label>Модель<select aria-label="Модель видео" value={selected} onchange={event => pick(provider, event.currentTarget.value)}>
    {#if !current}<option value={selected} disabled>{selected} · недоступна</option>{/if}
    {#each models as choice}<option value={choice.id}>{choice.label}</option>{/each}
  </select></label>
  <label>Рассуждение<select aria-label="Уровень рассуждения" value={effort} onchange={event => onChange({provider, model: selected, effort: event.currentTarget.value as VideoEffort})}>
    {#if !levels.includes(effort)}<option value={effort} disabled>{labels[effort]} · недоступно</option>{/if}
    {#each levels as level}<option value={level}>{labels[level]}</option>{/each}
  </select></label>
  {#if hint}<span class="hint">{hint}</span>{/if}
</div>

<style>
  .video-model-picker { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 10px 8px; min-width: 0; }
  .account, .hint { grid-column: 1 / -1; }
  label { display: grid; gap: 5px; min-width: 0; color: var(--dna-dim); font-size: 11px; }
  select { width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box; background: var(--dna-sunken); color: var(--dna-text); border: 1px solid var(--dna-border-strong); border-radius: 7px; padding: 7px 8px; font: inherit; font-size: 12px; text-overflow: ellipsis; }
  .hint { color: var(--dna-dim); font-size: 10px; }
</style>
