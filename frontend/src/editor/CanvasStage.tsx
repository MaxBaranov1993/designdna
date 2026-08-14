/* Канвас DNA-редактора: линейки, рейка инструментов, .fe-canvas-inner — хост
 * IRRenderer + GeoEdit (императивные движки). Pan/wheel-zoom навешиваются один раз
 * нативными слушателями (wheel нужен non-passive), логика — в контроллере. */
import { useEffect } from "react";
import * as ctl from "./controller";
import { ToolRail } from "./ToolRail";

export function CanvasStage() {
  useEffect(() => {
    const canvas = ctl.dom.canvas;
    if (!canvas) return;
    const onDown = (e: PointerEvent) => ctl.onCanvasPointerDown(e);
    const onWheel = (e: WheelEvent) => ctl.onCanvasWheel(e);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    // линейки перерисовываем и при ресайзе окна
    const onResize = () => ctl.drawRulers();
    window.addEventListener("resize", onResize);
    return () => {
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("wheel", onWheel);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <div className="fe-canvas" ref={(el) => { ctl.dom.canvas = el; }}>
      <div className="fe-ruler-corner"></div>
      <div className="fe-ruler-h"><canvas ref={(el) => { ctl.dom.rulerH = el; }}></canvas></div>
      <div className="fe-ruler-v"><canvas ref={(el) => { ctl.dom.rulerV = el; }}></canvas></div>
      <div className="fe-guide-layer" ref={(el) => { ctl.dom.guideLayer = el; }}></div>
      <ToolRail />
      <div className="fe-canvas-inner" ref={(el) => { ctl.dom.canvasInner = el; }}></div>
    </div>
  );
}
