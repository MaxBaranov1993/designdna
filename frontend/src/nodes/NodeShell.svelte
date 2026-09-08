<script lang="ts">
  import type { Snippet } from "svelte";
  import { NODE_DEFS } from "../flow/ports";
  import { flow, flowBusy, flowProgresses, flowStatuses } from "../flow/state";
  import { subscribeTick } from "../flow/ticker";
  import type { NodeType } from "../flow/types";
  import { requestNodeActions } from "../flow/ui";
  import { cn } from "../lib/utils";

  /* Каркас ноды по мотивам Weavy: шапка 36px (иконка, имя, точка статуса,
   * «···»), опциональная линия прогресса, тело-превью и футер с одним
   * главным действием. Классы n-<type>, f-*, data-id, .node-head, .n-x,
   * .n-progress* сохранены — на них стоят Playwright-тесты. */
  let {
    id,
    type,
    selected = false,
    idleStatus,
    title,
    children,
    footer,
  }: {
    id: string;
    type: NodeType;
    selected?: boolean;
    idleStatus?: { text: string; kind?: string | null };
    /** Переопределение имени в шапке (например, имя дизайн-системы). */
    title?: string;
    children?: Snippet;
    /** Футер: слева служебный текст / «+ вход», справа главное действие. */
    footer?: Snippet;
  } = $props();

  let def = $derived(NODE_DEFS[type]);
  let busy = $derived(Boolean($flowBusy[Number(id)]));
  let status = $derived((!busy && idleStatus) || $flowStatuses[Number(id)] || null);
  let dotClass = $derived(busy ? "run" : status?.kind === "err" ? "err" : status?.kind === "ok" ? "ok" : "");
  let dotText = $derived(busy ? "выполняется" : status?.text || "готова");

  /* Измеренный прогресс приходит стадиями с бэкенда (Source Import); у
   * остальных операций — indeterminate-линия и честная подсказка «до N мин». */
  let progress = $derived($flowProgresses[Number(id)]);
  let now = $state(Date.now());
  $effect(() => {
    if (!progress) return;
    return subscribeTick((value) => (now = value));
  });
  const elapsedMs = $derived(progress ? Math.max(0, now - progress.startedAt) : 0);
  const measured = $derived(!!progress && Number.isFinite(progress.percent));
  const percent = $derived(measured ? Number(progress!.percent) : 0);
  const overdue = $derived(!!progress && elapsedMs > progress.expectedMs);
  const expectedHint = $derived((() => {
    if (!progress) return "";
    const min = Math.max(1, Math.round(progress.expectedMs / 60_000));
    return overdue ? "дольше обычного" : `обычно до ${min} мин`;
  })());
  const clock = $derived((() => {
    const total = Math.floor(elapsedMs / 1000);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  })());

  const openActions = (event: MouseEvent) => {
    event.stopPropagation();
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    requestNodeActions({ nodeId: id, x: rect.right, y: rect.bottom + 4 });
  };
</script>

<div class={cn("fnode node", "n-" + type, selected && "selected")} data-id={id} style="width: {def.w}px; --n-accent: {def.accent}">
  <div class="node-head" title={def.sub}>
    <span class:wide={def.icon.length > 2} class="n-icon">{def.icon}</span>
    <span class="n-head-main">
      <span class="n-title">{title || def.title}</span>
      <span class="n-sub">{def.sub}</span>
    </span>
    <span class={`n-dot ${dotClass}`} role="img" aria-label={dotText} title={status?.text || dotText}></span>
    <button class="n-x nodrag" title="Удалить ноду (Del)" aria-label="Удалить ноду" onclick={() => $flow.deleteNode(Number(id))}>✕</button>
    <button class="n-more nodrag" title="Действия ноды" aria-label="Действия ноды" aria-haspopup="menu" onclick={openActions}>···</button>
  </div>
  {#if progress}
    <div
      class={cn("n-progress", !measured && "indeterminate", overdue && "overdue")}
      role="progressbar"
      aria-label={progress.label}
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={measured ? Math.round(percent) : undefined}
      aria-valuetext={measured ? `${Math.round(percent)}%` : `${progress.stage || progress.label}, ${clock}`}
    >
      <div class="n-progress-track"><div class="n-progress-fill" style={measured ? `width: ${percent}%` : ""}></div></div>
      <div class="n-progress-caption">
        <span class="n-progress-label">{progress.stage ? `${progress.label} · ${progress.stage}` : progress.label}…</span>
        <span>{measured ? `${Math.round(percent)}% · ${clock}` : `${clock} · ${expectedHint}`}</span>
      </div>
    </div>
  {/if}
  <div class="node-body">{@render children?.()}</div>
  {#if footer}
    <div class="node-foot nodrag">{@render footer()}</div>
  {/if}
</div>
