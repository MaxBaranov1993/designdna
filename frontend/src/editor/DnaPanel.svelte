<script lang="ts">
  /* Slide-over панель Style DNA. Каркас — Svelte (id/классы — контракт тестов
   * ui_style_dna_test.py / ui_style_projection_test.py), тело #feDnaBody заполняет
   * контроллер (токены, normalize preview, Tailwind projection). */
  import * as ctl from "./controller";

  let dnaPanel: HTMLDivElement | null = $state(null);
  let dnaMode: HTMLSpanElement | null = $state(null);
  let dnaBody: HTMLDivElement | null = $state(null);
  let dnaFoot: HTMLDivElement | null = $state(null);

  $effect(() => {
    ctl.dom.dnaPanel = dnaPanel;
    ctl.dom.dnaMode = dnaMode;
    ctl.dom.dnaBody = dnaBody;
    ctl.dom.dnaFoot = dnaFoot;
  });
</script>

<div class="fe-dna-panel" id="feDnaPanel" bind:this={dnaPanel}>
  <div class="fe-dna-head">
    <h3>🧬 Style DNA</h3>
    <span class="fe-dna-tag" id="feDnaMode" bind:this={dnaMode}>light</span>
    <button class="fe-tbtn" data-act="close-style-dna" title="Закрыть" onclick={() => ctl.handleAct("close-style-dna")}>✕</button>
  </div>
  <div class="fe-dna-body" id="feDnaBody" bind:this={dnaBody}>
    <div class="fe-dna-empty">Загрузка токенов…</div>
  </div>
  <div class="fe-dna-foot" id="feDnaFoot" bind:this={dnaFoot}></div>
  <div class="fe-dna-actions">
    <button class="fe-btn" data-act="reset-style-dna" onclick={() => ctl.handleAct("reset-style-dna")}>Сбросить</button>
    <button class="fe-btn primary" data-act="apply-style-dna" onclick={() => ctl.handleAct("apply-style-dna")}>Применить</button>
  </div>
</div>
