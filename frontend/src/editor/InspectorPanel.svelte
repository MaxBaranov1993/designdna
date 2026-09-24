<script lang="ts">
  /* Правая панель инспектора — чистый Svelte (без window.Inspector/innerHTML).
   * Контроллер хранит сессию (sel/ir/viewport/geo) и бампит store.inspectorTick;
   * панель перечитывает сессию и перемонтирует дерево по key={tick} — как legacy
   * перестраивал innerHTML. События — нативные, навешивает wireInspector после
   * монтирования (инпуты неконтролируемые: коммит по change, как в editor.js). */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import SharedInspector from "./inspector/SharedInspector.svelte";
  import TypeGroups from "./inspector/TypeGroups.svelte";
  import { wireInspector } from "./inspector/wireInspector";
  import { tick as afterDomUpdate } from "svelte";

  const tick = $derived($editorUi.inspectorTick);
  const busy = $derived($editorUi.aiBusy);
  const previewing = $derived(!!$editorUi.aiPreview);

  // The controller mutates selection inside the long-lived session object.
  // Depend on the explicit revision instead of the session reference, whose
  // identity does not change and can otherwise leave the empty state mounted.
  const selCount = $derived.by(() => {
    void $editorUi.inspectorTick;
    return ctl.getSession()?.sel.length ?? 0;
  });
  const source = $derived.by(() => {
    void $editorUi.inspectorTick;
    return selCount ? ctl.sourceForSelection() : null;
  });
  let contentRoot = $state<HTMLDivElement | null>(null);
  const wiredRoots = new WeakSet<HTMLDivElement>();
  let undoBtn: HTMLButtonElement | null = $state(null);
  let redoBtn: HTMLButtonElement | null = $state(null);

  // История доступна всегда (не только при выделении): disabled-состояние
  // обновляет контроллер через dom-refs
  $effect(() => {
    ctl.dom.undoBtn = undoBtn;
    ctl.dom.redoBtn = redoBtn;
    ctl.updateUndoBtn();
  });

  $effect(() => {
    const version = tick;
    const node = contentRoot;
    if (!node) return;
    void afterDomUpdate().then(() => {
      requestAnimationFrame(() => {
        if (
          contentRoot === node &&
          tick === version &&
          node.isConnected &&
          !wiredRoots.has(node)
        ) {
          wiredRoots.add(node);
          wireInspector(node);
        }
      });
    });
  });
</script>

<div class="fe-inspector">
  <div class="fe-insp-actions">
    <button class="fe-abtn" data-act="semantic-select" title="Select elements using a plain-language request" aria-label="Smart selection" disabled={busy} onclick={() => ctl.handleAct("semantic-select")}>⌘ Smart selection</button>
    <button class="fe-abtn" data-act="smart-axis" title="AI will find the shared content axis and preview a safe patch" aria-label="Align widths" disabled={busy} onclick={() => ctl.handleAct("smart-axis")}>✦ Align widths</button>
    <button class="fe-abtn" data-act="quality-gate" title="Check the grid, overflow, and constraints; preview fixes before applying" aria-label="AI check" disabled={busy} onclick={() => ctl.handleAct("quality-gate")}>✓ AI check</button>
    <button class="fe-abtn" data-act="harmonize" title="Unify colors, typography, radii, and shadows from different sources into one shared palette" aria-label="Unify style" disabled={busy} onclick={() => ctl.handleAct("harmonize")}>✦ Unify style</button>
    <button class="fe-abtn" data-act="responsive-autopilot" title="AI will prepare and validate tablet/mobile constraints before applying them" aria-label="Adapt" disabled={busy} onclick={() => ctl.handleAct("responsive-autopilot")}>▣ Adapt</button>
    <button class="fe-abtn" data-act="intent-locks" title="Protect selected blocks from AI changes" aria-label="Protect" disabled={busy} onclick={() => ctl.handleAct("intent-locks")}>🔒 Protect</button>
    <button class="fe-abtn" data-act="style-dna" title="Edit page color and type tokens" aria-label="Page tokens" disabled={busy} onclick={() => ctl.handleAct("style-dna")}>◈ Tokens</button>
    <button class="fe-abtn" data-act="components" title="Insert a design system component with a reference accepted by strict mode" aria-label="DS components" disabled={busy} onclick={() => ctl.handleAct("components")}>◈ Components</button>
    <button class="fe-abtn" data-act="rules" title="Rules used by Generator and the judge; edit project rules here" aria-label="Rules" disabled={busy} onclick={() => ctl.handleAct("rules")}>📜 Rules</button>
    <span class="fe-abtn-sep"></span>
    <button class="fe-abtn" data-act="undo" bind:this={undoBtn} title="Undo (Ctrl+Z)" aria-label="Undo" aria-keyshortcuts="Control+Z" onclick={() => ctl.handleAct("undo")}>↩ Undo</button>
    <button class="fe-abtn" data-act="redo" bind:this={redoBtn} title="Redo (Ctrl+Shift+Z)" aria-label="Redo" aria-keyshortcuts="Control+Shift+Z" onclick={() => ctl.handleAct("redo")}>↪ Redo</button>
    <button class="fe-abtn" data-act="forward" title="Bring forward (])" aria-label="Bring forward" aria-keyshortcuts="]" disabled={busy || previewing} onclick={() => ctl.handleAct("forward")}>⇈ Bring forward</button>
    <button class="fe-abtn" data-act="backward" title="Send backward ([)" aria-label="Send backward" aria-keyshortcuts="[" disabled={busy || previewing} onclick={() => ctl.handleAct("backward")}>⇊ Send backward</button>
  </div>
  {#if selCount}
    {#key tick}
      <div bind:this={contentRoot}>
        {#if source}
          <div class="fe-source-origin" style="--source-color: {source.color}">
            <span class="fe-source-origin-symbol">{source.symbol || "S"}</span>
            <span><b>{source.label}</b><small>{source.kind || "source"} · {Math.round((source.confidence ?? 1) * 100)}%</small></span>
            <span class="fe-source-origin-state">linked</span>
          </div>
        {/if}
        <div class="fe-shared-insp">
          <SharedInspector />
          {#if !previewing}
            <TypeGroups />
          {/if}
        </div>
      </div>
    {/key}
  {:else}
    <div class="fe-insp-empty"><span>✦</span><strong>Select an object</strong><p>Select an element on the canvas or in Layers, then describe the change to AI.</p></div>
  {/if}
</div>
