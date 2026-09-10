import type { IRObject } from "../flow/types";

/** A process diagram made entirely from existing, editable IR primitives.
 * Arrows are independent elements; moving a step does not reroute them. */
export function diagramSection(ir: IRObject, title: string, labels: string[]): Record<string, any> {
  const steps = labels.map(v => v.trim()).filter(Boolean);
  if (steps.length < 2 || steps.length > 6 || steps.some(v => v.length > 120)) throw new Error("Укажите от 2 до 6 шагов, до 120 символов в каждом");
  if (title.trim().length > 160) throw new Error("Заголовок должен быть короче 160 символов");
  const tokens = ir.tokens as Record<string, any> || {}, colors = tokens.color || {};
  const width = Math.max(320, Math.min(2560, Number((ir.frame as Record<string, unknown> | undefined)?.width) || 960));
  const ink = colors.text || "#20252B", accent = colors.primary || "#3359AD", surface = colors.surface || "#F3F5F7";
  const vertical = steps.length > 4 || width < 800;
  const gap = 48, margin = 40;
  const titleHeight = title.trim() ? Math.max(58, Math.ceil(title.trim().length / Math.max(10, Math.floor((width - margin * 2) / 18))) * 36) : 0;
  const top = titleHeight ? 50 + titleHeight : margin;
  const cellWidth = vertical ? width - margin * 2 : (width - margin * 2 - gap * (steps.length - 1)) / steps.length;
  const textHeight = Math.max(66, ...steps.map(v => Math.ceil(v.length / Math.max(8, Math.floor((cellWidth - 32) / 11))) * 22));
  const cellHeight = 54 + textHeight;
  const height = vertical ? top + steps.length * cellHeight + (steps.length - 1) * gap + margin : top + cellHeight + margin;
  const children: Record<string, any>[] = [];
  if (title.trim()) children.push({type: "heading", level: 2, text: title.trim(), frame: {x: margin, y: 28, width: width - 2 * margin, height: titleHeight}, style: {fontSize: 30, fontWeight: 700, color: ink, lineHeight: 1.2}});
  steps.forEach((label, i) => {
    const x = vertical ? margin : margin + i * (cellWidth + gap), y = vertical ? top + i * (cellHeight + gap) : top;
    children.push({type: "frame", name: `Шаг ${i + 1}`, frame: {x, y, width: cellWidth, height: cellHeight, layout: "free"}, children: [
      {type: "rect", fill: surface, radius: 12, frame: {x: 0, y: 0, width: cellWidth, height: cellHeight}, style: {borderColor: accent, borderWidth: 1, borderStyle: "solid"}},
      {type: "text", text: String(i + 1).padStart(2, "0"), frame: {x: 16, y: 14, width: cellWidth - 32, height: 20}, style: {fontSize: 12, fontWeight: 700, color: accent, lineHeight: 1.2}},
      {type: "text", text: label, frame: {x: 16, y: 42, width: cellWidth - 32, height: textHeight}, style: {fontSize: 18, color: ink, lineHeight: 1.2}},
    ]});
    if (i < steps.length - 1) children.push({type: "text", name: `Связь ${i + 1} → ${i + 2}`, text: vertical ? "↓" : "→", align: "center",
      frame: {x: vertical ? x + cellWidth / 2 - 20 : x + cellWidth + 4, y: vertical ? y + cellHeight + 4 : y + cellHeight / 2 - 20, width: 40, height: 40},
      style: {fontSize: 28, lineHeight: 1.2, color: accent}});
  });
  return {id: "process-diagram", type: "composition", variant: "default", props: {}, frame: {width, height, layout: "free"}, children};
}
