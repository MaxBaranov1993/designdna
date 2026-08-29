<script lang="ts">
  /* Верхний тулбар DNA-редактора: зум, вьюпорты, выравнивание, история, Style DNA,
   * закрыть/сохранить. Разметка 1:1 из legacy editor.js (data-act — контракт тестов).
   * Динамика (zoom-текст, hidden-группы, disabled undo/redo) — императивно через dom-refs
   * контроллера, Svelte эти атрибуты не трогает. */
  import * as ctl from "./controller";

  let zoomLabel: HTMLButtonElement | null = $state(null);
  let viewports: HTMLSpanElement | null = $state(null);
  let viewportWidth: HTMLInputElement | null = $state(null);
  let responsiveSep: HTMLSpanElement | null = $state(null);

  $effect(() => {
    ctl.dom.zoomLabel = zoomLabel;
    ctl.dom.viewports = viewports;
    ctl.dom.viewportWidth = viewportWidth;
    ctl.dom.responsiveSep = responsiveSep;
    ctl.syncToolbarState();
  });
</script>

<div class="fe-toolbar">
  <span class="fe-logo">✦ DNA Editor</span>
  <button class="fe-tbtn" data-act="zoom-out" title="Уменьшить" aria-label="Уменьшить" onclick={() => ctl.handleAct("zoom-out")}>−</button>
  <button class="fe-zoom" bind:this={zoomLabel} aria-live="polite" title="Сбросить зум до 100%" aria-label="Сбросить зум до 100%" onclick={() => ctl.zoomReset()}>100%</button>
  <button class="fe-tbtn" data-act="zoom-in" title="Увеличить" aria-label="Увеличить" onclick={() => ctl.handleAct("zoom-in")}>+</button>
  <button class="fe-tbtn" data-act="zoom-fit" title="Вписать" aria-label="Вписать" onclick={() => ctl.handleAct("zoom-fit")}>⊡</button>
  <span class="fe-sep"></span>
  <span class="fe-viewports" hidden bind:this={viewports}>
    <button class="fe-tbtn fe-viewport-btn active" data-viewport="desktop" title="Desktop 1440 px" aria-pressed="true" onclick={() => ctl.setViewport("desktop")}>
      <svg class="fe-device-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2"></rect><path d="M8 21h8M12 17v4"></path></svg>
      <span>Desktop</span>
    </button>
    <button class="fe-tbtn fe-viewport-btn" data-viewport="tablet" title="Tablet 834 px" aria-pressed="false" onclick={() => ctl.setViewport("tablet")}>
      <svg class="fe-device-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="2" width="14" height="20" rx="2"></rect><path d="M10 18h4"></path></svg>
      <span>Tablet</span>
    </button>
    <button class="fe-tbtn fe-viewport-btn" data-viewport="mobile" title="Mobile 390 px" aria-pressed="false" onclick={() => ctl.setViewport("mobile")}>
      <svg class="fe-device-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="2"></rect><path d="M10 18h4"></path></svg>
      <span>Mobile</span>
    </button>
    <input
      class="fe-viewport-width"
      type="number"
      min={320}
      max={2560}
      step={1}
      value={1440}
      title="Custom canvas width"
      aria-label="Ширина холста"
      bind:this={viewportWidth}
      oninput={(e) => ctl.setPreviewWidth(e.currentTarget.value)}
    />
  </span>
  <span class="fe-sep fe-responsive-sep" hidden bind:this={responsiveSep}></span>
  <span class="fe-spacer"></span>
  <button class="fe-btn danger" data-act="close" aria-label="Закрыть редактор" onclick={() => ctl.handleAct("close")}>Закрыть</button>
  <button class="fe-btn primary" data-act="save" aria-label="Сохранить" aria-keyshortcuts="Control+S" onclick={() => ctl.handleAct("save")}>💾 Сохранить</button>
</div>
