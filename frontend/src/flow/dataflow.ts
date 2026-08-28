import { portsOfNode } from "./ports";
import type { FlowEdge, FlowNode, PortKind, SourceViewport } from "./types";

/* Цвета проводов — зеркало #wires path в nodes.html: text серый, ir акцентный;
 * tokens — янтарный (решение владельца 9) */
export const WIRE_COLORS: Record<PortKind, string> = {
  text: "#8A8A93",
  ir: "#9B5CFF",
  tokens: "#FF691D",
  artifact: "#35B8A0",
  interaction: "#2FBF9F",
  motion: "#E05FB0",
};

/* Глубокое копирование значения между нодами. */
export function deepClone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v));
}

function withSourcePreview(ir: unknown, preview?: string, viewport?: SourceViewport): unknown {
  if (!ir || typeof ir !== "object" || Array.isArray(ir)) return ir;
  const root = ir as Record<string, unknown>;
  const tree = Array.isArray(root.tree) ? root.tree : [];
  const first = tree[0];
  if (!first || typeof first !== "object" || Array.isArray(first)) return ir;
  const sec = first as Record<string, unknown>;
  if (sec.type !== "source-block" && sec.variant !== "dom-capture") return ir;

  const meta = root.meta && typeof root.meta === "object" && !Array.isArray(root.meta)
    ? root.meta as Record<string, unknown>
    : {};
  const nextRoot = viewport ? { ...root, meta: { ...meta, activeViewport: viewport } } : root;
  if (!preview) return nextRoot;

  const props = sec.props && typeof sec.props === "object" && !Array.isArray(sec.props)
    ? (sec.props as Record<string, unknown>)
    : {};
  if (root.sourcePreview || sec.preview || props.sourcePreview) return nextRoot;

  const nextSec = { ...sec, props: { ...props, sourcePreview: preview }, preview };
  return { ...nextRoot, sourcePreview: preview, tree: [nextSec, ...tree.slice(1)] };
}

/* Зеркало outValue (nodes.js:923-932) — значение выходного порта ноды.
 * port нужен Source Import: у него выходы динамические, по именам зажжённых блоков. */
export function outValue(n: FlowNode, port?: string): unknown {
  switch (n.type) {
    case "prompt":
      return n.data.text || "";
    case "reference":
      return n.data.brief || (n.data.fileName ? "Референс: " + n.data.fileName : "");
    case "generator":
      return n.data.variants.length ? n.data.variants[n.data.active] || null : null;
    case "edit":
      return n.data.ir || null;
    case "mix":
      return n.data.ir || null;
    case "page": {
      const ir = n.data.ir;
      if (!ir) return null;
      // активный вьюпорт едет вниз по графу: edit/preview материализуют тот же
      const meta = ir.meta && typeof ir.meta === "object" && !Array.isArray(ir.meta)
        ? (ir.meta as Record<string, unknown>)
        : {};
      return { ...ir, meta: { ...meta, activeViewport: n.data.activeViewport } };
    }
    case "sourceimport":
      if (port === "artifact") return n.data.sourceArtifact || null;
      if (port === "tokens") return n.data.tokens || null;
      {
        const block = n.data.blocks.find((b) => b.name === port && b.lit);
        const preview = block?.previews?.[n.data.activeViewport] || block?.preview;
        return block ? withSourcePreview(block.ir || null, preview, n.data.activeViewport) : null;
      }
    case "designui":
      return n.data.artifact || null;
    // Design System заменил ноду Style DNA: наружу уходят токены системы —
    // семантические (styleGuide.tokens) либо, если ревизия старая, измеренные
    // foundations. Документ в ноде — кэш, при ссылке на ревизию порт пуст,
    // пока панель не подтянет документ.
    case "designsystem": {
      const document = n.data.document as Record<string, unknown> | null | undefined;
      if (!document || typeof document !== "object") return null;
      const styleGuide = document.styleGuide as Record<string, unknown> | undefined;
      const semantic = styleGuide?.tokens as Record<string, unknown> | undefined;
      if (semantic && Object.keys(semantic).length) return semantic;
      const foundations = document.foundations as Record<string, unknown> | undefined;
      return foundations && Object.keys(foundations).length ? foundations : null;
    }
    case "derive":
      return n.data.variants.length ? n.data.variants[n.data.active] || null : null;
    case "reskin":
      return n.data.ir || null;
    case "qualitypass":
      return n.data.ir || null;
    case "recorder":
      return n.data.interaction || null;
    case "motion":
      return n.data.motion || null;
    case "pagebridge":
      return n.data.ir || null;
  }
}

/* Зеркало pullInput (nodes.js:934-939) — pull-модель: значение входа тянется от источника */
export function pullInput(
  nodes: FlowNode[],
  edges: FlowEdge[],
  n: FlowNode,
  port: string,
): unknown {
  const e = edges.find((ed) => ed.target === n.id && ed.targetHandle === port);
  if (!e) return null;
  const src = nodes.find((x) => x.id === e.source);
  return src ? outValue(src, e.sourceHandle ?? undefined) : null;
}

/* Зеркало edgeKind (nodes.js:988-993): kind провода наследуется от выходного порта источника */
export function edgeKindOf(nodes: FlowNode[], e: FlowEdge): PortKind {
  const src = nodes.find((n) => n.id === e.source);
  if (!src) return "text";
  const p = portsOfNode(src).out.find((pp) => pp.name === e.sourceHandle);
  return p ? p.kind : "text";
}

/* Зеркало reachable (nodes.js:1032-1047): DFS по рёбрам, есть ли путь fromId -> toId
 * (используется для проверки циклов в connect) */
export function reachable(fromId: number, toId: number, edges: FlowEdge[]): boolean {
  const stack = [fromId];
  const seen = new Set<number>();
  while (stack.length) {
    const cur = stack.pop() as number;
    if (cur === toId) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of edges) {
      if (Number(e.source) === cur) stack.push(Number(e.target));
    }
  }
  return false;
}
