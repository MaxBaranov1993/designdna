<script lang="ts">
  /* Конфликт сохранения (409 stale revision): проект изменён из другого окна.
   * Автосейв в БД остановлен (fail-closed, serialize.ts) — этот диалог даёт
   * три честных выхода вместо «экспортируй и перезагрузись». */
  import {
    buildExportPayload,
    discardPendingDbSave,
    downloadJson,
    resolveConflictKeepMine,
    type ProjectConflictDetail,
  } from "./serialize";
  import { useFlowStore } from "./store";
  import { toast } from "./toast";

  let { detail, onclose }: { detail: ProjectConflictDetail; onclose: () => void } = $props();
  let busy = $state(false);
  let primary: HTMLButtonElement | null = $state(null);

  $effect(() => {
    primary?.focus();
  });

  async function keepMine() {
    busy = true;
    try {
      const ok = await resolveConflictKeepMine(detail.currentRevision);
      if (ok) {
        toast("Ваша версия записана в базу", "ok");
        onclose();
      } else {
        toast("Не удалось записать: проверьте сервер и повторите", "error");
      }
    } finally {
      busy = false;
    }
  }

  async function takeTheirs() {
    busy = true;
    try {
      discardPendingDbSave();
      const ok = await useFlowStore.getState().replaceProjectFromDb();
      if (ok) {
        toast("Загружена версия из базы", "ok");
        onclose();
      } else {
        toast("Не удалось загрузить проект из базы", "error");
      }
    } finally {
      busy = false;
    }
  }

  function exportJson() {
    downloadJson("designai-graph.json", buildExportPayload(useFlowStore.getState()));
  }
</script>

<div class="conflict-backdrop" role="presentation">
  <div class="conflict-card" role="dialog" aria-modal="true" aria-labelledby="conflict-title" data-project-conflict>
    <div class="conflict-kicker">Конфликт сохранения</div>
    <h2 id="conflict-title">Проект изменён в другом окне</h2>
    <p>
      База содержит более новую версию, автосохранение приостановлено. Выберите, какая версия
      остаётся: ваша перезапишет чужие правки, их версия заменит текущий холст.
    </p>
    <div class="conflict-actions">
      <button class="conflict-btn" type="button" disabled={busy} onclick={exportJson}>Экспорт JSON</button>
      <span class="conflict-spacer"></span>
      <button class="conflict-btn" type="button" disabled={busy} onclick={takeTheirs}>Загрузить их версию</button>
      <button bind:this={primary} class="conflict-btn primary" type="button" disabled={busy} onclick={keepMine}>
        Оставить мои правки
      </button>
    </div>
  </div>
</div>

<style>
  .conflict-backdrop {
    position: fixed;
    inset: 0;
    z-index: 190;
    display: grid;
    place-items: center;
    padding: 24px;
    background: rgba(7, 7, 10, 0.7);
    backdrop-filter: blur(5px);
  }
  .conflict-card {
    width: min(520px, calc(100vw - 48px));
    padding: 22px;
    border: 1px solid var(--dna-border-strong);
    border-radius: 16px;
    background: var(--dna-elevated);
    color: var(--dna-text);
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.7);
  }
  .conflict-kicker {
    margin-bottom: 7px;
    color: var(--dna-danger-text);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .conflict-card h2 {
    margin: 0 0 8px;
    font-size: 19px;
  }
  .conflict-card p {
    margin: 0 0 16px;
    color: var(--dna-text-2);
    font-size: 12.5px;
    line-height: 1.5;
  }
  .conflict-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .conflict-spacer {
    flex: 1;
  }
  .conflict-btn {
    padding: 8px 12px;
    border: 1px solid var(--dna-border);
    border-radius: 9px;
    background: var(--dna-panel);
    color: var(--dna-text);
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .conflict-btn:hover:not(:disabled) {
    background: var(--dna-hover);
  }
  .conflict-btn.primary {
    border-color: var(--dna-violet);
    background: var(--dna-violet);
    color: #fff;
  }
  .conflict-btn.primary:hover:not(:disabled) {
    background: var(--dna-violet-l);
  }
  .conflict-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .conflict-btn:focus-visible {
    outline: 2px solid var(--dna-violet-l);
    outline-offset: 2px;
  }
</style>
