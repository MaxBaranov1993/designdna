/* Левая рейка инструментов (модель pen.dev/Figma): 8 инструментов с хоткеями.
 * Активный инструмент — из zustand-стора; ellipse/line/image добавляются в geoedit
 * параллельно, контроллер gracefully откатывается на select, если движок их ещё не знает. */
import type { ReactNode } from "react";
import { useEditorStore } from "./store";
import * as ctl from "./controller";
import { cn } from "../lib/utils";

const TOOLS: { tool: string; title: string; icon: ReactNode }[] = [
  {
    tool: "select", title: "Выделение (V)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 1l11 6.5-5 1.2L7.5 14z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>,
  },
  {
    tool: "hand", title: "Рука — панорама (H)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M8 2v12M2 8h12M8 2L6 4M8 2l2 2M8 14l-2-2M8 14l2-2M2 8l2-2M2 8l2 2M14 8l-2-2M14 8l-2 2" stroke="currentColor" strokeWidth="1.1" fill="none" /></svg>,
  },
  {
    tool: "frame", title: "Фрейм (F)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M5 1v14M11 1v14M1 5h14M1 11h14" stroke="currentColor" strokeWidth="1.2" fill="none" /></svg>,
  },
  {
    tool: "rect", title: "Прямоугольник (R)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>,
  },
  {
    tool: "ellipse", title: "Эллипс (O)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><ellipse cx="8" cy="8" rx="5.5" ry="4" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>,
  },
  {
    tool: "line", title: "Линия (L)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 13L13 3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" /></svg>,
  },
  {
    tool: "text", title: "Текст (T)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 3h10M8 3v10" stroke="currentColor" strokeWidth="1.4" fill="none" /></svg>,
  },
  {
    tool: "image", title: "Изображение (I)",
    icon: <svg width="14" height="14" viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="1" fill="none" stroke="currentColor" strokeWidth="1.2" /><circle cx="5.5" cy="6.5" r="1.2" fill="currentColor" /><path d="M2.5 12l3.5-3 2.5 2 3-2.5 2 1.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" /></svg>,
  },
];

export function ToolRail() {
  const tool = useEditorStore((s) => s.tool);
  return (
    <div className="fe-rail">
      {TOOLS.map((t) => (
        <button
          key={t.tool}
          className={cn("fe-rail-btn", tool === t.tool && "active")}
          data-tool={t.tool}
          data-tip={t.title}
          aria-label={t.title}
          onClick={() => ctl.setTool(t.tool)}
        >
          {t.icon}
        </button>
      ))}
    </div>
  );
}
