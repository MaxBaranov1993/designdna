import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useEditorStore } from "./store";
import * as ctl from "./controller";
import { cn } from "../lib/utils";

type ToolDef = { tool: string; title: string; icon: ReactNode };

const ICONS: Record<string, ReactNode> = {
  select: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 1l11 6.5-5 1.2L7.5 14z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>,
  frame: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M5 1v14M11 1v14M1 5h14M1 11h14" stroke="currentColor" strokeWidth="1.2" fill="none" /></svg>,
  rect: <svg width="14" height="14" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>,
  ellipse: <svg width="14" height="14" viewBox="0 0 16 16"><ellipse cx="8" cy="8" rx="5.5" ry="4" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>,
  line: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 13L13 3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" /></svg>,
  text: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 3h10M8 3v10" stroke="currentColor" strokeWidth="1.4" fill="none" /></svg>,
  image: <svg width="14" height="14" viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="1" fill="none" stroke="currentColor" strokeWidth="1.2" /><circle cx="5.5" cy="6.5" r="1.2" fill="currentColor" /><path d="M2.5 12l3.5-3 2.5 2 3-2.5 2 1.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" /></svg>,
  ai: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M8 1.5l1.2 4.1L13.5 7l-4.3 1.4L8 12.5l-1.2-4.1L2.5 7l4.3-1.4L8 1.5zM12.5 10.5l.5 1.5 1.5.5-1.5.5-.5 1.5-.5-1.5-1.5-.5 1.5-.5.5-1.5z" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" /></svg>,
};

const SHAPE_GROUP: ToolDef[] = [
  { tool: "rect", title: "Прямоугольник (R)", icon: ICONS.rect },
  { tool: "ellipse", title: "Эллипс (O)", icon: ICONS.ellipse },
  { tool: "line", title: "Линия (L)", icon: ICONS.line },
  { tool: "image", title: "Изображение (I)", icon: ICONS.image },
];
const SHAPE_TOOLS = SHAPE_GROUP.map((t) => t.tool);
const SINGLE_TOOLS: ToolDef[] = [
  { tool: "select", title: "Выбор (V)", icon: ICONS.select },
  { tool: "frame", title: "Фрейм (F)", icon: ICONS.frame },
];

export function ToolRail() {
  const tool = useEditorStore((s) => s.tool);
  const aiOpen = useEditorStore((s) => s.aiOpen);
  const [flyOpen, setFlyOpen] = useState(false);
  const [lastShape, setLastShape] = useState("rect");
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (openTimer.current) clearTimeout(openTimer.current);
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  useEffect(() => {
    if (SHAPE_TOOLS.includes(tool)) setLastShape(tool);
  }, [tool]);

  const scheduleOpen = () => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
    if (openTimer.current) clearTimeout(openTimer.current);
    openTimer.current = setTimeout(() => setFlyOpen(true), 180);
  };
  const scheduleClose = () => {
    if (openTimer.current) { clearTimeout(openTimer.current); openTimer.current = null; }
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setFlyOpen(false), 220);
  };

  const pickShape = (next: string) => {
    ctl.setTool(next);
    setLastShape(next);
    setFlyOpen(false);
  };

  const displayShape = SHAPE_TOOLS.includes(tool) ? tool : lastShape;
  const displayDef = SHAPE_GROUP.find((t) => t.tool === displayShape) || SHAPE_GROUP[0];

  return (
    <div className="fe-rail" aria-label="Инструменты">
      {SINGLE_TOOLS.map((t) => (
        <button key={t.tool} className={cn("fe-rail-btn", tool === t.tool && "active")} data-tool={t.tool} data-tip={t.title} aria-label={t.title} onClick={() => ctl.setTool(t.tool)}>
          {t.icon}
        </button>
      ))}

      <div className="fe-rail-group" onMouseEnter={scheduleOpen} onMouseLeave={scheduleClose}>
        <button
          className={cn("fe-rail-btn", SHAPE_TOOLS.includes(tool) && "active")}
          data-tool="rect"
          data-flyout="shapes"
          data-tip="Фигура"
          aria-label="Фигура"
          onClick={() => ctl.setTool(displayShape)}
        >
          {displayDef.icon}<span className="fe-fly-arrow">▾</span>
        </button>
        {flyOpen && (
          <div className="fe-rail-flyout" onMouseEnter={() => { if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; } }} onMouseLeave={scheduleClose}>
            {SHAPE_GROUP.map((t) => (
              <button key={t.tool} className={cn("fe-rail-btn", tool === t.tool && "active")} data-tool={t.tool} data-fly-item={t.tool} data-tip={t.title} aria-label={t.title} onClick={() => pickShape(t.tool)}>
                {t.icon}
              </button>
            ))}
          </div>
        )}
      </div>

      <button className={cn("fe-rail-btn", tool === "text" && "active")} data-tool="text" data-tip="Текст (T)" aria-label="Текст (T)" onClick={() => ctl.setTool("text")}>
        {ICONS.text}
      </button>

      <button className={cn("fe-rail-btn fe-rail-ai", aiOpen && "active")} data-tool="ai" data-tip="AI‑ассистент" aria-label="AI‑ассистент" onClick={ctl.openAiPanel}>
        {ICONS.ai}
      </button>
    </div>
  );
}
