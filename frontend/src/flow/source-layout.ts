/* Source-faithful page assembly (mirror of app/source_page_layout.py).
 *
 * A captured Source section keeps its document rectangle in meta.pageRect.
 * On the Page node every such section becomes a full-width band: a transparent
 * free section (the page background is painted once on the page root through
 * meta.pageBackground), holding one container
 * ("card", sourceKey "<section>::box") with the original section box at its
 * original x. Consecutive bands from the same capture keep the original gaps
 * and overlaps (band height = distance to the next captured section); foreign
 * sections inserted between bands flow normally and push later bands down. */
import type { IRObject } from "./types";

type IRNode = Record<string, unknown>;

type Rect = { x: number; y: number; width: number; height: number; source?: string };
type Entry = { section: IRNode; ir: IRObject; band: boolean };

const BOX_SUFFIX = "::box";

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function num(value: unknown, fallback = 0): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function pageRectOf(ir: IRObject, viewport?: string): Rect | null {
  const meta = isRecord(ir?.meta) ? ir.meta : {};
  if (viewport && isRecord(meta.pageRectByViewport) && isRecord(meta.pageRectByViewport[viewport])) {
    return meta.pageRectByViewport[viewport] as Rect;
  }
  return isRecord(meta.pageRect) ? (meta.pageRect as Rect) : null;
}

export function isBandable(ir: IRObject): boolean {
  const tree = Array.isArray(ir?.tree) ? ir.tree : [];
  if (tree.length !== 1 || !isRecord(tree[0]) || !pageRectOf(ir)) return false;
  const frame = isRecord(tree[0].frame) ? tree[0].frame : {};
  return frame.layout === "free";
}

/** True when a composed section is a band produced by bandSection. */
export function isSourceBand(section: unknown): section is IRNode {
  if (!isRecord(section) || !Array.isArray(section.children) || section.children.length !== 1) return false;
  const box = section.children[0];
  return isRecord(box) && typeof box.sourceKey === "string" && box.sourceKey.endsWith(BOX_SUFFIX);
}

export function bandSection(section: IRNode, ir: IRObject): IRNode {
  const rect = pageRectOf(ir) || { x: 0, y: 0, width: 1440, height: 0 };
  const frame = isRecord(section.frame) ? { ...section.frame } : {};
  const boxFrame: Record<string, unknown> = {
    ...frame, absolute: true, x: round2(num(rect.x)), y: 0,
    width: round2(num(rect.width, num(frame.width, 1440))),
  };
  if (typeof boxFrame.height !== "number") boxFrame.height = round2(num(rect.height));
  const box: IRNode = {
    type: "card",
    // role marks a captured DOM box: the renderer draws it exactly as styled,
    // without the generated-card surface, border, padding and shadow
    role: "section",
    sourceKey: `${String(section.sourceKey || "root")}${BOX_SUFFIX}`,
    sourceMeta: { kind: "dom", reason: "source section box placed at its page position" },
    style: isRecord(section.style) ? structuredClone(section.style) : {},
    frame: boxFrame,
    children: Array.isArray(section.children) ? section.children : [],
  };
  const responsive: Record<string, Record<string, unknown>> = isRecord(section.responsive)
    ? structuredClone(section.responsive) as Record<string, Record<string, unknown>> : {};
  const meta = isRecord(ir.meta) ? ir.meta : {};
  const byViewport = isRecord(meta.pageRectByViewport) ? meta.pageRectByViewport : {};
  for (const [viewport, vpRect] of Object.entries(byViewport)) {
    if (viewport === "desktop" || !isRecord(vpRect)) continue;
    const override = (responsive[viewport] ||= {});
    override.frame = { ...(isRecord(override.frame) ? override.frame : {}), x: round2(num(vpRect.x)), y: 0, absolute: true };
  }
  if (Object.keys(responsive).length) box.responsive = responsive;
  const band: IRNode = {};
  for (const [key, value] of Object.entries(section)) {
    if (!["style", "frame", "children", "responsive"].includes(key)) band[key] = structuredClone(value);
  }
  band.style = {}; // transparent: the page background is painted once on the page root
  band.frame = { width: "fill", height: boxFrame.height, layout: "free", direction: "column", gap: 0, padding: 0, justify: "start", align: "start" };
  band.children = [box];
  return band;
}

/** The site's page background (a colour or the body gradient over the whole
 *  document). The composed Page paints it once behind every section
 *  (meta.pageBackground); per-band copies restarted the gradient in each band,
 *  and a gradient in `background` was dropped by the renderer, leaving the page
 *  white around cream section boxes. */
export function pageBackgroundOf(entries: Entry[]): string | null {
  for (const entry of entries) {
    const meta = entry.band && isRecord(entry.ir.meta) ? entry.ir.meta : null;
    if (meta && typeof meta.pageBackground === "string" && meta.pageBackground.trim()) return meta.pageBackground;
  }
  return null;
}

/** Band height = distance to the next band of the same capture (per viewport). */
export function settleBandHeights(entries: Entry[]): void {
  entries.forEach((entry, index) => {
    const next = entries[index + 1];
    if (!entry.band || !next || !next.band) return;
    const here = pageRectOf(entry.ir), there = pageRectOf(next.ir);
    if (!here?.source || here.source !== there?.source) return;
    const band = entry.section;
    const frame = band.frame as Record<string, unknown>;
    const box = (band.children as IRNode[])[0];
    const distance = num(there.y) - num(here.y);
    frame.height = round2(Math.max(1, distance));
    if (distance < num((box.frame as Record<string, unknown>).height)) frame.clip = false;
    const meta = isRecord(entry.ir.meta) ? entry.ir.meta : {};
    const nextMeta = isRecord(next.ir.meta) ? next.ir.meta : {};
    const byViewport = isRecord(meta.pageRectByViewport) ? meta.pageRectByViewport : {};
    const nextByViewport = isRecord(nextMeta.pageRectByViewport) ? nextMeta.pageRectByViewport : {};
    for (const [viewport, vpRect] of Object.entries(byViewport)) {
      const nextRect = nextByViewport[viewport];
      if (viewport === "desktop" || !isRecord(vpRect) || !isRecord(nextRect)) continue;
      const responsive = (band.responsive ||= {}) as Record<string, Record<string, unknown>>;
      (responsive[viewport] ||= {}).frame = { height: round2(Math.max(1, num(nextRect.y) - num(vpRect.y))) };
    }
  });
}
