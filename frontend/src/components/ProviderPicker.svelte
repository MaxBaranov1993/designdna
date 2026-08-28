<script lang="ts">
  import type { NodeProvider } from "../flow/types";

  /* Выбор провайдера и усилия для AI-ноды.
   *
   * Sol работает по API-ключу, Codex и Claude — по подписке через локальный
   * CLI (OAuth живёт внутри самого CLI, приложение секрета не видит).
   * Codex — text-only контракт без reasoning, поэтому усилие для него скрыто. */
  let {
    provider = "openai" as NodeProvider,
    effort = "medium",
    onChange,
  }: {
    provider?: NodeProvider;
    effort?: string;
    onChange: (next: { provider: NodeProvider; effort: string }) => void;
  } = $props();

  const PROVIDERS: { value: NodeProvider; label: string }[] = [
    { value: "openai", label: "GPT-5.6 Sol" },
    { value: "codex", label: "Codex" },
    { value: "claude", label: "Claude Opus" },
  ];
  const EFFORTS = [
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
    { value: "max", label: "Max" },
  ];

  const supportsEffort = $derived(provider !== "codex");
</script>

<div class="provider-picker">
  <select
    class="f-provider-select nodrag"
    value={provider}
    onchange={(e) => onChange({ provider: e.currentTarget.value as NodeProvider, effort })}
    aria-label="Провайдер"
  >
    {#each PROVIDERS as option (option.value)}
      <option value={option.value}>{option.label}</option>
    {/each}
  </select>
  {#if supportsEffort}
    <select
      class="f-effort-select nodrag"
      value={effort}
      onchange={(e) => onChange({ provider, effort: e.currentTarget.value })}
      aria-label="Усилие"
    >
      {#each EFFORTS as option (option.value)}
        <option value={option.value}>{option.label}</option>
      {/each}
    </select>
  {/if}
</div>

<style>
  /* Адаптивно: провайдер занимает свободное место, усилие — по содержимому.
     minmax(0,…) обязателен, иначе grid-элемент не сжимается ниже ширины
     текста и «Claude Opus» наползал на соседний селект. */
  .provider-picker {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, auto);
    gap: 6px;
    align-items: center;
    min-width: 0;
  }
  .provider-picker:has(.f-effort-select:only-child),
  .provider-picker:not(:has(.f-effort-select)) {
    grid-template-columns: minmax(0, 1fr);
  }
  .provider-picker select {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  @container (max-width: 220px) {
    .provider-picker { grid-template-columns: minmax(0, 1fr); }
  }
</style>
