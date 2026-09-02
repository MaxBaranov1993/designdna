<script lang="ts">
  /* Хост фирменного confirm: показывает первый запрос из очереди confirm.ts.
   * Монтируется один раз в App.svelte вне переключателя поверхностей, чтобы
   * confirmDialog() работал и на Project Map, и на графовом экране. */
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import { confirmQueue, settleConfirm } from "./confirm";
</script>

{#if $confirmQueue.length}
  {@const request = $confirmQueue[0]}
  {#key request.id}
    <ConfirmDialog {request} onresolve={(value) => settleConfirm(request.id, value)} />
  {/key}
{/if}
