import { useEffect, useRef } from "react";
import { deepClone } from "../flow/dataflow";
import type { IRObject } from "../flow/types";
import { cn } from "../lib/utils";

declare global {
  interface Window {
    /* Legacy-рендерер (app/static/renderer.js), подключается в index.html.
     * renderIR(container, ir) — рендерит IR и в rAF вызывает fitPreview. */
    IRRenderer?: {
      renderIR: (container: HTMLElement, ir: IRObject) => void;
      fitPreview: (container: HTMLElement, inner?: HTMLElement | null) => void;
      DESIGN_WIDTH: number;
    };
  }
}

/* Превью IR через legacy renderer.js — прямое монтирование в ref-managed div
 * (FLOW-MIGRATION.md §6.3, вариант A): React не управляет children контейнера,
 * GeoEdit/Inspector смогут работать с тем же DOM в Фазе B3.
 * Фиксированная высота + overflow hidden: нода не растягивается на весь IR,
 * fitPreview масштабирует дизайн под ширину контейнера. */
export function IrPreview({
  ir,
  height = 180,
  empty = "IR появится после запуска",
  className,
}: {
  ir: IRObject | null;
  height?: number;
  empty?: string;
  className?: string;
}) {
  const innerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    if (!ir || !window.IRRenderer) {
      el.innerHTML = "";
      return;
    }
    // renderIR мутирует ir (tokens, __path) — рендерим глубокую копию (§6.2A)
    window.IRRenderer.renderIR(el, deepClone(ir));
  }, [ir]);

  // ширина контейнера может измениться — повторяем fit (rAF renderIR — только на первый рендер)
  useEffect(() => {
    const el = innerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (window.IRRenderer) window.IRRenderer.fitPreview(el);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className={cn("ir-preview", className)} style={{ height }}>
      <div ref={innerRef} className="ir-preview-inner" />
      {!ir && empty ? <div className="ir-preview-empty">{empty}</div> : null}
    </div>
  );
}
