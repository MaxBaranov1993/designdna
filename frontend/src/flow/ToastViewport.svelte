<script lang="ts">
  import "./toast.css";
  import { toastItems, dismissToast, pauseToast, resumeToast, type ToastItem } from "./toast";

  function runAction(t: ToastItem) {
    try {
      t.action?.run();
    } finally {
      dismissToast(t.id);
    }
  }
</script>

<!-- Контейнер тостов — зеркало #toasts в nodes.html -->
<div id="toasts" aria-live="polite">
  {#each $toastItems as t (t.id)}
    <div
      class={"toast" + (t.kind ? " " + t.kind : "") + (t.sticky ? " sticky" : "")}
      role={t.kind === "error" ? "alert" : "status"}
      data-toast-id={t.id}
      onmouseenter={() => pauseToast(t.id)}
      onmouseleave={() => resumeToast(t.id)}
      onfocusin={() => pauseToast(t.id)}
      onfocusout={() => resumeToast(t.id)}
    >
      <span class="toast-msg">{t.msg}</span>
      {#if t.action}
        <button type="button" class="toast-action" onclick={() => runAction(t)}>{t.action.label}</button>
      {/if}
      <button
        type="button"
        class="toast-close"
        aria-label="Закрыть уведомление"
        title="Закрыть"
        onclick={() => dismissToast(t.id)}
      >
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" focusable="false">
          <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none" />
        </svg>
      </button>
    </div>
  {/each}
</div>
