<script lang="ts">
  /* Канвас DNA-редактора: линейки, рейка инструментов, .fe-canvas-inner — хост
   * IRRenderer + GeoEdit (императивные движки). Pan/wheel-zoom навешиваются один раз
   * нативными слушателями (wheel нужен non-passive), логика — в контроллере. */
  import * as ctl from "./controller";
  import ToolRail from "./ToolRail.svelte";

  let canvas: HTMLDivElement | null = $state(null);
  let canvasInner: HTMLDivElement | null = $state(null);
  let rulerH: HTMLCanvasElement | null = $state(null);
  let rulerV: HTMLCanvasElement | null = $state(null);

  $effect(() => {
    ctl.dom.canvas = canvas;
    ctl.dom.canvasInner = canvasInner;
    ctl.dom.rulerH = rulerH;
    ctl.dom.rulerV = rulerV;
  });

  $effect(() => {
    const el = canvas;
    if (!el) return;
    const onDown = (e: PointerEvent) => ctl.onCanvasPointerDown(e);
    const onWheel = (e: WheelEvent) => ctl.onCanvasWheel(e);
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("wheel", onWheel, { passive: false });
    const onResize = () => ctl.drawRulers();
    window.addEventListener("resize", onResize);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("wheel", onWheel);
      window.removeEventListener("resize", onResize);
    };
  });
</script>

<div class="fe-canvas" bind:this={canvas}>
  <div class="fe-ruler-corner"></div>
  <div class="fe-ruler-h"><canvas bind:this={rulerH}></canvas></div>
  <div class="fe-ruler-v"><canvas bind:this={rulerV}></canvas></div>
  <ToolRail />
  <div class="fe-canvas-inner" bind:this={canvasInner}></div>
</div>
