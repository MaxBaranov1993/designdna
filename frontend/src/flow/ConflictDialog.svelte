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
  import { embedGraphAssets } from "./portable-assets";

  let { detail, onclose }: { detail: ProjectConflictDetail; onclose: () => void } = $props();
  let busy = $state(false);
  // Edited during startup: the canvas is the compact cache, the saved project is the full one.
  let whileLoading = $derived(detail.error === "edited-while-loading");
  // The save would drop pages the user never deleted: the canvas lost them.
  let pageLoss = $derived(detail.error === "page_loss");
  let primary: HTMLButtonElement | null = $state(null);

  $effect(() => {
    primary?.focus();
  });

  async function keepMine() {
    busy = true;
    try {
      const ok = await resolveConflictKeepMine(detail.currentRevision, pageLoss ? detail.missingPageIds || [] : []);
      if (ok) {
        toast("Your version was saved to the database", "ok");
        onclose();
      } else {
        toast("Could not save: check the server and retry", "error");
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
        toast("Database version loaded", "ok");
        onclose();
      } else {
        toast("Could not load the project from the database", "error");
      }
    } finally {
      busy = false;
    }
  }

  async function exportJson() {
    busy = true;
    try { downloadJson("designai-graph.json", await embedGraphAssets(buildExportPayload(useFlowStore.getState()))); }
    catch (error) { toast("Export did not finish: " + (error instanceof Error ? error.message : String(error)), "error"); }
    finally { busy = false; }
  }
</script>

<div class="conflict-backdrop" role="presentation">
  <div class="conflict-card" role="dialog" aria-modal="true" aria-labelledby="conflict-title" data-project-conflict>
    <div class="conflict-kicker">Save conflict</div>
    {#if pageLoss}
      <h2 id="conflict-title">Saving would remove pages</h2>
      <p>
        The saved project has pages that are missing on the canvas: {(detail.missingPages || []).join(", ")}. Autosave is paused and nothing was overwritten. Load the saved project to get them back, or remove them for good.
      </p>
    {:else if whileLoading}
      <h2 id="conflict-title">The canvas changed while the project was loading</h2>
      <p>
        Autosave is paused. The saved project is complete; the canvas shown during startup may miss large data such as page results and videos. Load the saved project, or keep the current canvas and overwrite it.
      </p>
    {:else}
      <h2 id="conflict-title">Project changed in another window</h2>
      <p>
        The database contains a newer version. Autosave is paused. Choose which version to keep: yours will overwrite their changes; theirs will replace the current canvas.
      </p>
    {/if}
    <div class="conflict-actions">
      <button class="conflict-btn" type="button" disabled={busy} onclick={exportJson}>Export JSON</button>
      <span class="conflict-spacer"></span>
      {#if pageLoss}
        <button class="conflict-btn" type="button" disabled={busy} onclick={keepMine}>Remove these pages</button>
        <button bind:this={primary} class="conflict-btn primary" type="button" disabled={busy} onclick={takeTheirs}>
          Load saved project
        </button>
      {:else if whileLoading}
        <button class="conflict-btn" type="button" disabled={busy} onclick={keepMine}>Keep the current canvas</button>
        <button bind:this={primary} class="conflict-btn primary" type="button" disabled={busy} onclick={takeTheirs}>
          Load saved project
        </button>
      {:else}
        <button class="conflict-btn" type="button" disabled={busy} onclick={takeTheirs}>Load their version</button>
        <button bind:this={primary} class="conflict-btn primary" type="button" disabled={busy} onclick={keepMine}>
          Keep my changes
        </button>
      {/if}
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
