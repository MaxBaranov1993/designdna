<script lang="ts">
  import { useSvelteFlow, useViewport } from "@xyflow/svelte";
  import { flowGraphHistory } from "./state";
  import { useFlowStore } from "./store";

  let { tool = $bindable("select"), showMinimap = $bindable(false), handActive, selectedCount }: {
    tool: "select" | "hand"; showMinimap: boolean; handActive: boolean; selectedCount: number;
  } = $props();
  const rf = useSvelteFlow();
  const viewport = useViewport();
  const duration = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180;
  const resetZoom = (event: MouseEvent) => {
    const canvas = (event.currentTarget as HTMLElement).closest(".svelte-flow");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const center = rf.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    void rf.setCenter(center.x, center.y, { zoom: 1, duration: duration() });
  };
  const fit = (selected = false) => {
    const nodes = useFlowStore.getState().nodes.filter((node) => !selected || node.selected);
    if (nodes.length) void rf.fitView({ nodes, padding: 0.2, maxZoom: 1, duration: duration() });
  };
</script>

<div class="canvas-dock nodrag nopan nowheel" role="toolbar" aria-label="Навигация по канвасу">
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
  <button title="Уменьшить" aria-label="Уменьшить масштаб" onclick={() => void rf.zoomOut({ duration: duration() })}>−</button>
  <button class="dock-percent" title="Масштаб 100%" aria-label="Масштаб 100%" onclick={resetZoom}>{Math.round(viewport.current.zoom * 100)}%</button>
  <button title="Увеличить" aria-label="Увеличить масштаб" onclick={() => void rf.zoomIn({ duration: duration() })}>+</button>
  <button id="btn-fit" title="Вписать весь граф (Shift+1)" aria-label="Вписать весь граф" onclick={() => fit()}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5" /></svg>
  </button>
  <button title="Вписать выделенное (Shift+2)" aria-label="Вписать выделенное" disabled={!selectedCount} onclick={() => fit(true)}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/></svg>
  </button>
  <span class="dock-divider"></span>
  <button title="Миникарта" aria-label="Миникарта" aria-pressed={showMinimap} onclick={() => showMinimap = !showMinimap}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M6 8h5v5H6zm8 6h4v3h-4"/></svg>
  </button>
</div>

<style>
  .canvas-dock { position: absolute; z-index: 10; bottom: 20px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 3px; padding: 6px; border: 1px solid var(--dna-border-strong); border-radius: 14px; background: var(--dna-elevated); box-shadow: 0 6px 24px #0005; max-width: calc(100% - 24px); }
  button { display: grid; place-items: center; flex-shrink: 0; width: 34px; height: 34px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--dna-text-2); font: inherit; font-size: 18px; cursor: pointer; }
  button:hover:not(:disabled) { background: var(--dna-hover); color: var(--dna-text); }
  button[aria-pressed="true"] { background: var(--dna-text); color: var(--dna-bg); }
  button[aria-pressed="true"]:hover { background: var(--dna-text-2); color: var(--dna-bg); }
  button:focus-visible { outline: 2px solid var(--dna-action); outline-offset: 2px; }
  button:disabled { opacity: .3; cursor: default; }
  .dock-percent { min-width: 52px; font-size: 12px; font-variant-numeric: tabular-nums; }
  .dock-divider { height: 20px; width: 1px; background: var(--dna-border-strong); margin: 0 4px; }
  svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
  @media (max-width: 700px) { .canvas-dock { gap: 0; padding: 4px; bottom: 12px; } button { width: 28px; } .dock-divider { margin: 0 2px; } }
</style>
