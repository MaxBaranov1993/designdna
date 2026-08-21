import { createStore } from "zustand/vanilla";

import { api, extractStyleDna as extractStyleDnaApi } from "./api";
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
  FLOW_LS_KEY,
  buildPagesProjectPayload,
  compactLegacyLocalStorage,
  loadPagesProjectFromDb,
  loadPagesProjectFromStorage,
  loadFromStorage,
  makeRfEdge,
  payloadToRf,
  scheduleProjectSave,
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

function friendlyProviderError(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error);
  const detail = raw.replace(/^Error invoking remote method '[^']+':\s*Error:\s*/i, "").trim();
  if (/OpenAI API key|Kimi не подключён|нет подключённого AI-аккаунта|Agents\s*→\s*Connections/i.test(detail)) {
    return "AI-аккаунт не подключён. Откройте Agents → Connections.";
  }
  return detail || "AI не ответил. Повторите запуск.";
}

/* Статусная строка ноды — runtime-поле, в сейв не попадает (как .n-status в legacy) */
export type NodeStatus = { text: string; kind?: "ok" | "err" };

export type PersistedEditorDraft = {
  baseRevision: number;
  draftRevision: number;
  ir: IRObject;
};

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
  moveNodes: (updates: Array<{ id: number; x: number; y: number }>) => void;
  connect: (from: LegacyEdgeEndpoint, to: LegacyEdgeEndpoint) => boolean;
  deleteNode: (id: number) => void;
  deleteEdge: (edgeId: string) => void;
  setNodeData: (id: number, patch: Record<string, unknown>) => void;
  getNodeIrRevision: (id: number) => number;
  persistEditorDraft: (id: number, draft: PersistedEditorDraft) => void;
  clearEditorDraft: (id: number) => void;
  commitEditorDraft: (id: number, expectedRevision: number, ir: IRObject) => boolean;
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
  syncFromCanvas: (nodes: FlowNode[], edges: FlowEdge[]) => void;
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
compactLegacyLocalStorage();
const projectSaved = loadPagesProjectFromStorage();
if (projectSaved) {
  /* pages-проект полностью заменяет legacy-ключ: убираем мёртвый блоб,
   * который иначе занимает мегабайты квоты localStorage. */
  try {
    localStorage.removeItem(FLOW_LS_KEY);
  } catch {
    /* приватный режим и т.п. — не критично */
  }
}
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
  // A tokens wire is an intentional pass-through. For an IR wire the rendered
  // tree is authoritative: ir.tokens may have been inherited from a Header.
  const explicit = asRecord(tokensRaw);
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
  if (!colors.some((value) => value != null) && !fonts.some((value) => value != null)) {
    const inherited = asRecord(ir?.tokens);
    if (inherited) return { tokens: deepClone(inherited), summary: summarizeStyleDna(inherited) };
  }
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

export const useFlowStore = createStore<FlowStoreState>()((set, get) => ({
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
    const data = defaultData(type);
    if (type === "generator" && typeof window !== "undefined" && window.designDNA) {
      (data as { provider: string }).provider = "codex";
    }
    const node = {
      id: String(id),
      type,
      position: { x: rx, y: ry },
      // Svelte Flow keeps a custom node hidden until it has initial dimensions.
      // ResizeObserver replaces these bootstrap values with the real rendered size.
      initialWidth: 260,
      initialHeight: 120,
      data,
    } as FlowNode;
    set({ nodes: [...get().nodes, node], nextId: id + 1 });
    return { id, type, x: rx, y: ry, data: node.data };
  },

  /* Позиция ноды в мировых px (legacy Math.round на dragend, nodes.js:336-337) */
  moveNode: (id, x, y) => {
    get().moveNodes([{ id, x, y }]);
  },

  /* Multi-select drag is one user action: publish one array and wake autosave once. */
  moveNodes: (updates) => {
    const positions = new Map(
      updates.map(({ id, x, y }) => [String(id), { x: Math.round(x), y: Math.round(y) }]),
    );
    set({
      nodes: get().nodes.map((node) => {
        const position = positions.get(node.id);
        return position ? { ...node, position } : node;
      }),
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
        n.id === sid ? (() => {
          const nextPatch = { ...patch } as Record<string, unknown>;
          if (Object.prototype.hasOwnProperty.call(nextPatch, "ir")) {
            const currentRevision = Number((n.data as Record<string, unknown>)._irRevision) || 0;
            nextPatch._irRevision = currentRevision + 1;
          }
          return ({ ...n, data: { ...n.data, ...nextPatch } }) as FlowNode;
        })() : n,
      ),
    }));
  },

  getNodeIrRevision: (id) => {
    const node = get().nodes.find((item) => Number(item.id) === id);
    return node ? Number((node.data as Record<string, unknown>)._irRevision) || 0 : -1;
  },

  persistEditorDraft: (id, draft) => {
    const sid = String(id);
    const persisted = deepClone(draft);
    set((state) => ({
      nodes: state.nodes.map((node) =>
        node.id === sid
          ? ({ ...node, data: { ...node.data, _editorDraft: persisted } } as unknown as FlowNode)
          : node,
      ),
    }));
  },

  clearEditorDraft: (id) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((node) => {
        if (node.id !== sid) return node;
        const data = { ...node.data } as Record<string, unknown>;
        delete data._editorDraft;
        return { ...node, data } as FlowNode;
      }),
    }));
  },

  commitEditorDraft: (id, expectedRevision, ir) => {
    const sid = String(id);
    const node = get().nodes.find((item) => item.id === sid);
    if (!node) return false;
    const currentRevision = Number((node.data as Record<string, unknown>)._irRevision) || 0;
    if (currentRevision !== expectedRevision) return false;
    set((state) => ({
      nodes: state.nodes.map((item) => {
        if (item.id !== sid) return item;
        const data = { ...item.data, ir: deepClone(ir), _irRevision: currentRevision + 1 } as Record<string, unknown>;
        delete data._editorDraft;
        return { ...item, data } as FlowNode;
      }),
    }));
    return true;
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
          if (ir) {
            // Wait for exact IR extraction before updating downstream nodes.
            void get().runStyleDna(consId);
          } else {
            const dna = extractStyleDna(null, tokensRaw);
            get().setNodeData(consId, { tokens: dna.tokens, summary: dna.summary });
            get().setStatus(consId, "Style DNA обновлён", "ok");
            get().propagate(consId, visited);
          }
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
    const selectedProvider = data.provider === "kimi" || data.provider === "openai"
      ? data.provider
      : data.provider === "auto" ? "auto" : "codex";
    const desktop = window.designDNA;
    const provider = desktop
      ? selectedProvider
      : selectedProvider === "codex" ? "auto" : selectedProvider;
    const count = Math.max(1, Math.min(2, Number(data.count) || 1));
    const providerLabel = provider === "kimi"
      ? "Kimi K3"
      : provider === "openai" ? "GPT-5.6-sol" : provider === "auto" ? "Auto route" : "GPT Codex";
    get().setStatus(id, `Генерация (${providerLabel}, ${count})… 20–120 сек`);
    get().setBusy(id, true);
    try {
      const request = {
        brief,
        count,
        provider,
        styleHint,
        tokens,
        preset: data.preset || undefined,
      };
      let res: GenerateResp;
      if (!desktop) {
        res = await api<GenerateResp>("/api/generate", request);
      } else {
        const desktopProvider: "auto" | "codex" | "kimi" | "openai" = provider;
        const prepared = await api<GenerateResp>("/api/generate", { ...request, prepareOnly: true });
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить запросы генератора");
        const rawOutputs: string[] = [];
        for (const prompt of prepared.prompts) {
          const answer = await desktop.providers.chat(desktopProvider, prompt.messages, styleHint ? 0.3 : 0.8);
          rawOutputs.push(answer.content);
        }
        res = await api<GenerateResp>("/api/generate", { ...request, rawOutputs });
      }
      const variants = Array.isArray(res.variants) ? res.variants : [];
      get().setNodeData(id, { variants, active: 0 });
      const errNote = res.errors && res.errors.length ? `, ошибок: ${res.errors.length}` : "";
      const fixedCount = (res.qa || []).reduce((s, q) => s + (q.fixed || 0), 0);
      const qaNote = fixedCount ? `, автофиксов QA: ${fixedCount}` : "";
      const designNote = res.design?.label ? `, тип: ${res.design.label}` : "";
      get().setStatus(id, `Готово: вариантов ${variants.length}${errNote}${qaNote}${designNote}`, "ok");
      get().propagate(id);
    } catch (e) {
      const msg = friendlyProviderError(e);
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
        get().setStatus(id, "Скриншот → pixel capture через подключённый аккаунт…");
        const res = await api<ReproduceResp>("/api/reproduce", {
          image: data.image,
          url: "",
          provider: "auto",
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
        const rawUrl = (data.url || "").trim();
        const url = rawUrl && !/^[a-z][a-z\d+.-]*:\/\//i.test(rawUrl)
          ? rawUrl.startsWith("//") ? `https:${rawUrl}` : `https://${rawUrl}`
          : rawUrl;
        if (!url) {
          get().setStatus(id, "Введите URL сайта", "err");
          return;
        }
        if (!data.mine) {
          get().setStatus(id, "Отметьте «это мой сайт/есть право»", "err");
          return;
        }
        if (data.importedUrl === url && data.blocks.length > 0) {
          get().setStatus(id, `Уже загружено локально · ${data.blocks.length} блоков`, "ok");
          return;
        }
        if (url !== data.url) get().setNodeData(id, { url });
        get().setStatus(id, `Импортирую ${url.slice(0, 30)}…`);
        const res = await api<BlockParseResp>("/api/block-parse", {
          url,
          useAuthenticatedSession: !!data.authenticatedSession && !!window.designDNA?.sourceAuth,
          viewports: [
            { name: "desktop", width: 1440, height: 900 },
            { name: "tablet", width: 768, height: 1024 },
            { name: "mobile", width: 390, height: 844 },
          ],
        });
        const litBefore = new Set(data.blocks.filter((b) => b.lit).map((b) => b.name));
        const blocks = (res.blocks || []).map((b) => ({
          ...b,
          cached: !!res.cached || !!b.cached,
          lit: litBefore.has(b.name),
        }));
        get().setNodeData(id, { blocks, tokens: res.tokens || null, importedUrl: url });
        const sid = String(id);
        const alive = new Set<string>(["tokens", ...blocks.map((b) => b.name)]);
        set((state) => ({
          edges: state.edges.filter((e) => e.source !== sid || alive.has(e.sourceHandle ?? "")),
        }));
        const errCount = blocks.filter((b) => b.error).length;
        const authNote = res.authWarning ? ` · ${res.authWarning}` : "";
        const cacheNote = res.cached ? " · локальный кэш" : "";
        get().setStatus(id, `${blocks.length} блоков (${errCount} ошибок) · Source Import${cacheNote}${authNote}`, errCount ? "err" : "ok");
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
    if (!n || n.type !== "styledna" || st.busy[id]) return;
    const ir = pullInput(st.nodes, st.edges, n, "ir");
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    if (!ir && !tokensRaw) {
      get().setStatus(id, "Подключите IR или tokens", "err");
      return;
    }
    if (!ir) {
      const dna = extractStyleDna(null, tokensRaw);
      get().setNodeData(id, { tokens: dna.tokens, summary: dna.summary });
      get().setStatus(id, "Style DNA собран из tokens", "ok");
      get().propagate(id);
      return;
    }
    get().setBusy(id, true);
    get().setStatus(id, "Style DNA: извлекаю из входного IR…");
    try {
      const response = await extractStyleDnaApi(ir as IRObject);
      const tokens = asRecord(response.tokens);
      if (!tokens) throw new Error("сервер не вернул Style DNA");
      get().setNodeData(id, { tokens: deepClone(tokens), summary: summarizeStyleDna(tokens) });
      get().setStatus(id, "Style DNA собран из входного IR", "ok");
      get().propagate(id);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      get().setStatus(id, "Style DNA: " + message, "err");
      toast("Style DNA: " + message, "error");
    } finally {
      get().setBusy(id, false);
    }
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
    get().setStatus(id, `Derive: ${data.count} вариант(а) через подключённый аккаунт…`);
    get().setBusy(id, true);
    try {
      const request = {
        brief: prompt,
        count: data.count,
        provider: "auto",
        styleHint: styleHint || undefined,
        tokens: tokens && typeof tokens === "object" ? tokens : undefined,
      };
      let res: GenerateResp;
      const desktop = window.designDNA;
      if (!desktop) {
        res = await api<GenerateResp>("/api/generate", request);
      } else {
        // тот же transport-контракт, что у Generator: сервер готовит промпты,
        // LLM отвечает через подключённый аккаунт, сервер валидирует и чинит
        const prepared = await api<GenerateResp>("/api/generate", { ...request, prepareOnly: true });
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить запросы Derive");
        const rawOutputs: string[] = [];
        for (const p of prepared.prompts) {
          const answer = await desktop.providers.chat("auto", p.messages, 0.8);
          rawOutputs.push(answer.content);
        }
        res = await api<GenerateResp>("/api/generate", { ...request, rawOutputs });
      }
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
        provider: data.provider || "auto",
        mask: data.mask,
      };
      if (tokensRaw && typeof tokensRaw === "object") payload.tokens = tokensRaw;
      let res: ReskinResp;
      const desktop = window.designDNA;
      if (!desktop) {
        res = await api<ReskinResp>("/api/reskin", payload);
      } else {
        // desktop: сервер готовит reskin-промпт, аккаунт отвечает, сервер
        // делает merge-back/валидацию — креденшелы не покидают main-процесс
        const prepared = await api<{ prompts: Array<{ messages: Array<{ role: string; content: string }> }> }>(
          "/api/reskin", { ...payload, prepareOnly: true },
        );
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить промпт рестайла");
        const answer = await desktop.providers.chat("auto", prepared.prompts[0].messages, 0.7);
        res = await api<ReskinResp>("/api/reskin", { ...payload, rawOutput: answer.content });
      }
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

  /* Quality Pass: FastAPI prepares and validates every step. In desktop mode
   * judge/repair/rejudge run through whichever account is explicitly connected;
   * standalone web keeps the server-side provider compatibility path. */
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
      const request = {
        ir,
        brief: data.brief,
        min_score: data.minScore,
        repair: data.repair,
        rejudge: data.repair,
      };
      const desktop = window.designDNA;
      let res: QualityPassResp;
      if (!desktop) {
        res = await api<QualityPassResp>("/api/quality-pass", request);
      } else {
        const outputs: Partial<Record<"judge" | "repair" | "rejudge", string>> = {};
        const seen = new Set<string>();
        for (;;) {
          res = await api<QualityPassResp>("/api/quality-pass/codex-step", { ...request, outputs });
          const pending = res.pending;
          if (!pending) break;
          if (seen.has(pending.stage) || seen.size >= 3) {
            throw new Error("Quality Pass: некорректная последовательность этапов Codex");
          }
          seen.add(pending.stage);
          get().setStatus(id, `Quality Pass: ${pending.stage} через подключённый аккаунт…`);
          const answer = await desktop.providers.chat(
            "auto", pending.messages, pending.stage === "repair" ? 0.25 : 0.2, pending.profile,
          );
          outputs[pending.stage] = answer.content;
        }
      }
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
  /* Синхронизация из канваса Svelte Flow (bind:nodes/bind:edges — библиотека
   * сама применяет drag/select/remove к массивам). Удаления ведём через
   * deleteNode/deleteEdge — та же зачистка рёбер/статусов, что в legacy
   * onNodesChange; округление позиции на dragend — в moveNode из onnodedragstop. */
  syncFromCanvas: (nextNodes, nextEdges) => {
    const removedNodes = get().nodes.filter((n) => !nextNodes.some((x) => x.id === n.id));
    const removedEdges = get().edges.filter((e) => !nextEdges.some((x) => x.id === e.id));
    for (const n of removedNodes) get().deleteNode(Number(n.id));
    for (const e of removedEdges) get().deleteEdge(e.id);
    const alive = new Set(get().edges.map((e) => e.id));
    set({ nodes: nextNodes, edges: nextEdges.filter((e) => alive.has(e.id)) });
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

function samePersistedNodes(a: FlowNode[], b: FlowNode[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  return a.every((node, index) => {
    const other = b[index];
    return !!other
      && node.id === other.id
      && node.type === other.type
      && node.position.x === other.position.x
      && node.position.y === other.position.y
      && node.data === other.data;
  });
}

function samePersistedEdges(a: FlowEdge[], b: FlowEdge[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  return a.every((edge, index) => {
    const other = b[index];
    return !!other
      && edge.id === other.id
      && edge.source === other.source
      && edge.sourceHandle === other.sourceHandle
      && edge.target === other.target
      && edge.targetHandle === other.targetHandle;
  });
}

/* Автосейв: selection/measurement changes from Svelte Flow are runtime-only.
 * Serializing three Source Import payloads for every click can freeze the renderer.
 * view намеренно не будит автосейв: pan/zoom не сериализуют проект — вью
 * уезжает в сейв при следующем реальном изменении либо во flush на unload. */
useFlowStore.subscribe((state, prev) => {
  const nodesChanged = !samePersistedNodes(state.nodes, prev.nodes);
  const edgesChanged = !samePersistedEdges(state.edges, prev.edges);
  if (
    !nodesChanged &&
    !edgesChanged &&
    state.nextId === prev.nextId &&
    state.pages === prev.pages &&
    state.activePageId === prev.activePageId &&
    state.channels === prev.channels
  )
    return;
  localDirtySinceInit = true;
  scheduleProjectSave(() => buildPagesProjectPayload(useFlowStore.getState()));
});
