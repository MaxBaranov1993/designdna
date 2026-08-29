<script lang="ts">
  /* Канвас DNA-редактора: линейки, рейка инструментов, .fe-canvas-inner — хост
   * IRRenderer + GeoEdit (императивные движки). Pan/wheel-zoom навешиваются один раз
   * нативными слушателями (wheel нужен non-passive), логика — в контроллере. */
  import * as ctl from "./controller";
  import { editorUi } from "./state";
  import ToolRail from "./ToolRail.svelte";

  /* Статус-чип внизу канваса: активный инструмент + шаг привязки */
  const TOOL_NAMES: Record<string, string> = {
    select: "Выделение", hand: "Рука", frame: "Фрейм", rect: "Прямоугольник",
    ellipse: "Эллипс", line: "Линия", image: "Изображение", text: "Текст",
  };

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
  <div class="fe-status" aria-live="polite">
    <span class="fe-status-tool">{TOOL_NAMES[$editorUi.tool] || $editorUi.tool}</span>
    <span class="fe-status-sep">·</span>
    <span class="fe-status-grid">{$editorUi.snap ? `сетка ${$editorUi.snapStep}px` : "сетка выкл"}</span>
  </div>
</div>
