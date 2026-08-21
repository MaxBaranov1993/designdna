import { deepClone } from "./dataflow";
import type { IRObject, SourceViewport } from "./types";

/* Ширины артборда по вьюпортам — зеркало DEFAULT_SOURCE_VIEWPORTS (scraper.py). */
export const PAGE_VIEWPORT_WIDTHS: Record<SourceViewport, number> = {
  desktop: 1440,
  tablet: 768,
  mobile: 390,
};

const PAGE_VIEWPORT_FALLBACK_HEIGHTS: Record<SourceViewport, number> = {
  desktop: 900,
  tablet: 1024,
  mobile: 844,
};

/* Сборка страницы из блоков (нода Page): детерминированно, без LLM.
 * Порядок blocks = порядок секций на странице. id секций и sourceKey
 * дедуплицируются между блоками (у Source Import все секции — "imported-block");
 * токены: style DNA с провода > токены последнего стилизованного блока; секции получают
 * width:"fill" внутрь артборда 1440; per-section responsive-override'ы
 * хранятся в самих узлах и переживают сборку как есть. */

type IRNode = Record<string, unknown>;
type ColorRole = "background" | "surface" | "text" | "textMuted" | "border" | "primary" | "accent";

function isRecord(v: unknown): v is Record<string, unknown> {
  return Boolean(v && typeof v === "object" && !Array.isArray(v));
}

function hex(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const s = v.trim();
  if (/^#[0-9a-f]{3}$/i.test(s)) return "#" + s.slice(1).split("").map((c) => c + c).join("").toLowerCase();
  if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
  return null;
}

function rgb(color: string): [number, number, number] {
  return [
    parseInt(color.slice(1, 3), 16),
    parseInt(color.slice(3, 5), 16),
    parseInt(color.slice(5, 7), 16),
  ];
}

function luminance(color: string): number {
  const [r, g, b] = rgb(color).map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const hi = Math.max(luminance(a), luminance(b));
  const lo = Math.min(luminance(a), luminance(b));
  return (hi + 0.05) / (lo + 0.05);
}

function dist(a: string, b: string): number {
  const ar = rgb(a);
  const br = rgb(b);
  return Math.sqrt((ar[0] - br[0]) ** 2 + (ar[1] - br[1]) ** 2 + (ar[2] - br[2]) ** 2);
}

function colorTokens(tokens: unknown): Partial<Record<ColorRole, string>> {
  const c = isRecord(tokens) && isRecord(tokens.color) ? tokens.color : {};
  const primary = hex(c.primary) || "#5b5bd6";
  const background = hex(c.background) || (hex(c.mode) === "#000000" ? "#0b0b0d" : "#ffffff");
  const dark = luminance(background) < 0.2;
  return {
    background,
    surface: hex(c.surface) || (dark ? "#16161a" : "#f5f5f7"),
    text: hex(c.text) || (dark ? "#f8fafc" : "#171717"),
    textMuted: hex(c.textMuted) || hex(c.muted) || (dark ? "#a1a1aa" : "#666666"),
    border: hex(c.border) || (dark ? "#2a2a32" : "#e0e0e0"),
    primary,
    accent: hex(c.accent) || hex(c.secondary) || primary,
  };
}

function nearestRole(color: string, palette: Partial<Record<ColorRole, string>>, preferred: ColorRole[]): ColorRole {
  const roles = preferred.filter((role) => palette[role]);
  let best = roles[0] || "text";
  let bestDist = Number.POSITIVE_INFINITY;
  for (const role of roles) {
    const candidate = palette[role];
    if (!candidate) continue;
    const d = dist(color, candidate);
    if (d < bestDist) {
      best = role;
      bestDist = d;
    }
  }
  return best;
}

function readable(fg: string, bg: string): string {
  if (contrast(fg, bg) >= 4.5) return fg;
  const light = "#ffffff";
  const dark = "#111111";
  return contrast(light, bg) >= contrast(dark, bg) ? light : dark;
}

function adaptStyleValue(
  value: unknown,
  source: Partial<Record<ColorRole, string>>,
  target: Partial<Record<ColorRole, string>>,
  prop: "background" | "color" | "borderColor",
  bg: string,
): string | null {
  const color = hex(value);
  if (!color) return null;
  const preferred =
    prop === "background"
      ? (["background", "surface", "primary", "accent", "border"] as ColorRole[])
      : prop === "borderColor"
        ? (["border", "primary", "accent", "surface"] as ColorRole[])
        : (["text", "textMuted", "primary", "accent"] as ColorRole[]);
  const role = nearestRole(color, source, preferred);
  const mapped = target[role] || target.text || color;
  return prop === "color" ? readable(mapped, bg) : mapped;
}

function adaptNodeStyle(node: IRNode, source: Partial<Record<ColorRole, string>>, target: Partial<Record<ColorRole, string>>, parentBg: string): void {
  const style = isRecord(node.style) ? { ...node.style } : null;
  let bg = parentBg;
  if (style) {
    const nextBg = adaptStyleValue(style.background, source, target, "background", parentBg);
    if (nextBg) {
      style.background = nextBg;
      bg = nextBg;
    }
    const nextBorder = adaptStyleValue(style.borderColor, source, target, "borderColor", bg);
    if (nextBorder) style.borderColor = nextBorder;
    const nextColor = adaptStyleValue(style.color, source, target, "color", bg);
    if (nextColor) style.color = nextColor;
    node.style = style;
  }
  const children = node.children;
  if (Array.isArray(children)) {
    for (const child of children) {
      if (isRecord(child)) adaptNodeStyle(child, source, target, bg);
    }
  }
}

function adaptSectionToStyleDna(section: IRNode, blockTokens: unknown, targetTokens: IRObject | null): void {
  if (!targetTokens) return;
  // Imported DOM/source blocks are literal captures. Page-level Style DNA may
  // style generated content around them, but must never recolor the source
  // component itself (especially navigation/header chrome).
  if (section.type === "source-block" || section.variant === "dom-capture") return;
  const source = colorTokens(blockTokens);
  const target = colorTokens(targetTokens);
  const bg = target.background || "#ffffff";
  adaptNodeStyle(section, source, target, bg);
  const frame = isRecord(section.frame) ? { ...section.frame } : {};
  if (typeof frame.background === "string") {
    const mapped = adaptStyleValue(frame.background, source, target, "background", bg);
    if (mapped) frame.background = mapped;
    section.frame = frame;
  }
  const responsive = isRecord(section.responsive) && isRecord(section.responsive.viewports) ? section.responsive.viewports : null;
  if (responsive) {
    for (const vp of Object.values(responsive)) {
      const style = isRecord(vp) && isRecord(vp.style) ? vp.style : null;
      if (!style) continue;
      const nextBg = adaptStyleValue(style.background, source, target, "background", bg);
      if (nextBg) style.background = nextBg;
      const nextColor = adaptStyleValue(style.color, source, target, "color", nextBg || bg);
      if (nextColor) style.color = nextColor;
      const nextBorder = adaptStyleValue(style.borderColor, source, target, "borderColor", nextBg || bg);
      if (nextBorder) style.borderColor = nextBorder;
    }
  }
}

function walk(node: IRNode, fn: (n: IRNode) => void): void {
  fn(node);
  const children = node.children;
  if (Array.isArray(children)) {
    for (const c of children) {
      if (c && typeof c === "object") walk(c as IRNode, fn);
    }
  }
}

function safeBlockName(name: string): string {
  return name.replace(/[^a-zA-Z0-9_-]/g, "-").replace(/^-+|-+$/g, "") || "block";
}

function prefixSourceKey(blockName: string, key: string): string {
  const name = safeBlockName(blockName);
  if (key.startsWith(`${name}/`)) return key;
  return `${name}/${key}`;
}

function verticalPadding(frame: IRNode): number {
  if (typeof frame.padding === "number") return Math.max(0, frame.padding) * 2;
  if (Array.isArray(frame.padding) && frame.padding.length === 4) {
    const top = typeof frame.padding[0] === "number" ? frame.padding[0] : 0;
    const bottom = typeof frame.padding[2] === "number" ? frame.padding[2] : 0;
    return Math.max(0, top) + Math.max(0, bottom);
  }
  return 0;
}

function viewportNodeFrame(node: IRNode, viewport: SourceViewport): IRNode | null {
  const responsive = isRecord(node.responsive) ? node.responsive : null;
  const override = responsive && isRecord(responsive[viewport]) ? responsive[viewport] : null;
  if (override && override.visible === false) return null;
  return {
    ...(isRecord(node.frame) ? node.frame : {}),
    ...(override && isRecord(override.frame) ? override.frame : {}),
  };
}

function fallbackSectionHeight(node: IRNode): number {
  const type = String(node.type || "").toLowerCase();
  if (type === "header" || type === "navbar" || type === "banner") return 96;
  if (type === "footer") return 320;
  if (type === "hero") return 640;
  return 360;
}

function estimateNodeHeight(node: IRNode, viewport: SourceViewport, section = false): number {
  const frame = viewportNodeFrame(node, viewport);
  if (!frame) return 0;
  if (typeof frame.height === "number" && Number.isFinite(frame.height) && frame.height >= 0) {
    return frame.height;
  }

  const children = Array.isArray(node.children)
    ? node.children.filter((child): child is IRNode => isRecord(child))
    : [];
  if (!children.length) return section ? fallbackSectionHeight(node) : 0;

  const heights = children.map((child) => estimateNodeHeight(child, viewport));
  const gap = typeof frame.gap === "number" ? Math.max(0, frame.gap) : 0;
  const padding = verticalPadding(frame);
  if (frame.layout === "free") {
    let bottom = 0;
    children.forEach((child, index) => {
      const childFrame = viewportNodeFrame(child, viewport);
      if (!childFrame) return;
      const y = typeof childFrame.y === "number" ? childFrame.y : 0;
      bottom = Math.max(bottom, y + heights[index]);
    });
    return Math.max(section ? fallbackSectionHeight(node) : 0, bottom + padding);
  }
  if (frame.direction === "row") {
    return Math.max(section ? fallbackSectionHeight(node) : 0, ...heights) + padding;
  }
  const visibleHeights = heights.filter((height) => height > 0);
  const content = visibleHeights.reduce((sum, height) => sum + height, 0) +
    Math.max(0, visibleHeights.length - 1) * gap + padding;
  return Math.max(section ? fallbackSectionHeight(node) : 0, content);
}

/** Best numeric document height for exports and viewport metadata. The actual
 * page artboard remains height:"hug", so DOM content is still the authority
 * when a generated section has intrinsic text/content height. */
export function pageHeightForViewport(tree: IRNode[], viewport: SourceViewport): number {
  const measured = tree.reduce((sum, section) => sum + estimateNodeHeight(section, viewport, true), 0);
  return measured > 0 ? Math.ceil(measured) : PAGE_VIEWPORT_FALLBACK_HEIGHTS[viewport];
}

export function composePage(
  blocks: { name: string; ir: IRObject }[],
  tokensOverride: IRObject | null,
  activeViewport: SourceViewport = "desktop",
): IRObject {
  // Pages are assembled top-to-bottom (Header first, generated/main content
  // later). Without an explicit DNA wire, the last styled input owns the page
  // look; choosing the first input made Header silently own the whole page.
  const fallbackTokens = [...blocks].reverse().find(({ ir }) => isRecord(ir?.tokens))?.ir.tokens;
  const effectiveTokens = tokensOverride || (isRecord(fallbackTokens) ? fallbackTokens : null);
  const usedIds = new Set<string>();
  const usedKeys = new Set<string>();
  const tree: IRNode[] = [];
  for (const { name, ir } of blocks) {
    const sections = Array.isArray(ir?.tree) ? (ir.tree as IRNode[]) : [];
    for (const sec of sections) {
      const s = deepClone(sec) as IRNode;
      adaptSectionToStyleDna(s, ir?.tokens, effectiveTokens);
      const baseId = String(s.id || "section");
      let id = baseId;
      if (usedIds.has(id)) id = `${baseId}--${name}`;
      let k = 2;
      while (usedIds.has(id)) id = `${baseId}--${name}-${k++}`;
      usedIds.add(id);
      s.id = id;
      walk(s, (n) => {
        if (typeof n.sourceKey === "string" && n.sourceKey) {
          let key = prefixSourceKey(name, n.sourceKey);
          if (usedKeys.has(key)) {
            // Extremely rare: identical keys inside the same block after prefixing.
            // Append a deterministic numeric suffix.
            let i = 2;
            let candidate = `${key}#${i.toString().padStart(3, "0")}`;
            while (usedKeys.has(candidate)) {
              i += 1;
              candidate = `${key}#${i.toString().padStart(3, "0")}`;
            }
            key = candidate;
          }
          n.sourceKey = key;
          usedKeys.add(key);
        }
      });
      // секции обязаны течь в auto-колонке артборда страницы: позиционные остатки
      // блока (x/y/absolute от drag-правок в редакторе) ломали бы вертикальный стек
      const sf: IRNode = { ...((s.frame as IRNode) || {}), width: "fill" };
      delete sf.x;
      delete sf.y;
      delete sf.absolute;
      s.frame = sf;
      tree.push(s);
    }
  }
  return {
    version: "1.1",
    meta: {
      name: "Страница",
      description: blocks.map((b) => b.name).join(" + "),
      activeViewport,
    },
    // Канонический артборд всегда desktop: materializeResponsiveIR подставит
    // ширину активного вьюпорта при рендере, а редактор сохраняет canonical 1440.
    // Auto-height is intentional: the common page artboard follows every
    // section, including generated sections whose intrinsic text height is not
    // knowable until Chromium lays it out. A manual artboard resize replaces
    // "hug" with a numeric height in the editor.
    frame: { width: PAGE_VIEWPORT_WIDTHS.desktop, height: "hug", layout: "auto", direction: "column" },
    // responsive-мета документа: без неё renderer не материализует per-node
    // override'ы (visible/frame/style) и мобильные слои дублируются на десктопе
    responsive: {
      viewports: {
        desktop: { width: PAGE_VIEWPORT_WIDTHS.desktop, height: pageHeightForViewport(tree, "desktop") },
        tablet: { width: PAGE_VIEWPORT_WIDTHS.tablet, height: pageHeightForViewport(tree, "tablet") },
        mobile: { width: PAGE_VIEWPORT_WIDTHS.mobile, height: pageHeightForViewport(tree, "mobile") },
      },
    },
    tokens: deepClone(effectiveTokens || {}),
    tree,
  };
}
