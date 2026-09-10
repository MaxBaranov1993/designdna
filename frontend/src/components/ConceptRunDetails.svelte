<script lang="ts">
  import type { ConceptRun } from "../flow/generator-visual";
  let { runs = [] }: { runs?: ConceptRun[] } = $props();
</script>

{#if runs.length}
  <details class="concept-history nodrag" data-concept-history>
    <summary>Визуальный эскиз · {runs.at(-1)?.status === "complete" ? "готов" : runs.at(-1)?.status === "running" ? "создаётся" : "не завершён"}</summary>
    {#each [...runs].reverse() as run (run.id)}
      <div class="concept-run">
        <small>{new Date(run.startedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ориентир композиции</small>
        {#if run.result}<img src={run.result.src} alt="Эскиз композиции" />{/if}
        {#if run.error}<p>{run.error}. Макет можно собрать без эскиза.</p>{/if}
        {#if run.prompt}<details><summary>Задание эскиза</summary><p>{run.prompt}</p></details>{/if}
      </div>
    {/each}
  </details>
{/if}

<style>
  .concept-history { margin: 8px 12px; font-size: 12px; }
  summary { cursor: pointer; padding: 6px 0; }
  .concept-run { margin: 8px 0; }
  small { display: block; opacity: .7; margin-bottom: 6px; }
  img { display: block; width: 100%; max-height: 250px; object-fit: contain; }
  p { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; }
</style>
