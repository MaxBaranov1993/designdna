<script lang="ts">
  import type { Snippet } from "svelte";
  import { NODE_DEFS } from "../flow/ports";
  import { flow, flowProgresses } from "../flow/state";
  import type { NodeType } from "../flow/types";
  import { cn } from "../lib/utils";

  /* Общий каркас ноды: шапка (иконка, название, ✕) и тело.
   * Зеркало .node-head/.node-body legacy; классы n-<type>, f-* и data-id
   * сохранены для тестов (dataset.id на .node — контракт buildNodeDom legacy). */
  let {
    id,
    type,
    selected = false,
    children,
  }: {
    id: string;
    type: NodeType;
    selected?: boolean;
    children?: Snippet;
  } = $props();

  let def = $derived(NODE_DEFS[type]);

  /* Тонкая полоса прогресса длинных операций (импорт/генерация):
   * elapsed тикает локально, проценты — асимптотическая кривая к expectedMs,
   * до реального завершения 100% не показываем. */
  let progress = $derived($flowProgresses[Number(id)]);
  let now = $state(Date.now());
  $effect(() => {
    if (!progress) return;
    const timer = setInterval(() => (now = Date.now()), 500);
    return () => clearInterval(timer);
  });
  const elapsedMs = $derived(progress ? Math.max(0, now - progress.startedAt) : 0);
  const percent = $derived(progress ? Math.min(97, 100 * (1 - Math.exp((-1.7 * elapsedMs) / progress.expectedMs))) : 0);
  const clock = $derived((() => {
    const total = Math.floor(elapsedMs / 1000);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  })());
</script>

<div class={cn("fnode node", "n-" + type, selected && "selected")} data-id={id} style="width: {def.w}px">
  <div class="node-head">
    <span class="n-icon">{def.icon}</span>
    <span class="n-title">{def.title}</span>
    <button class="n-x nodrag" title="Удалить ноду (Del)" onclick={() => $flow.deleteNode(Number(id))}>✕</button>
  </div>
  <div class="node-body">{@render children?.()}</div>
  {#if progress}
    <div
      class="n-progress"
      role="progressbar"
      aria-label={progress.label}
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={Math.round(percent)}
    >
      <div class="n-progress-track"><div class="n-progress-fill" style="width: {percent}%"></div></div>
      <div class="n-progress-caption">
        <span class="n-progress-label">{progress.label}…</span>
        <span>{Math.round(percent)}% · {clock}</span>
      </div>
    </div>
  {/if}
</div>
