<script lang="ts">
  import type { Snippet } from "svelte";
  import { NODE_DEFS } from "../flow/ports";
  import { flow, flowBusy, flowProgresses, flowStatuses } from "../flow/state";
  import { subscribeTick } from "../flow/ticker";
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
  let status = $derived($flowStatuses[Number(id)] ?? null);
  let busy = $derived(Boolean($flowBusy[Number(id)]));
  let badgeClass = $derived(busy ? "run" : status?.kind === "err" ? "err" : status?.kind === "ok" ? "ok" : "");
  let badgeText = $derived(busy ? "выполняется" : status?.text || "готова");

  /* Source Import supplies measured backend stages; legacy operations retain
   * the asymptotic elapsed-time fallback until they expose stage events. */
  let progress = $derived($flowProgresses[Number(id)]);
  let now = $state(Date.now());
  // Подписка живёт только пока у ноды есть прогресс; сам интервал — один на все
  // ноды приложения (см. flow/ticker.ts).
  $effect(() => {
    if (!progress) return;
    return subscribeTick((value) => (now = value));
  });
  const elapsedMs = $derived(progress ? Math.max(0, now - progress.startedAt) : 0);
  const percent = $derived(progress
    ? progress.percent ?? Math.min(97, 100 * (1 - Math.exp((-1.7 * elapsedMs) / progress.expectedMs)))
    : 0);
  const clock = $derived((() => {
    const total = Math.floor(elapsedMs / 1000);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  })());
</script>

<div class={cn("fnode node", "n-" + type, selected && "selected")} data-id={id} style="width: {def.w}px; --n-accent: {def.accent}">
  <div class="node-head">
    <span class:wide={def.icon.length > 2} class="n-icon">{def.icon}</span>
    <span class="n-head-main">
      <span class="n-title">{def.title}</span>
      <span class="n-sub">{def.sub}</span>
    </span>
    <span class={`n-badge ${badgeClass}`} title={status?.text || badgeText}>{badgeText}</span>
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
