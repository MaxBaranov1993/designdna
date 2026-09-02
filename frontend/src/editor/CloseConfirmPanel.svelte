<script lang="ts">
  /* Модалка закрытия редактора с несохранёнными правками (controller.requestClose).
   * Esc здесь = «Остаться» (dismissOpenOverlays в controller.onKeydown). */
  import * as ctl from "./controller";
  import { editorUi } from "./state";

  const open = $derived($editorUi.closeConfirmOpen);
  let primary: HTMLButtonElement | null = $state(null);

  $effect(() => {
    if (open) primary?.focus();
  });
</script>

{#if open}
  <div
    class="fe-locks-backdrop fe-close-backdrop"
    role="presentation"
    onmousedown={(event) => {
      if (event.target === event.currentTarget) ctl.dismissCloseConfirm();
    }}
  >
    <div class="fe-locks-card fe-close-card" role="dialog" aria-modal="true" aria-labelledby="close-confirm-title" data-close-confirm>
      <div class="fe-locks-kicker">Несохранённые правки</div>
      <h2 id="close-confirm-title">Закрыть редактор?</h2>
      <p>Правки ещё не записаны в ноду. Сохраните их, выйдите без сохранения или останьтесь в редакторе.</p>
      <div class="fe-locks-actions fe-close-actions">
        <button class="fe-btn danger" data-act="close-discard" onclick={() => ctl.discardAndClose()}>Не сохранять</button>
        <span class="fe-close-spacer"></span>
        <button class="fe-btn" data-act="close-stay" onclick={() => ctl.dismissCloseConfirm()}>Остаться</button>
        <button bind:this={primary} class="fe-btn primary" data-act="close-save" onclick={() => ctl.saveAndClose()}>Сохранить и закрыть</button>
      </div>
    </div>
  </div>
{/if}
