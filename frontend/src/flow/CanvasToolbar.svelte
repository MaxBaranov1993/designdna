<script lang="ts">
  import { useSvelteFlow, useViewport } from "@xyflow/svelte";
  import { flowGraphHistory } from "./state";
  import { useFlowStore } from "./store";

  /* Док снизу по центру (Weavy): Выбор / Рука · Отменить / Повторить · «47 % ⌄».
   * Активный инструмент — белая плитка. Зум, «вписать» и миникарта — в dropdown. */
  let { tool = $bindable("select"), showMinimap = $bindable(false), handActive, selectedCount }: {
    tool: "select" | "hand"; showMinimap: boolean; handActive: boolean; selectedCount: number;
  } = $props();
  const rf = useSvelteFlow();
  const viewport = useViewport();
  let zoomOpen = $state(false);
  const duration = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180;
  const zoomTo = (zoom: number) => {
    const canvas = document.querySelector(".dna-canvas .svelte-flow");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const center = rf.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    void rf.setCenter(center.x, center.y, { zoom, duration: duration() });
    zoomOpen = false;
  };
  const fit = (selected = false) => {
    const nodes = useFlowStore.getState().nodes.filter((node) => !selected || node.selected);
    if (nodes.length) void rf.fitView({ nodes, padding: 0.2, maxZoom: 1, duration: duration() });
    zoomOpen = false;
  };
  const closeOnOutside = (node: HTMLElement) => {
    const onDown = (event: MouseEvent) => {
      if (!node.contains(event.target as Node)) zoomOpen = false;
    };
    window.addEventListener("mousedown", onDown, true);
    return { destroy: () => window.removeEventListener("mousedown", onDown, true) };
  };
</script>

<div class="canvas-dock nodrag nopan nowheel" role="toolbar" aria-label="Навигация по канвасу" use:closeOnOutside>
  <button title="Выбор и рамка (V)" aria-label="Выбор" aria-pressed={!handActive} onclick={() => tool = "select"}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 3 15 9-7 2-3 7Z" /></svg>
  </button>
  <button title="Рука (H) · удерживайте пробел для временного перемещения" aria-label="Рука" aria-pressed={handActive} onclick={() => tool = "hand"}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 12V6a2 2 0 0 1 4 0v5-7a2 2 0 0 1 4 0v7-4a2 2 0 0 1 4 0v8c0 4-3 7-7 7-3 0-4-2-6-4l-3-4a2 2 0 0 1 3-2l1 1" /></svg>
  </button>
  <span class="dock-divider"></span>
  <button id="btn-undo" title="Отменить (Ctrl+Z)" aria-label="Отменить последнее изменение графа" disabled={!$flowGraphHistory.past.length} onclick={() => useFlowStore.getState().undoGraph()}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5-5 5 5 5M4 10h10a6 6 0 0 1 0 12" transform="translate(0 -2)" /></svg>
  </button>
  <button id="btn-redo" title="Повторить (Ctrl+Shift+Z)" aria-label="Повторить отменённое изменение графа" disabled={!$flowGraphHistory.future.length} onclick={() => useFlowStore.getState().redoGraph()}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5 5 5-5 5m5-5H10a6 6 0 0 0 0 12" transform="translate(0 -2)" /></svg>
  </button>
  <span class="dock-divider"></span>
  <div class="dock-zoom">
    <button class="dock-percent" title="Масштаб и навигация" aria-label="Масштаб" aria-haspopup="menu" aria-expanded={zoomOpen} onclick={() => (zoomOpen = !zoomOpen)}>
      <span>{Math.round(viewport.current.zoom * 100)}%</span>
      <svg viewBox="0 0 24 24" aria-hidden="true" class="chev"><path d="m6 9 6 6 6-6" /></svg>
    </button>
    {#if zoomOpen}
      <div class="dock-menu" role="menu">
        <button role="menuitem" onclick={() => void rf.zoomIn({ duration: duration() }).then(() => (zoomOpen = false))}><span>Увеличить</span><kbd>Ctrl +</kbd></button>
        <button role="menuitem" onclick={() => void rf.zoomOut({ duration: duration() }).then(() => (zoomOpen = false))}><span>Уменьшить</span><kbd>Ctrl −</kbd></button>
        <button role="menuitem" onclick={() => zoomTo(1)}><span>Масштаб 100 %</span><kbd>Ctrl 0</kbd></button>
        <button role="menuitem" onclick={() => zoomTo(0.5)}><span>Масштаб 50 %</span></button>
        <span class="dock-menu-sep"></span>
        <button id="btn-fit" role="menuitem" onclick={() => fit()}><span>Вписать весь граф</span><kbd>Shift 1</kbd></button>
        <button role="menuitem" disabled={!selectedCount} onclick={() => fit(true)}><span>Вписать выделенное</span><kbd>Shift 2</kbd></button>
        <span class="dock-menu-sep"></span>
        <button role="menuitemcheckbox" aria-checked={showMinimap} onclick={() => { showMinimap = !showMinimap; zoomOpen = false; }}><span>Миникарта</span><i class:on={showMinimap}></i></button>
      </div>
    {/if}
  </div>
</div>

<style>
  .canvas-dock { position: absolute; z-index: 12; bottom: 16px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 2px; padding: 5px; border: 1px solid var(--dna-border); border-radius: var(--r-panel); background: var(--dna-panel); box-shadow: var(--shadow-panel); max-width: calc(100% - 24px); }
  button { display: grid; place-items: center; flex-shrink: 0; width: 34px; height: 34px; border: 0; border-radius: 9px; background: transparent; color: var(--dna-text-2); font: inherit; font-size: 12px; cursor: pointer; transition: background var(--dur) var(--ease), color var(--dur) var(--ease); }
  button:hover:not(:disabled) { background: var(--dna-hover); color: var(--dna-text); }
  button[aria-pressed="true"] { background: var(--dna-active-bg); color: var(--dna-active-fg); }
  button[aria-pressed="true"]:hover { background: #fff; color: var(--dna-active-fg); }
  button:focus-visible { outline: 2px solid var(--dna-text); outline-offset: 2px; }
  button:disabled { opacity: .3; cursor: default; }
  .dock-divider { height: 18px; width: 1px; background: var(--dna-border-strong); margin: 0 4px; }
  svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
  .dock-zoom { position: relative; }
  .dock-percent { width: auto; min-width: 64px; grid-auto-flow: column; gap: 4px; padding: 0 8px 0 10px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .dock-percent .chev { width: 12px; height: 12px; color: var(--dna-dim); }
  .dock-menu { position: absolute; left: 50%; bottom: calc(100% + 10px); transform: translateX(-50%); min-width: 220px; padding: 6px; border-radius: 12px; border: 1px solid var(--dna-border); background: var(--dna-panel); box-shadow: var(--shadow-panel); display: flex; flex-direction: column; gap: 2px; }
  .dock-menu button { width: 100%; height: 32px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 10px; border-radius: 7px; font-size: 12px; font-weight: 600; color: var(--dna-text-2); }
  .dock-menu button:hover:not(:disabled) { color: var(--dna-text); }
  .dock-menu kbd { font: 600 10px "Manrope Variable", Manrope, sans-serif; color: var(--dna-dim); }
  .dock-menu i { width: 8px; height: 8px; border-radius: 999px; border: 1.5px solid var(--dna-border-strong); }
  .dock-menu i.on { background: var(--dna-text); border-color: var(--dna-text); }
  .dock-menu-sep { height: 1px; margin: 4px 2px; background: var(--dna-border-soft); }
  @media (max-width: 700px) { .canvas-dock { gap: 0; padding: 4px; bottom: 12px; } button { width: 28px; } .dock-divider { margin: 0 2px; } }
</style>
