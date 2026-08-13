import { useEffect, useRef, useState } from "react";
import type { MouseEventHandler } from "react";
import { deepClone } from "../flow/dataflow";
import type { IRObject, SourceViewport } from "../flow/types";
import { cn } from "../lib/utils";

declare global {
  interface Window {
    IRRenderer?: {
      renderIR: (
        container: HTMLElement,
        ir: IRObject,
        options?: { viewport?: SourceViewport; fit?: boolean },
      ) => void;
      materializeResponsiveIR: (ir: IRObject, viewport: string) => IRObject;
      fitPreview: (container: HTMLElement, inner?: HTMLElement | null) => void;
      DESIGN_WIDTH: number;
    };
  }
}

export function IrPreview({
  ir,
  height = 180,
  empty = "IR появится после запуска",
  className,
  viewport,
  fitHeight = false,
  minHeight = 32,
  interactive = false,
  onClickCapture,
}: {
  ir: IRObject | null;
  height?: number;
  empty?: string;
  className?: string;
  viewport?: SourceViewport;
  fitHeight?: boolean;
  minHeight?: number;
  interactive?: boolean;
  onClickCapture?: MouseEventHandler<HTMLDivElement>;
}) {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const [measuredHeight, setMeasuredHeight] = useState<number | null>(null);

  const syncPreviewSize = () => {
    const el = innerRef.current;
    if (!el || !window.IRRenderer) return;
    window.IRRenderer.fitPreview(el);
    if (!fitHeight || !ir) return;
    const renderedHeight = Number.parseFloat(el.style.height) || el.getBoundingClientRect().height;
    const nextHeight = Math.max(minHeight, Math.min(height, Math.ceil(renderedHeight)));
    setMeasuredHeight((current) => current === nextHeight ? current : nextHeight);
  };

  useEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    if (!ir || !window.IRRenderer) {
      el.innerHTML = "";
      setMeasuredHeight(null);
      return;
    }

    const meta = ir.meta && typeof ir.meta === "object" && !Array.isArray(ir.meta)
      ? ir.meta as Record<string, unknown>
      : {};
    const activeViewport = viewport || (
      meta.activeViewport === "desktop" || meta.activeViewport === "tablet" || meta.activeViewport === "mobile"
        ? meta.activeViewport
        : undefined
    );
    window.IRRenderer.renderIR(el, deepClone(ir), activeViewport ? { viewport: activeViewport } : undefined);
    const frame = requestAnimationFrame(syncPreviewSize);
    return () => cancelAnimationFrame(frame);
  }, [ir, viewport, fitHeight, height, minHeight]);

  useEffect(() => {
    const outer = outerRef.current;
    if (!outer || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(syncPreviewSize);
    ro.observe(outer);
    return () => ro.disconnect();
  }, [ir, fitHeight, height, minHeight]);

  return (
    <div
      ref={outerRef}
      className={cn("ir-preview", interactive && "ir-preview-interactive", className)}
      style={{ height: fitHeight && ir && measuredHeight !== null ? measuredHeight : height }}
      onClickCapture={onClickCapture}
    >
      <div ref={innerRef} className="ir-preview-inner" />
      {!ir && empty ? <div className="ir-preview-empty">{empty}</div> : null}
    </div>
  );
}
