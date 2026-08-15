import { create } from "zustand";
import { applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import type { EdgeChange, NodeChange } from "@xyflow/react";

import { api } from "./api";
import type {
  BlockParseResp,
  GenerateResp,
  MixResp,
  ReproduceResp,
  ReskinResp,
  QualityPassResp,
} from "./api";
import { NODE_DEFS, defaultData, portsOfNode } from "./ports";
import { deepClone, outValue, pullInput, reachable } from "./dataflow";
import { composeSourceInputs, sourceInputForPort } from "./sourceComposition";
import type { SourceInputBlock } from "./sourceComposition";
import {
  DEFAULT_VIEW,
  buildPagesProjectPayload,
  buildSavePayload,
  loadPagesProjectFromDb,
  loadPagesProjectFromStorage,
  loadFromStorage,
  makeRfEdge,
  payloadToRf,
  scheduleProjectSave,
  scheduleSave,
} from "./serialize";
import { toast } from "./toast";
import type {
  AnyNodeData,
  FlowPage,
  FlowEdge,
  FlowNode,
  GeneratorNodeData,
  IRObject,
  LegacyEdgeEndpoint,
  LegacyGraphPayload,
  LegacyView,
  MixNodeData,
  PageNodeData,
  NodeType,
  ReskinNodeData,
  SourceImportNodeData,
  DeriveNodeData,
  EditNodeData,
  QualityPassNodeData,
  PageBridgeNodeData,
  RecorderNodeData,
  InteractionLiveAction,
  MotionNodeData,
} from "./types";

/* Статусная строка ноды — runtime-поле, в сейв не попадает (как .n-status в legacy) */
export type NodeStatus = { text: string; kind?: "ok" | "err" };

export interface FlowStoreState {
  /* состояние графа в типах RF (id строковые); конвертация в legacy — в serialize.ts */
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
  pages: FlowPage[];
  activePageId: string;
  channels: Record<string, IRObject | null>;
  statuses: Record<number, NodeStatus>;
  /* run-based ноды в полёте запроса (спиннер на ноде); runtime-поле, в сейв не попадает */
  busy: Record<number, boolean>;

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
  setBusy: (id: number, v: boolean) => void;
  propagate: (startId: number, visited?: Set<number>) => void;
  runNode: (id: number) => void;
  runGenerator: (id: number) => Promise<void>;
  runMix: (id: number) => Promise<void>;
  runPage: (id: number) => void;
  refreshEdit: (id: number) => void;
  runSourceImport: (id: number) => Promise<void>;
  runStyleDna: (id: number) => Promise<void>;
  runDerive: (id: number) => Promise<void>;
  runReskin: (id: number) => Promise<void>;
  runQualityPass: (id: number) => Promise<void>;
  runRecorder: (id: number) => Promise<void>;
  runLiveRecorder: (id: number, actions: InteractionLiveAction[]) => Promise<boolean>;
  runMotion: (id: number) => Promise<void>;
  runPageBridge: (id: number) => void;
  sendToNode: (id: number, targetType: "edit" | "reference") => void;
  addMixInput: (id: number) => void;
  removeMixInput: (id: number, name: string) => void;
  addEditInput: (id: number) => void;
  removeEditInput: (id: number, name: string) => void;
  reorderEditInputs: (id: number, from: number, to: number) => void;
  addPageInput: (id: number) => void;
  removePageInput: (id: number, name: string) => void;
  reorderPageInputs: (id: number, from: number, to: number) => void;
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<FlowEdge>[]) => void;
  loadGraph: (payload: LegacyGraphPayload) => void;
  clearGraph: () => void;
  setView: (v: LegacyView) => void;
  createPage: (name?: string) => void;
  switchPage: (id: string) => void;
  renamePage: (id: string, name: string) => void;
  deletePage: (id: string) => void;
  loadPersistedProject: () => Promise<void>;
}

/* Стартовое состояние — из сейва designai-flow-v1 (битый сейв → пустой граф) */
const emptyGraph = { nodes: [] as FlowNode[], edges: [] as FlowEdge[], view: { ...DEFAULT_VIEW }, nextId: 1 };
const projectSaved = loadPagesProjectFromStorage();
const saved = projectSaved ? null : loadFromStorage();
const initialSingle = saved ? payloadToRf(saved) : emptyGraph;
const initialPages: FlowPage[] = projectSaved?.pages || [
  {
    id: "page-1",
    name: "Page 1",
    ...initialSingle,
  },
];
const initialActivePageId = projectSaved?.activePageId || initialPages[0].id;
const initialActiveGraph = initialPages.find((page) => page.id === initialActivePageId) || initialPages[0];
const initialChannels = projectSaved?.channels || {};

function pageId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `page-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function currentPageSnapshot(st: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
}): Pick<FlowPage, "nodes" | "edges" | "view" | "nextId"> {
  return {
    nodes: st.nodes,
    edges: st.edges,
    view: st.view,
    nextId: st.nextId,
  };
}

function withCurrentPageSaved(st: FlowStoreState): FlowPage[] {
  const snapshot = currentPageSnapshot(st);
  return st.pages.map((page) => (page.id === st.activePageId ? { ...page, ...snapshot } : page));
}

function hydratePageBridgeNodes(nodes: FlowNode[], channels: Record<string, IRObject | null>): FlowNode[] {
  return nodes.map((node) => {
    if (node.type !== "pagebridge" || node.data.mode !== "receive") return node;
    const ir = channels[node.data.channel] || null;
    return { ...node, data: { ...node.data, ir: ir ? deepClone(ir) : null } } as FlowNode;
  });
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function uniqueValues(values: unknown[], limit = 12): string[] {
  const out: string[] = [];
  for (const v of values) {
    const s = typeof v === "string" || typeof v === "number" ? String(v).trim() : "";
    if (s && !out.includes(s)) out.push(s);
    if (out.length >= limit) break;
  }
  return out;
}

function extractStyleDna(irRaw: unknown, tokensRaw: unknown): { tokens: Record<string, unknown>; summary: string } {
  const ir = asRecord(irRaw);
  const explicit = asRecord(tokensRaw) || asRecord(ir?.tokens);
  if (explicit) {
    return { tokens: deepClone(explicit), summary: summarizeStyleDna(explicit) };
  }
  const colors: unknown[] = [];
  const fonts: unknown[] = [];
  const radii: unknown[] = [];
  const spacing: unknown[] = [];
  const walk = (node: unknown) => {
    if (Array.isArray(node)) return node.forEach(walk);
    const r = asRecord(node);
    if (!r) return;
    const style = asRecord(r.style) || {};
    colors.push(style.color, style.background, style.borderColor);
    fonts.push(style.fontFamily);
    radii.push(style.borderRadius, asRecord(r.props)?.radius);
    const frame = asRecord(r.frame);
    spacing.push(frame?.x, frame?.y, frame?.w, frame?.h);
    walk(r.children);
  };
  walk(ir?.tree);
  const tokens: Record<string, unknown> = {
    color: { sampled: uniqueValues(colors) },
    font: { sampled: uniqueValues(fonts, 6) },
    radius: { sampled: uniqueValues(radii, 6) },
    spacing: { measured: uniqueValues(spacing, 10) },
  };
  return { tokens, summary: summarizeStyleDna(tokens) };
}

function summarizeStyleDna(tokens: Record<string, unknown>): string {
  const color = asRecord(tokens.color);
  const font = asRecord(tokens.font);
  const radius = asRecord(tokens.radius);
  const spacing = asRecord(tokens.spacing);
  const parts = [
    color ? `colors=${JSON.stringify(color).slice(0, 180)}` : "",
    font ? `fonts=${JSON.stringify(font).slice(0, 140)}` : "",
    radius ? `radius=${JSON.stringify(radius).slice(0, 100)}` : "",
    spacing ? `spacing=${JSON.stringify(spacing).slice(0, 120)}` : "",
  ].filter(Boolean);
  return parts.join("\n");
}

let localDirtySinceInit = false;

export const useFlowStore = create<FlowStoreState>()((set, get) => ({
  nodes: hydratePageBridgeNodes(initialActiveGraph.nodes, initialChannels),
  edges: initialActiveGraph.edges,
  view: initialActiveGraph.view,
  nextId: initialActiveGraph.nextId,
  pages: initialPages,
  activePageId: initialActivePageId,
  channels: initialChannels,
  statuses: {},
  busy: {},

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

  /* Правила проводов — зеркало connect() (nodes.js:1049-1070), см. docs/ARCHITECTURE.md */
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
      const busy = { ...state.busy };
      delete busy[id];
      return {
        nodes: state.nodes.filter((n) => n.id !== sid),
        edges: state.edges.filter((e) => e.source !== sid && e.target !== sid),
        statuses,
        busy,
      };
    });
  },

  deleteEdge: (edgeId) => {
    const removed = get().edges.find((edge) => edge.id === edgeId);
    set({ edges: get().edges.filter((edge) => edge.id !== edgeId) });
    if (removed) {
      const target = get().nodes.find((node) => node.id === removed.target);
      if (target?.type === "edit") {
        get().refreshEdit(Number(target.id));
        get().propagate(Number(target.id));
      }
    }
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

  setBusy: (id, v) => {
    set((state) => ({ busy: { ...state.busy, [id]: v } }));
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
        get().refreshEdit(consId);
        get().propagate(consId, visited);
      } else if (cons.type === "reference") {
        const ir = pullInput(nodes, edges, cons, "ir");
        if (ir) {
          get().setNodeData(consId, { ir: deepClone(ir) });
          get().setStatus(consId, "IR получен — можно разбить на компоненты", "ok");
          get().propagate(consId, visited);
        }
      } else if (cons.type === "mix") {
        get().setStatus(consId, "Входы обновлены — нажмите «Смешать»");
      } else if (cons.type === "styledna") {
        const ir = pullInput(nodes, edges, cons, "ir");
        const tokensRaw = pullInput(nodes, edges, cons, "tokens");
        if (ir || tokensRaw) {
          const dna = extractStyleDna(ir, tokensRaw);
          get().setNodeData(consId, { tokens: dna.tokens, summary: dna.summary });
          get().setStatus(consId, "Style DNA обновлён", "ok");
          get().propagate(consId, visited);
        }
      } else if (cons.type === "derive") {
        get().setStatus(consId, "Входы обновлены — нажмите Derive");
      } else if (cons.type === "qualitypass") {
        const ir = pullInput(nodes, edges, cons, "ir");
        if (ir) {
          get().setNodeData(consId, { ir: deepClone(ir), result: null });
          get().setStatus(consId, "IR получен — запустите Quality Pass");
        }
      } else if (cons.type === "recorder") {
        const ir = pullInput(nodes, edges, cons, "ir");
        if (ir) {
          get().setNodeData(consId, { ir: deepClone(ir), interaction: null, draftEvents: [], draftScenes: [{ id: "scene-0", viewport: "desktop", patch: [] }] });
          get().setStatus(consId, "Design IR ready for interaction recording", "ok");
        }
      } else if (cons.type === "motion") {
        const designIr = pullInput(nodes, edges, cons, "ir") as IRObject | null;
        const interaction = pullInput(nodes, edges, cons, "interaction") as IRObject | null;
        get().setNodeData(consId, {
          ir: designIr ? deepClone(designIr) : null,
          interaction: interaction ? deepClone(interaction) : null,
          motion: null,
          sceneIrs: [],
        });
        get().setStatus(consId, designIr && interaction ? "Motion inputs ready" : "Connect Design IR and Interaction IR");
      } else if (cons.type === "pagebridge") {
        get().runPageBridge(consId);
        get().propagate(consId, visited);
      }
    }
  },

  /* Диспетчер run-based нод (кнопки ▶ и GraphDev.run) */
  runNode: (id) => {
    const n = get().nodes.find((x) => Number(x.id) === id);
    if (!n) return;
    if (n.type === "generator") void get().runGenerator(id);
    else if (n.type === "mix") void get().runMix(id);
    else if (n.type === "page") get().runPage(id);
    else if (n.type === "sourceimport") void get().runSourceImport(id);
    else if (n.type === "styledna") void get().runStyleDna(id);
    else if (n.type === "derive") void get().runDerive(id);
    else if (n.type === "reskin") void get().runReskin(id);
    else if (n.type === "qualitypass") void get().runQualityPass(id);
    else if (n.type === "recorder") void get().runRecorder(id);
    else if (n.type === "motion") void get().runMotion(id);
    else if (n.type === "pagebridge") get().runPageBridge(id);
  },

  /* Зеркало runGenerator (nodes.js:498-518): бриф тянем из входа prompt (pull-based)
   * с fallback на ownPrompt, styleHint — из входа style, tokens — из входа style DNA; payload {brief, count,
   * provider, styleHint, tokens?}. Результат — variants + active=0,
   * propagate проталкивает clones[active] в edit/reference ниже по графу. */
  runGenerator: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "generator" || st.busy[id]) return;
    const data = n.data as GeneratorNodeData;
    const brief = String(
      pullInput(st.nodes, st.edges, n, "prompt") || data.ownPrompt || "",
    ).trim();
    if (!brief) {
      get().setStatus(id, "Нет промта: подключите провод или заполните поле", "err");
      return;
    }
    const styleRaw = pullInput(st.nodes, st.edges, n, "style");
    const styleHint = styleRaw ? String(styleRaw) : undefined;
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    const tokens = tokensRaw && typeof tokensRaw === "object" ? (tokensRaw as Record<string, unknown>) : undefined;
    get().setStatus(id, `Генерация (OpenRouter, ${data.count})… 20–120 сек`);
    get().setBusy(id, true);
    try {
      const res = await api<GenerateResp>("/api/generate", {
        brief,
        count: data.count,
        provider: "openrouter",
        styleHint,
        tokens,
        preset: data.preset || undefined,
      });
      const variants = Array.isArray(res.variants) ? res.variants : [];
      get().setNodeData(id, { variants, active: 0 });
      const errNote = res.errors && res.errors.length ? `, ошибок: ${res.errors.length}` : "";
      const fixedCount = (res.qa || []).reduce((s, q) => s + (q.fixed || 0), 0);
      const qaNote = fixedCount ? `, автофиксов QA: ${fixedCount}` : "";
      const designNote = res.design?.label ? `, тип: ${res.design.label}` : "";
      get().setStatus(id, `Готово: вариантов ${variants.length}${errNote}${qaNote}${designNote}`, "ok");
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Генератор: " + msg, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  /* Зеркало runMix (nodes.js:815-836): IR тянем из подключённых входов (pull),
   * веса нормируются 0..1; payload {irs, weights}. */
  runMix: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "mix" || st.busy[id]) return;
    const data = n.data as MixNodeData;
    const irs: unknown[] = [];
    const weights: number[] = [];
    const labels: string[] = [];
    for (const name of data.inputs) {
      const ir = pullInput(st.nodes, st.edges, n, name);
      if (ir) {
        irs.push(ir);
        weights.push((data.weights[name] ?? 50) / 100);
        labels.push(`${name}:${data.weights[name] ?? 50}%`);
      }
    }
    if (irs.length < 2) {
      get().setStatus(id, "Нужно минимум 2 подключённых IR-входа", "err");
      return;
    }
    get().setStatus(id, "Смешиваю…");
    get().setBusy(id, true);
    try {
      const res = await api<MixResp>("/api/mix", { irs, weights });
      get().setNodeData(id, { ir: res.ir || null });
      get().setStatus(id, "Готово: " + labels.join(" + "), "ok");
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Микс: " + msg, "error");
    } finally {
      get().setBusy(id, false);
    }
  },


  /* Page: сборка страницы из подключённых блоков — детерминированно, без LLM.
   * Порядок inputs = порядок секций; tokens — style DNA с провода > первый блок. */
  refreshEdit: (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "edit") return;
    const data = n.data as EditNodeData;
    const inputs = data.inputs || ["ir"];
    const blocks = inputs
      .map((name) => sourceInputForPort(st.nodes, st.edges, n, name))
      .filter((block): block is SourceInputBlock => block !== null);
    if (!blocks.length) {
      get().setNodeData(id, { ir: null, sourceRegistry: {}, nodeSources: {}, layoutEvidence: [] });
      get().setStatus(id, "Подключите хотя бы один компонент", "err");
      return;
    }
    const result = composeSourceInputs(blocks, null, "desktop", blocks.length > 1);
    get().setNodeData(id, result);
    get().setStatus(id, `${blocks.length} компонент(а) · ${Object.keys(result.sourceRegistry).length} источн.`, "ok");
  },

  runPage: (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "page") return;
    const data = n.data as PageNodeData;
    const blocks = data.inputs
      .map((name) => sourceInputForPort(st.nodes, st.edges, n, name))
      .filter((block): block is SourceInputBlock => block !== null);
    if (!blocks.length) {
      get().setStatus(id, "Подключите хотя бы один IR-вход", "err");
      return;
    }
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    const tokens = tokensRaw && typeof tokensRaw === "object" ? (tokensRaw as IRObject) : null;
    const result = composeSourceInputs(blocks, tokens, data.activeViewport || "desktop", true);
    get().setNodeData(id, result);
    get().setStatus(id, `Собрана: блоков ${blocks.length}`, "ok");
    get().propagate(id);
  },
  runSourceImport: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "sourceimport" || st.busy[id]) return;
    const data = n.data as SourceImportNodeData;
    get().setBusy(id, true);
    try {
      if (data.mode === "screenshot") {
        if (!data.image) {
          get().setStatus(id, "Загрузите скриншот элемента", "err");
          return;
        }
        get().setStatus(id, "Скриншот → pixel capture через OpenRouter…");
        const res = await api<ReproduceResp>("/api/reproduce", {
          image: data.image,
          url: "",
          provider: "openrouter",
        });
        const ir = res.ir || null;
        const dna = extractStyleDna(ir, null);
        const blocks = ir
          ? [{
              name: "capture",
              selector: "screenshot",
              ir,
              source: "vision" as const,
              parserContract: res.parserContract,
              lit: true,
            }]
          : [];
        get().setNodeData(id, { blocks, tokens: dna.tokens });
        get().setStatus(id, ir ? "Готово: capture + Style DNA" : "Не удалось получить IR из скриншота", ir ? "ok" : "err");
      } else {
        const url = (data.url || "").trim();
        if (!url) {
          get().setStatus(id, "Введите URL сайта", "err");
          return;
        }
        if (!data.mine) {
          get().setStatus(id, "Отметьте «это мой сайт/есть право»", "err");
          return;
        }
        get().setStatus(id, `Импортирую ${url.slice(0, 30)}…`);
        const res = await api<BlockParseResp>("/api/block-parse", {
          url,
          viewports: [
            { name: "desktop", width: 1440, height: 900 },
            { name: "tablet", width: 768, height: 1024 },
            { name: "mobile", width: 390, height: 844 },
          ],
        });
        const litBefore = new Set(data.blocks.filter((b) => b.lit).map((b) => b.name));
        const blocks = (res.blocks || []).map((b) => ({ ...b, lit: litBefore.has(b.name) }));
        get().setNodeData(id, { blocks, tokens: res.tokens || null });
        const sid = String(id);
        const alive = new Set<string>(["tokens", ...blocks.map((b) => b.name)]);
        set((state) => ({
          edges: state.edges.filter((e) => e.source !== sid || alive.has(e.sourceHandle ?? "")),
        }));
        const errCount = blocks.filter((b) => b.error).length;
        get().setStatus(id, `${blocks.length} блоков (${errCount} ошибок) · Source Import`, errCount ? "err" : "ok");
      }
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Source Import: " + msg, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  runStyleDna: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "styledna") return;
    const ir = pullInput(st.nodes, st.edges, n, "ir");
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    if (!ir && !tokensRaw) {
      get().setStatus(id, "Подключите IR или tokens", "err");
      return;
    }
    const dna = extractStyleDna(ir, tokensRaw);
    get().setNodeData(id, { tokens: dna.tokens, summary: dna.summary });
    get().setStatus(id, "Style DNA собран", "ok");
    get().propagate(id);
  },

  runDerive: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "derive" || st.busy[id]) return;
    const data = n.data as DeriveNodeData;
    const prompt = String(pullInput(st.nodes, st.edges, n, "prompt") || data.prompt || "").trim();
    const reference = pullInput(st.nodes, st.edges, n, "reference");
    const tokens = pullInput(st.nodes, st.edges, n, "tokens");
    if (!prompt) {
      get().setStatus(id, "Опишите, какой компонент получить", "err");
      return;
    }
    const styleHint = [
      tokens ? "Style DNA:\n" + JSON.stringify(tokens) : "",
      reference ? "Reference IR:\n" + JSON.stringify(reference).slice(0, 9000) : "",
    ].filter(Boolean).join("\n\n");
    get().setStatus(id, `Derive: ${data.count} вариант(а) через OpenRouter…`);
    get().setBusy(id, true);
    try {
      const res = await api<GenerateResp>("/api/generate", {
        brief: prompt,
        count: data.count,
        provider: "openrouter",
        styleHint: styleHint || undefined,
        tokens: tokens && typeof tokens === "object" ? tokens : undefined,
      });
      const variants = Array.isArray(res.variants) ? res.variants : [];
      get().setNodeData(id, { variants, active: 0 });
      get().setStatus(id, `Готово: вариантов ${variants.length}`, "ok");
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Derive: " + msg, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  /* Reskin: входы ir/tokens тянутся
   * проводами (pull-модель); payload {ir, prompt, tokens?, mask}; пустая маска
   * не запускается (бэкенд вернул бы IR без изменений). Ответ: {ir, log} —
   * log (журнал merge-back) показывается свёрнутым блоком в ноде. */
  runReskin: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "reskin" || st.busy[id]) return;
    const data = n.data as ReskinNodeData;
    if (!Object.values(data.mask).some(Boolean)) {
      get().setStatus(id, "Пустая маска: отметьте, что разрешено менять", "err");
      return;
    }
    const ir = pullInput(st.nodes, st.edges, n, "ir") as IRObject | null;
    if (!ir) {
      get().setStatus(id, "Подключите IR ко входу (например, из Source Import)", "err");
      return;
    }
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    get().setStatus(id, "Рестайл: LLM + merge-back… 20–120 сек");
    get().setBusy(id, true);
    try {
      const payload: Record<string, unknown> = {
        ir,
        prompt: data.prompt || "",
        mask: data.mask,
      };
      if (tokensRaw && typeof tokensRaw === "object") payload.tokens = tokensRaw;
      const res = await api<ReskinResp>("/api/reskin", payload);
      const log = Array.isArray(res.log) ? res.log : [];
      get().setNodeData(id, { ir: res.ir || null, log });
      get().setStatus(id, `Готово · журнал merge-back: ${log.length}`, "ok");
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Reskin: " + msg, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  /* Quality Pass: независимый judge оценивает IR, затем при необходимости
   * запускает адресный repair и повторную оценку. Все LLM-вызовы внутри
   * endpoint идут только через OpenRouter; UI получает объяснимый scorecard. */
  runQualityPass: async (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "qualitypass" || st.busy[id]) return;
    const data = n.data as QualityPassNodeData;
    const ir = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!ir) {
      get().setStatus(id, "Подключите IR ко входу", "err");
      return;
    }
    get().setStatus(id, "Quality Pass: judge + проверка правил… 30–120 сек");
    get().setBusy(id, true);
    try {
      const res = await api<QualityPassResp>("/api/quality-pass", {
        ir,
        brief: data.brief,
        min_score: data.minScore,
        repair: data.repair,
        rejudge: data.repair,
      });
      const score = Number(res.scorecard?.score ?? 0);
      const passed = Boolean(res.passed);
      const repairNote = res.repair?.applied ? " · repair применён" : "";
      get().setNodeData(id, { ir: res.ir || ir, result: res });
      get().setStatus(id, `${passed ? "Готово" : "Нужна проверка"}: ${score}/100${repairNote}`, passed ? "ok" : "err");
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Quality Pass: " + msg, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  runRecorder: async (id) => {
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "recorder" || st.busy[id]) return;
    const data = n.data as RecorderNodeData;
    const baseIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!baseIr) {
      get().setStatus(id, "Connect Design IR before recording", "err");
      return;
    }
    get().setBusy(id, true);
    get().setStatus(id, "Sanitizing Interaction IR...");
    try {
      const response = await api<{ interaction?: IRObject }>("/api/interaction/build", {
        base_ir: baseIr,
        source: { kind: "design-ir", url: "" },
        scenes: data.draftScenes,
        events: data.draftEvents,
        variables: {},
      });
      const interaction = response.interaction || null;
      get().setNodeData(id, { ir: deepClone(baseIr), interaction, recording: false });
      const report = interaction?.privacyReport as Record<string, unknown> | undefined;
      get().setStatus(id, `Interaction IR ready · ${data.draftEvents.length} events · ${Number(report?.sanitizedCount || 0)} redactions`, "ok");
      get().propagate(id);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      get().setStatus(id, "Recorder: " + message, "err");
      toast("Recorder: " + message, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  runLiveRecorder: async (id, actions) => {
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "recorder" || st.busy[id]) return false;
    const data = n.data as RecorderNodeData;
    const baseIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!baseIr || !data.liveUrl.trim() || !data.mine || !actions.length) {
      get().setStatus(id, "Live capture needs Design IR, URL, ownership confirmation and actions", "err");
      return false;
    }
    get().setBusy(id, true);
    get().setStatus(id, `Replaying ${actions.length} actions in Chromium...`);
    try {
      const response = await api<{ interaction?: IRObject }>("/api/interaction/capture", {
        base_ir: baseIr,
        url: data.liveUrl.trim(),
        mine: data.mine,
        viewport: data.liveViewport || "desktop",
        actions,
      });
      const interaction = response.interaction || null;
      get().setNodeData(id, { ir: deepClone(baseIr), interaction, recording: false });
      const report = interaction?.privacyReport as Record<string, unknown> | undefined;
      get().setStatus(id, `Live Interaction IR ready · ${actions.length} actions · ${Number(report?.sanitizedCount || 0)} redactions`, "ok");
      get().propagate(id);
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      get().setStatus(id, "Live capture: " + message, "err");
      toast("Live capture: " + message, "error");
      return false;
    } finally {
      get().setBusy(id, false);
    }
  },

  runMotion: async (id) => {
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "motion" || st.busy[id]) return;
    const data = n.data as MotionNodeData;
    const designIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    const interaction = (pullInput(st.nodes, st.edges, n, "interaction") || data.interaction) as IRObject | null;
    if (!designIr || !interaction) {
      get().setStatus(id, "Connect Design IR and Interaction IR", "err");
      return;
    }
    get().setBusy(id, true);
    get().setStatus(id, "Building editable motion timeline...");
    try {
      const response = await api<{ motion?: IRObject; sceneIrs?: MotionNodeData["sceneIrs"] }>("/api/motion/build", {
        base_ir: designIr,
        interaction,
        composition: data.composition,
        scene_settings: data.sceneSettings,
        render_settings: data.renderSettings || { format: "mp4", quality: "high" },
      });
      const motion = response.motion || null;
      const sceneIrs = response.sceneIrs || [];
      const scenes = Array.isArray(motion?.scenes) ? motion.scenes : [];
      get().setNodeData(id, {
        ir: deepClone(designIr), interaction: deepClone(interaction), motion, sceneIrs, renderJob: null,
        selectedScene: Math.min(data.selectedScene || 0, Math.max(0, scenes.length - 1)),
      });
      const composition = motion?.composition as Record<string, unknown> | undefined;
      get().setStatus(id, `Motion IR ready · ${scenes.length} scenes · ${(Number(composition?.duration || 0) / 1000).toFixed(1)}s`, "ok");
      get().propagate(id);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      get().setStatus(id, "Motion: " + message, "err");
      toast("Motion: " + message, "error");
    } finally {
      get().setBusy(id, false);
    }
  },

  runPageBridge: (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "pagebridge") return;
    const data = n.data as PageBridgeNodeData;
    const channel = (data.channel || "shared-component").trim() || "shared-component";
    if (data.mode === "send") {
      const ir = pullInput(st.nodes, st.edges, n, "ir") as IRObject | null;
      if (!ir) {
        get().setStatus(id, "Подключите компонент к входу", "err");
        return;
      }
      const cloned = deepClone(ir);
      set((state) => ({
        channels: { ...state.channels, [channel]: cloned },
        nodes: state.nodes.map((node) =>
          node.id === String(id)
            ? ({ ...node, data: { ...node.data, channel, ir: cloned } } as FlowNode)
            : node,
        ),
      }));
      get().setStatus(id, `Передано в канал: ${channel}`, "ok");
      return;
    }
    const ir = st.channels[channel] || null;
    if (!ir) {
      get().setNodeData(id, { channel, ir: null });
      get().setStatus(id, `Канал пустой: ${channel}`, "err");
      return;
    }
    get().setNodeData(id, { channel, ir: deepClone(ir) });
    get().setStatus(id, `Получено из канала: ${channel}`, "ok");
    get().propagate(id);
  },

  /* Зеркало sendToNode (nodes.js:522-545): создать ноду target справа от источника,
   * положить клон IR и соединить проводом ir->ir. */
  sendToNode: (id, targetType) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n) return;
    const ir = outValue(n) as IRObject | null;
    if (!ir) {
      toast("Сначала запустите ноду и получите IR на выходе", "error");
      return;
    }
    const def = NODE_DEFS[n.type as NodeType];
    const target = get().addNode(targetType, n.position.x + (def ? def.w : 270) + 60, n.position.y);
    get().setNodeData(target.id, { ir: deepClone(ir) });
    if (targetType === "reference") get().setStatus(target.id, "IR получен от генератора", "ok");
    get().connect({ node: id, port: "ir" }, { node: target.id, port: targetType === "edit" ? "a" : "ir" });
    toast(`→ ${NODE_DEFS[targetType].title}`, "ok");
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

  /* Edit принимает компоненты напрямую: порядок входов становится порядком секций. */
  addEditInput: (id) => {
    const sid = String(id);
    const n = get().nodes.find((x) => x.id === sid);
    if (!n || n.type !== "edit") return;
    const inputs = (n.data as EditNodeData).inputs || ["ir"];
    const candidates = "abcdefghijkl".split("");
    if (inputs.length >= candidates.length) {
      toast("Максимум 12 компонентов", "error");
      return;
    }
    const name = candidates.find((candidate) => !inputs.includes(candidate));
    if (!name) return;
    set((state) => ({
      nodes: state.nodes.map((item) => item.id === sid && item.type === "edit"
        ? ({ ...item, data: { ...item.data, inputs: [...inputs, name] } } as FlowNode)
        : item),
    }));
  },

  removeEditInput: (id, name) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((item) => {
        if (item.id !== sid || item.type !== "edit") return item;
        const inputs = (item.data.inputs || ["ir"]).filter((input) => input !== name);
        return { ...item, data: { ...item.data, inputs } } as FlowNode;
      }),
      edges: state.edges.filter((edge) => !(edge.target === sid && edge.targetHandle === name)),
    }));
    get().refreshEdit(id);
    get().propagate(id);
  },

  reorderEditInputs: (id, from, to) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((item) => {
        if (item.id !== sid || item.type !== "edit") return item;
        const inputs = [...(item.data.inputs || ["ir"] )];
        if (from < 0 || from >= inputs.length || to < 0 || to >= inputs.length || from === to) return item;
        const [moved] = inputs.splice(from, 1);
        inputs.splice(to, 0, moved);
        return { ...item, data: { ...item.data, inputs } } as FlowNode;
      }),
    }));
    get().refreshEdit(id);
    get().propagate(id);
  },


  /* «+ вход» у Page: до 8 блоков, имена a..h (паттерн addMixInput) */
  addPageInput: (id) => {
    const sid = String(id);
    const n = get().nodes.find((x) => x.id === sid);
    if (!n || n.type !== "page") return;
    const inputs = (n.data as PageNodeData).inputs;
    if (inputs.length >= 8) {
      toast("Максимум 8 блоков", "error");
      return;
    }
    const name = ["a", "b", "c", "d", "e", "f", "g", "h"].find((c) => !inputs.includes(c));
    if (!name) return;
    set((state) => ({
      nodes: state.nodes.map((x) =>
        x.id === sid && x.type === "page"
          ? ({ ...x, data: { ...x.data, inputs: [...x.data.inputs, name] } } as FlowNode)
          : x,
      ),
    }));
  },

  /* «✕» у входа Page: снять вход и его провода (паттерн removeMixInput) */
  removePageInput: (id, name) => {
    const sid = String(id);
    set((state) => {
      const nodes = state.nodes.map((x) => {
        if (x.id !== sid || x.type !== "page") return x;
        return {
          ...x,
          data: { ...x.data, inputs: x.data.inputs.filter((i) => i !== name) },
        } as FlowNode;
      });
      const edges = state.edges.filter((e) => !(e.target === sid && e.targetHandle === name));
      return { nodes, edges };
    });
  },

  /* drag-порядок блоков Page = порядок секций на странице */
  reorderPageInputs: (id, from, to) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((x) => {
        if (x.id !== sid || x.type !== "page") return x;
        const inputs = [...x.data.inputs];
        if (from < 0 || from >= inputs.length || to < 0 || to >= inputs.length || from === to) return x;
        const [moved] = inputs.splice(from, 1);
        inputs.splice(to, 0, moved);
        return { ...x, data: { ...x.data, inputs } } as FlowNode;
      }),
    }));
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
    const graph = payloadToRf(payload);
    set((state) => ({
      ...graph,
      pages: state.pages.map((page) =>
        page.id === state.activePageId ? { ...page, ...graph } : page,
      ),
      statuses: {},
    }));
  },

  clearGraph: () => {
    get().loadGraph({ nodes: [], edges: [], view: { ...DEFAULT_VIEW }, nextId: 1 });
  },

  setView: (v) => {
    set({ view: v });
  },

  createPage: (name) => {
    const st = get();
    const id = pageId();
    const nextIndex = st.pages.length + 1;
    const page: FlowPage = {
      id,
      name: (name || `Page ${nextIndex}`).trim() || `Page ${nextIndex}`,
      nodes: [],
      edges: [],
      view: { ...DEFAULT_VIEW },
      nextId: 1,
    };
    set((state) => ({
      pages: [...withCurrentPageSaved(state), page],
      activePageId: id,
      nodes: page.nodes,
      edges: page.edges,
      view: page.view,
      nextId: page.nextId,
      statuses: {},
      busy: {},
    }));
  },

  switchPage: (id) => {
    const st = get();
    if (id === st.activePageId) return;
    const pages = withCurrentPageSaved(st);
    const page = pages.find((p) => p.id === id);
    if (!page) return;
    set({
      pages,
      activePageId: id,
      nodes: hydratePageBridgeNodes(page.nodes, st.channels),
      edges: page.edges,
      view: page.view,
      nextId: page.nextId,
      statuses: {},
      busy: {},
    });
  },

  renamePage: (id, name) => {
    const nextName = name.trim();
    if (!nextName) return;
    set((state) => ({
      pages: withCurrentPageSaved(state).map((page) =>
        page.id === id ? { ...page, name: nextName } : page,
      ),
    }));
  },

  deletePage: (id) => {
    const st = get();
    if (st.pages.length <= 1) return;
    const pages = withCurrentPageSaved(st).filter((page) => page.id !== id);
    const next = pages.find((page) => page.id === st.activePageId) || pages[0];
    set({
      pages,
      activePageId: next.id,
      nodes: hydratePageBridgeNodes(next.nodes, st.channels),
      edges: next.edges,
      view: next.view,
      nextId: next.nextId,
      statuses: {},
      busy: {},
    });
  },

  loadPersistedProject: async () => {
    const project = await loadPagesProjectFromDb();
    if (!project) return;
    // Гонка гидратации: пока шёл fetch, локальный граф мог измениться (пользователь
    // или GraphDev.add в тестах уже добавил ноды) — применять загруженный проект
    // поверх нельзя, он затёр бы локальные правки пустым/устаревшим состоянием.
    if (localDirtySinceInit) return;
    const current = get();
    const dbNodeCount = project.pages.reduce((sum, page) => sum + page.nodes.length, 0);
    if (dbNodeCount === 0 && (current.nodes.length > 0 || current.edges.length > 0)) return;
    const activePage = project.pages.find((page) => page.id === project.activePageId) || project.pages[0];
    if (!activePage) return;
    set({
      pages: project.pages,
      activePageId: activePage.id,
      nodes: hydratePageBridgeNodes(activePage.nodes, project.channels),
      edges: activePage.edges,
      view: activePage.view,
      nextId: activePage.nextId,
      channels: project.channels,
      statuses: {},
      busy: {},
    });
  },
}));

/* Автосейв: одна подписка на изменения nodes/edges/view/nextId с дебаунсом 300 мс
 * (зеркало save() nodes.js:1175-1176) */
useFlowStore.subscribe((state, prev) => {
  if (
    state.nodes === prev.nodes &&
    state.edges === prev.edges &&
    state.view === prev.view &&
    state.nextId === prev.nextId &&
    state.pages === prev.pages &&
    state.activePageId === prev.activePageId &&
    state.channels === prev.channels
  )
    return;
  localDirtySinceInit = true;
  scheduleSave(() => buildSavePayload(useFlowStore.getState()));
  scheduleProjectSave(() => buildPagesProjectPayload(useFlowStore.getState()));
});
