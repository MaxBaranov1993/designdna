<script lang="ts">
  /* Модальный confirm в стиле ConflictDialog: фокус на кнопке подтверждения,
   * Esc и клик по фону = отмена, Tab ходит по кругу между двумя кнопками. */
  import type { ConfirmRequest } from "./confirm";

  let { request, onresolve }: { request: ConfirmRequest; onresolve: (value: boolean) => void } = $props();
  let primary: HTMLButtonElement | null = $state(null);
  let secondary: HTMLButtonElement | null = $state(null);

  $effect(() => {
    primary?.focus();
  });

  const onKeydown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onresolve(false);
      return;
    }
    if (event.key === "Tab") {
      // Ловушка фокуса: две кнопки, цикл в обе стороны
      const order = [secondary, primary].filter(Boolean) as HTMLButtonElement[];
      if (!order.length) return;
      const index = order.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.shiftKey
        ? order[(index - 1 + order.length) % order.length]
        : order[(index + 1) % order.length];
      event.preventDefault();
      next.focus();
    }
  };
</script>

<svelte:window onkeydown={onKeydown} />

<div
  class="confirm-backdrop"
  role="presentation"
  onclick={(event) => {
    if (event.target === event.currentTarget) onresolve(false);
  }}
>
  <div
    class="confirm-card"
    role="dialog"
    aria-modal="true"
    aria-labelledby="confirm-title-{request.id}"
    aria-describedby="confirm-message-{request.id}"
    data-confirm-dialog
  >
    <div class="confirm-kicker" class:danger={request.danger}>{request.danger ? "Необратимое действие" : "Подтверждение"}</div>
    <h2 id="confirm-title-{request.id}">{request.title}</h2>
    <p id="confirm-message-{request.id}">{request.message}</p>
    <div class="confirm-actions">
      <button bind:this={secondary} class="confirm-btn" type="button" data-act="cancel" onclick={() => onresolve(false)}>
        {request.cancelLabel}
      </button>
      <button
        bind:this={primary}
        class="confirm-btn primary"
        class:danger={request.danger}
        type="button"
        data-act="confirm"
        onclick={() => onresolve(true)}
      >
        {request.confirmLabel}
      </button>
    </div>
  </div>
</div>

<style>
  .confirm-backdrop {
    position: fixed;
    inset: 0;
    z-index: 195;
    display: grid;
    place-items: center;
    padding: 24px;
    background: rgba(7, 7, 10, 0.66);
    backdrop-filter: blur(5px);
  }
  .confirm-card {
    width: min(440px, calc(100vw - 48px));
    padding: 22px;
    border: 1px solid var(--dna-border-strong);
    border-radius: 16px;
    background: var(--dna-elevated);
    color: var(--dna-text);
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.7);
  }
  .confirm-kicker {
    margin-bottom: 7px;
    color: var(--dna-violet-text);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .confirm-kicker.danger {
    color: var(--dna-danger-text);
  }
  .confirm-card h2 {
    margin: 0 0 8px;
    font-size: 18px;
  }
  .confirm-card p {
    margin: 0 0 16px;
    color: var(--dna-text-2);
    font-size: 12.5px;
    line-height: 1.5;
    white-space: pre-line;
  }
  .confirm-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .confirm-btn {
    padding: 8px 12px;
    border: 1px solid var(--dna-border);
    border-radius: 9px;
    background: var(--dna-panel);
    color: var(--dna-text);
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .confirm-btn:hover {
    background: var(--dna-hover);
  }
  .confirm-btn.primary {
    border-color: var(--dna-violet);
    background: var(--dna-violet);
    color: #fff;
  }
  .confirm-btn.primary:hover {
    background: var(--dna-violet-l);
  }
  .confirm-btn.primary.danger {
    border-color: var(--dna-danger);
    background: var(--dna-danger);
  }
  .confirm-btn.primary.danger:hover {
    background: #f04a73;
  }
  .confirm-btn:focus-visible {
    outline: 2px solid var(--dna-violet-l);
    outline-offset: 2px;
  }
</style>
