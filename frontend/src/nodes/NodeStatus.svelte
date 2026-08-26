<script lang="ts">
  import { flowBusy, flowStatuses } from "../flow/state";
  import { cn } from "../lib/utils";

  /* Статусная строка ноды — зеркало .n-status (runtime, в сейв не попадает) */
  let { id }: { id: string } = $props();
  let status = $derived($flowStatuses[Number(id)]);
  let busy = $derived(!!$flowBusy[Number(id)]);
  const canCancel = $derived(busy && typeof window !== "undefined" && !!window.designDNA?.api?.cancel);

  const cancelRun = () => {
    void window.designDNA?.api?.cancel().catch(() => undefined);
  };
</script>

<div class="n-status-row">
  <div class={cn("n-status", status?.kind)}>{status?.text || ""}</div>
  {#if canCancel}
    <button class="n-cancel nodrag" title="Отменить текущую задачу (перезапускает фоновый воркер)" onclick={cancelRun}>✕</button>
  {/if}
</div>
