<script lang="ts">
  import { flow } from "../flow/state";
  import { cn } from "../lib/utils";

  /* Статусная строка ноды — зеркало .n-status (runtime, в сейв не попадает) */
  let { id }: { id: string } = $props();
  let status = $derived($flow.statuses[Number(id)]);
</script>

<div class={cn("n-status", status?.kind)}>{status?.text || ""}</div>
