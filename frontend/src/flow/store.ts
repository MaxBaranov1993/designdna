import { create } from "zustand";
import { applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import type { EdgeChange, NodeChange } from "@xyflow/react";

import { defaultData, portsOfNode } from "./ports";
import { deepClone, pullInput, reachable } from "./dataflow";
import {
  DEFAULT_VIEW,
  buildSavePayload,
  loadFromStorage,
  makeRfEdge,
  payloadToRf,
  scheduleSave,
} from "./serialize";
import { toast } from "./toast";
import type {
  AnyNodeData,
  FlowEdge,
  FlowNode,
  LegacyEdgeEndpoint,
  LegacyGraphPayload,
  LegacyView,
  MixNodeData,
  NodeType,
} from "./types";

/* Статусная строка ноды — runtime-поле, в сейв не попадает (как .n-status в legacy) */
export type NodeStatus = { text: string; kind?: "ok" | "err" };

export interface FlowStoreState {
  /* состояние графа в типах RF (id строковые); конвертация в legacy — в serialize.ts */
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
  statuses: Record<number, NodeStatus>;

  addNode: (
    type: NodeType,
    x: number,
    y: number,
  ) => { id: number; type: NodeType; x: number; y: number; data: AnyNodeData };
  moveNode: (id: number, x: number, y: number) => void;
  connect: (from: LegacyEdgeEndpoint, to: LegacyEdgeEndpoint) => boolean;
  deleteNode: (id: number) => void;
  deleteEdge: (edgeId: string) => void;
  setNodeData: (id: number, patch: Record<string, unknown>) => void;
  setStatus: (id: number, text: string, kind?: "ok" | "err") => void;
  propagate: (startId: number, visited?: Set<number>) => void;
  runNode: (id: number) => void;
  addMixInput: (id: number) => void;
  removeMixInput: (id: number, name: string) => void;
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<FlowEdge>[]) => void;
  loadGraph: (payload: LegacyGraphPayload) => void;
  clearGraph: () => void;
  setView: (v: LegacyView) => void;
}

/* Стартовое состояние — из сейва designai-flow-v1 (битый сейв → пустой граф) */
const saved = loadFromStorage();
const initial = saved
  ? payloadToRf(saved)
  : { nodes: [] as FlowNode[], edges: [] as FlowEdge[], view: { ...DEFAULT_VIEW }, nextId: 1 };

export const useFlowStore = create<FlowStoreState>()((set, get) => ({
  ...initial,
  statuses: {},

  /* Зеркало addNode (nodes.js:256-264): id из nextId, координаты Math.round */
  addNode: (type, x, y) => {
    const id = get().nextId;
    const rx = Math.round(x);
    const ry = Math.round(y);
    const node = {
      id: String(id),
      type,
      position: { x: rx, y: ry },
      data: defaultData(type),
    } as FlowNode;
    set({ nodes: [...get().nodes, node], nextId: id + 1 });
    return { id, type, x: rx, y: ry, data: node.data };
  },

  /* Позиция ноды в мировых px (legacy Math.round на dragend, nodes.js:336-337) */
  moveNode: (id, x, y) => {
    const sid = String(id);
    set({
      nodes: get().nodes.map((n) =>
        n.id === sid ? { ...n, position: { x: Math.round(x), y: Math.round(y) } } : n,
      ),
    });
  },

  /* Правила проводов — зеркало connect() (nodes.js:1049-1070), см. FLOW-MIGRATION.md §3.2 */
  connect: (from, to) => {
    const state = get();
    const fromNode = Number(from.node);
    const toNode = Number(to.node);
    const src = state.nodes.find((n) => Number(n.id) === fromNode);
    const dst = state.nodes.find((n) => Number(n.id) === toNode);
    // правило 1: ноды существуют и это разные ноды (самосоединение молча отклоняется)
    if (!src || !dst || src.id === dst.id) return false;
    const outP = portsOfNode(src).out.find((p) => p.name === from.port);
    const inP = portsOfNode(dst).in.find((p) => p.name === to.port);
    // правило 2: оба порта объявлены
    if (!outP || !inP) return false;
    // правило 3: совпадение kind
    if (outP.kind !== inP.kind) {
      toast(`Несовместимые порты: ${outP.kind} → ${inP.kind}`, "error");
      return false;
    }
    // правило 4: проверка циклов — DFS, путь to -> from уже существует?
    if (reachable(toNode, fromNode, state.edges)) {
      toast("Нельзя: соединение создаёт цикл", "error");
      return false;
    }
    // правило 5: один провод на вход — существующее ребро в тот же вход заменяется
    const sidTarget = String(toNode);
    const nextEdges = [
      ...state.edges.filter((e) => !(e.target === sidTarget && e.targetHandle === to.port)),
      makeRfEdge(state.nodes, { node: fromNode, port: from.port }, { node: toNode, port: to.port }),
    ];
    set({ edges: nextEdges });
    // зеркало nodes.js:1067: propagate от источника
    get().propagate(fromNode);
    return true;
  },

  /* Зеркало removeNode (nodes.js:298-311): вместе с нодой снимаются её рёбра */
  deleteNode: (id) => {
    const sid = String(id);
    set((state) => {
      const statuses = { ...state.statuses };
      delete statuses[id];
      return {
        nodes: state.nodes.filter((n) => n.id !== sid),
        edges: state.edges.filter((e) => e.source !== sid && e.target !== sid),
        statuses,
      };
    });
  },

  deleteEdge: (edgeId) => {
    set({ edges: get().edges.filter((e) => e.id !== edgeId) });
  },

  /* Точечное обновление data ноды (аналог записи n.data.* в legacy + save()) */
  setNodeData: (id, patch) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === sid ? (({ ...n, data: { ...n.data, ...patch } }) as FlowNode) : n,
      ),
    }));
  },

  setStatus: (id, text, kind) => {
    set((state) => ({ statuses: { ...state.statuses, [id]: { text, kind } } }));
  },

  /* Зеркало propagate (nodes.js:943-968): edit/reference получают КЛОН IR,
   * mix помечается stale; через generator/mix поток не идёт (run-based).
   * Защита от повторов — visited (nodes.js:944-946). */
  propagate: (startId, visited = new Set<number>()) => {
    if (visited.has(startId)) return;
    visited.add(startId);
    const { nodes, edges } = get();
    for (const e of edges.filter((ed) => Number(ed.source) === startId)) {
      const consId = Number(e.target);
      const cons = nodes.find((n) => Number(n.id) === consId);
      if (!cons) continue;
      if (cons.type === "edit") {
        const ir = pullInput(nodes, edges, cons, "ir");
        if (ir) {
          get().setNodeData(consId, { ir: deepClone(ir) });
          get().propagate(consId, visited);
        }
      } else if (cons.type === "reference") {
        const ir = pullInput(nodes, edges, cons, "ir");
        if (ir) {
          get().setNodeData(consId, { ir: deepClone(ir) });
          get().setStatus(consId, "IR получен — можно разбить на компоненты", "ok");
          get().propagate(consId, visited);
        }
      } else if (cons.type === "mix") {
        get().setStatus(consId, "Входы обновлены — нажмите «Смешать»");
      }
    }
  },

  /* B1: run-based ноды — заглушки; LLM-вызовы подключаются в Фазе B2 */
  runNode: (id) => {
    const n = get().nodes.find((x) => Number(x.id) === id);
    if (!n) return;
    if (n.type !== "generator" && n.type !== "mix" && n.type !== "clone" && n.type !== "reproduce")
      return;
    get().setStatus(id, "Фаза B1: run-операции будут подключены в Фазе B2");
  },

  /* «+ вход» у mix: максимум 4, имя — первое свободное из a..d, вес 50 (nodes.js:403-412) */
  addMixInput: (id) => {
    const sid = String(id);
    const n = get().nodes.find((x) => x.id === sid);
    if (!n || n.type !== "mix") return;
    const inputs = (n.data as MixNodeData).inputs;
    if (inputs.length >= 4) {
      toast("Максимум 4 входа", "error");
      return;
    }
    const name = ["a", "b", "c", "d"].find((c) => !inputs.includes(c));
    if (!name) return;
    set((state) => ({
      nodes: state.nodes.map((x) =>
        x.id === sid && x.type === "mix"
          ? ({
              ...x,
              data: {
                ...x.data,
                inputs: [...x.data.inputs, name],
                weights: { ...x.data.weights, [name]: 50 },
              },
            } as FlowNode)
          : x,
      ),
    }));
  },

  /* «✕» у входа mix: снять вход и его провода (nodes.js:800-808) */
  removeMixInput: (id, name) => {
    const sid = String(id);
    set((state) => {
      const nodes = state.nodes.map((x) => {
        if (x.id !== sid || x.type !== "mix") return x;
        const weights = { ...x.data.weights };
        delete weights[name];
        return {
          ...x,
          data: { ...x.data, inputs: x.data.inputs.filter((i) => i !== name), weights },
        } as FlowNode;
      });
      const edges = state.edges.filter((e) => !(e.target === sid && e.targetHandle === name));
      return { nodes, edges };
    });
  },

  onNodesChange: (changes) => {
    // удаление ноды ведём сами, чтобы гарантированно снять рёбра (аналог removeNode)
    for (const ch of changes) {
      if (ch.type === "remove") get().deleteNode(Number(ch.id));
    }
    const rest = changes.filter((ch) => ch.type !== "remove");
    if (!rest.length) return;
    set({ nodes: applyNodeChanges(rest, get().nodes) });
    // конец drag: округляем позицию (legacy Math.round, nodes.js:336-337)
    for (const ch of rest) {
      if (ch.type === "position" && ch.dragging === false && ch.position) {
        get().moveNode(Number(ch.id), ch.position.x, ch.position.y);
      }
    }
  },

  onEdgesChange: (changes) => {
    for (const ch of changes) {
      if (ch.type === "remove") get().deleteEdge(ch.id);
    }
    const rest = changes.filter((ch) => ch.type !== "remove");
    if (rest.length) set({ edges: applyEdgeChanges(rest, get().edges) });
  },

  /* Зеркало load() (nodes.js:1202-1219): полная замена графа из payload */
  loadGraph: (payload) => {
    set({ ...payloadToRf(payload), statuses: {} });
  },

  clearGraph: () => {
    get().loadGraph({ nodes: [], edges: [], view: { ...DEFAULT_VIEW }, nextId: 1 });
  },

  setView: (v) => {
    set({ view: v });
  },
}));

/* Автосейв: одна подписка на изменения nodes/edges/view/nextId с дебаунсом 300 мс
 * (зеркало save() nodes.js:1175-1176, FLOW-MIGRATION.md §5.3) */
useFlowStore.subscribe((state, prev) => {
  if (
    state.nodes === prev.nodes &&
    state.edges === prev.edges &&
    state.view === prev.view &&
    state.nextId === prev.nextId
  )
    return;
  scheduleSave(() => buildSavePayload(useFlowStore.getState()));
});
