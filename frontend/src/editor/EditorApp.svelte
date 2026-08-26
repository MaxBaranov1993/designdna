<script lang="ts">
  /* Корень DNA-редактора. Overlay смонтирован всегда (display flex/none —
   * жёсткий контракт тестов: style.display === 'flex', когда редактор открыт).
   * Svelte отвечает только за каркас; сессия и движки — в controller.ts. */
  import "./editor.css";
  import { onMount } from "svelte";
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import TopBar from "./TopBar.svelte";
  import LayersPanel from "./LayersPanel.svelte";
  import CanvasStage from "./CanvasStage.svelte";
  import InspectorPanel from "./InspectorPanel.svelte";
  import DnaPanel from "./DnaPanel.svelte";
  import SourceLensBar from "./SourceLensBar.svelte";
  import SmartAxisPanel from "./SmartAxisPanel.svelte";
  import QualityGatePanel from "./QualityGatePanel.svelte";
  import HarmonizerPanel from "./HarmonizerPanel.svelte";
  import ResponsiveAutopilotPanel from "./ResponsiveAutopilotPanel.svelte";
  import IntentLocksPanel from "./IntentLocksPanel.svelte";
  import SemanticSelectPanel from "./SemanticSelectPanel.svelte";

  let overlay: HTMLDivElement | null = $state(null);

  // ctl.dom.overlay — регистрируем сразу, overlay смонтирован всегда
  $effect(() => {
    ctl.dom.overlay = overlay;
  });

  // A first open can start the lazy import before this overlay exists. Finish
  // that one pending open once after mount; later opens are handled by store.ts.
  onMount(() => {
    ctl.dom.overlay = overlay;
    if (!$editorUi.isOpen || !ctl.isActive()) return;
    requestAnimationFrame(() => {
      if (ctl.dom.overlay && ctl.isActive()) ctl.finishOpen();
    });
  });

</script>

<!-- клавиатура редактора (порт keydown из editor.js) — активна только в открытой сессии -->
<svelte:document onkeydown={(e) => ctl.onKeydown(e)} />

<div bind:this={overlay} class="dna-editor" style="display: {$editorUi.isOpen ? 'flex' : 'none'}" aria-busy={$editorUi.aiBusy} data-editor-open={$editorUi.isOpen ? "true" : "false"}>
  <TopBar />
  <SourceLensBar />
  <div class="fe-body">
    <LayersPanel />
    <CanvasStage />
    <InspectorPanel />
  </div>
  <DnaPanel />
  <SmartAxisPanel />
  <QualityGatePanel />
  <HarmonizerPanel />
  <ResponsiveAutopilotPanel />
  <IntentLocksPanel />
  <SemanticSelectPanel />
</div>
