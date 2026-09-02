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
  <div class={cn("n-status", status?.kind)}>{status?.text || ""}</div>
  {#if canCancel}
    <button
      class="n-cancel nodrag"
      title={isDesktop ? "Отменить текущую задачу (перезапускает фоновый воркер)" : "Отменить ожидание ответа"}
      aria-label="Отменить"
      onclick={cancelRun}
    >✕</button>
  {/if}
</div>
