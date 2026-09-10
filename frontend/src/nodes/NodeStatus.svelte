<script lang="ts">
  import { flowBusy, flowStatuses } from "../flow/state";
  import { hasRunAbort, useFlowStore } from "../flow/store";
  import { cn } from "../lib/utils";

  /* Статусная строка ноды — зеркало .n-status (runtime, в сейв не попадает) */
  let { id }: { id: string } = $props();
  let status = $derived($flowStatuses[Number(id)]);
  let busy = $derived(!!$flowBusy[Number(id)]);
  /* Отмена доступна везде, где есть что отменять: браузер — AbortController
   * запроса ноды (регистрируется до setBusy), десктоп — рестарт воркера. */
  const isDesktop = typeof window !== "undefined" && !!window.designDNA?.api?.cancel;
  const canCancel = $derived(busy && (isDesktop || hasRunAbort(Number(id))));

  const cancelRun = () => {
    void useFlowStore.getState().cancelRun(Number(id));
  };
</script>

<div class="n-status-row">
  {#if (status?.kind === "err" || status?.kind === "warn") && status.text.length > 220}
    <details class={cn("n-status nodrag", status.kind)}><summary>{status.kind === "warn" ? "Готово с замечаниями · подробности" : "Есть замечания · диагностика"}</summary><div class="status-details">{status.text}</div></details>
  {:else}
    <div class={cn("n-status", status?.kind)}>{status?.text || ""}</div>
  {/if}
  {#if canCancel}
    <button
      class="n-cancel nodrag"
      title={isDesktop ? "Отменить текущую задачу (перезапускает фоновый воркер)" : "Отменить ожидание ответа"}
      aria-label="Отменить"
      onclick={cancelRun}
    >✕</button>
  {/if}
</div>

<style>
  .status-details { max-height: 160px; overflow: auto; padding-top: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
  summary { cursor: pointer; }
</style>
