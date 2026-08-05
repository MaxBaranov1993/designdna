import type { ReactFlowInstance } from "@xyflow/react";
import { deepClone } from "./dataflow";
import { useFlowStore } from "./store";
import type { FlowEdge, NodeType } from "./types";

/* Шим window.GraphDev — зеркало nodes.js:1270-1304. Требуется Playwright-тестам:
 * те же сигнатуры, id принимаются как Number, state()/node() отдают legacy-форму. */
export interface GraphDevApi {
  add: (type: NodeType, x?: number, y?: number) => {
    id: number;
    type: NodeType;
    x: number;
    y: number;
    data: unknown;
  };
  connect: (fromId: number, fromPort: string, toId: number, toPort: string) => boolean;
  setIR: (nodeId: number, ir: unknown) => boolean;
  setText: (nodeId: number, text: string) => boolean;
  run: (nodeId: number) => void;
  state: () => {
    nodes: { id: number; type: string; x: number; y: number }[];
    edges: { from: { node: number; port: string }; to: { node: number; port: string } }[];
  };
  node: (id: number) =>
    | { id: number; type: string; x: number; y: number; data: unknown }
    | undefined;
  fit: () => void;
}

declare global {
  interface Window {
    GraphDev?: GraphDevApi;
  }
}

let rfInstance: ReactFlowInstance | null = null;

export function setReactFlowInstance(instance: ReactFlowInstance | null) {
  rfInstance = instance;
}

function legacyEdges(edges: FlowEdge[]) {
  return edges.map((e) => ({
    from: { node: Number(e.source), port: e.sourceHandle ?? "" },
    to: { node: Number(e.target), port: e.targetHandle ?? "" },
  }));
}

export function installGraphDev() {
  if (window.GraphDev) return;
  window.GraphDev = {
    add: (type, x, y) => useFlowStore.getState().addNode(type, x ?? 100, y ?? 100),
    connect: (fromId, fromPort, toId, toPort) =>
      useFlowStore
        .getState()
        .connect(
          { node: Number(fromId), port: String(fromPort) },
          { node: Number(toId), port: String(toPort) },
        ),
    setIR: (nodeId, ir) => {
      const st = useFlowStore.getState();
      const n = st.nodes.find((x) => Number(x.id) === Number(nodeId));
      if (!n || n.type !== "edit") return false;
      st.setNodeData(Number(nodeId), { ir: deepClone(ir) });
      st.propagate(Number(nodeId));
      return true;
    },
    setText: (nodeId, text) => {
      const st = useFlowStore.getState();
      const n = st.nodes.find((x) => Number(x.id) === Number(nodeId));
      if (!n || n.type !== "prompt") return false;
      st.setNodeData(Number(nodeId), { text: String(text) });
      st.propagate(Number(nodeId));
      return true;
    },
    run: (nodeId) => {
      useFlowStore.getState().runNode(Number(nodeId));
    },
    state: () => {
      const st = useFlowStore.getState();
      return {
        nodes: st.nodes.map((n) => ({
          id: Number(n.id),
          type: n.type,
          x: n.position.x,
          y: n.position.y,
        })),
        edges: legacyEdges(st.edges),
      };
    },
    node: (id) => {
      const n = useFlowStore.getState().nodes.find((x) => Number(x.id) === Number(id));
      return n
        ? { id: Number(n.id), type: n.type, x: n.position.x, y: n.position.y, data: n.data }
        : undefined;
    },
    fit: () => {
      if (rfInstance) void rfInstance.fitView();
    },
  };
}
