import { portsOfNode } from "./ports";
import type { FlowEdge, FlowNode, PortKind } from "./types";

/* Цвета проводов — зеркало #wires path в nodes.html: text серый, ir акцентный */
export const WIRE_COLORS: Record<PortKind, string> = {
  text: "#7a7a8c",
  ir: "#5b5bd6",
};

/* Зеркало clone() (nodes.js:74) */
export function deepClone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v));
}

/* Зеркало outValue (nodes.js:923-932) — значение выходного порта ноды */
export function outValue(n: FlowNode): unknown {
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
    case "clone":
      return n.data.ir || null;
    case "reproduce":
      return n.data.result ? n.data.result.ir || null : null;
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
  return src ? outValue(src) : null;
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
