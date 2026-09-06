import { pullInput } from "./dataflow";
import type { FlowNode, FlowEdge, TimelineFlowNode, IRObject } from "./types";

export function videoPages(nodes: FlowNode[], edges: FlowEdge[], node: TimelineFlowNode, detached = false) {
  return (node.data.inputs || ["ir"]).flatMap((id, index) => {
    const connected = edges.some((edge) => edge.target === node.id && edge.targetHandle === id);
    const ir = (connected ? pullInput(nodes, edges, node, id) : detached && id === "ir" ? node.data.ir : null) as IRObject | null;
    if (!ir) return [];
    return [{ id, name: node.data.pageNames?.[id] || `Страница ${index + 1}`, ir }];
  });
}
