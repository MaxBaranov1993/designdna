import { createStore } from "zustand/vanilla";

import { api, apiGet, extractStyleDna as extractStyleDnaApi } from "./api";
import type {
  BlockParseJobResp,
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
import { fitFlowView } from "./graphdev";
import { offloadSourceEvidenceInPlace } from "../desktop/blobStore";
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
  NodeProvider,
  NodeType,
  ReskinNodeData,
  DesignSystemNodeData,
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

/* Провайдер ноды: поддерживаемый выбор проходит как есть, ретро-значения из
 * старых проектов мигрируют на Sol (тот же контракт, что в serialize.ts и
 * desktop/services/provider-router.mjs). */
const NODE_PROVIDERS = new Set<NodeProvider>(["openai", "codex", "claude"]);
function nodeProvider(value: unknown): NodeProvider {
  return NODE_PROVIDERS.has(value as NodeProvider) ? (value as NodeProvider) : "openai";
}
const PROVIDER_LABELS: Record<NodeProvider, string> = {
  openai: "GPT-5.6 Sol",
  codex: "Codex",
  claude: "Claude Opus",
};
type NodeEffort = "medium" | "high" | "max";
function nodeEffort(value: unknown): NodeEffort {
  return value === "high" || value === "max" ? value : "medium";
}
/* Codex — text-only контракт без reasoning; модель выбирает сам транспорт. */
function chatRoute(provider: NodeProvider, effort: unknown) {
  if (provider === "codex") return { provider, model: null };
  const reasoning = { effort: nodeEffort(effort) };
  if (provider === "claude") return { provider, model: "opus", reasoning };
  return { provider, model: "gpt-5.6-sol", reasoning };
}

/* AI-уточнение разбора Source.
 *
 * Модель видит только компактную сводку структуры (роли, имена, размеры) и
 * список того, чего не решили эвристики, — не весь IR: он весит мегабайты.
 * Ответ жёстко ограничен переименованиями и сменой роли блока; применяет их
 * сервер (blockparse.apply_refinements) с собственной валидацией. */
const REFINE_ROLES = [
  "header", "footer", "carousel", "categories", "product-grid", "services-grid",
  "journal", "how-it-works", "faq", "cta", "trust", "pricing", "testimonials",
  "gallery", "navigation", "status", "toolbar", "profile", "panel", "section",
];

function sourceStructureDigest(response: BlockParseResp) {
  return (response.blocks || []).map((block) => {
    const boundaries: Array<{ sourceKey: string; role: string; label: string }> = [];
    const walk = (node: unknown) => {
      if (!node || typeof node !== "object") return;
      const record = node as Record<string, unknown>;
      const meta = record.sourceMeta as Record<string, unknown> | undefined;
      if (meta?.componentBoundary && boundaries.length < 30) {
        boundaries.push({
          sourceKey: String(record.sourceKey || ""),
          role: String(meta.componentRole || ""),
          label: String(meta.componentLabel || ""),
        });
      }
      for (const child of (record.children as unknown[]) || []) walk(child);
    };
    for (const root of ((block.ir as Record<string, unknown> | undefined)?.tree as unknown[]) || []) walk(root);
    return {
      name: block.name,
      label: block.label,
      kind: block.kind,
      size: block.size,
      components: boundaries,
    };
  });
}

async function refineSourceWithAi(
  response: BlockParseResp,
  provider: NodeProvider,
  setStatus: (id: number, text: string, kind?: "ok" | "err") => void,
  id: number,
): Promise<BlockParseResp | null> {
  const desktop = window.designDNA;
  if (!desktop) return null;
  setStatus(id, "AI-уточнение структуры…");
  const instruction = [
    "Ты уточняешь результат автоматического разбора веб-страницы на компоненты.",
    "Дай человекочитаемые названия компонентам и уточни роли блоков.",
    `Допустимые роли блока: ${REFINE_ROLES.join(", ")}.`,
    "Ответь СТРОГО одним JSON-объектом вида",
    '{"operations":[{"op":"rename-block","block":"<name>","label":"<текст>"},',
    '{"op":"set-block-role","block":"<name>","role":"<роль>"},',
    '{"op":"rename-component","block":"<name>","sourceKey":"<ключ>","label":"<текст>"}]}',
    "Не добавляй пояснений. Не выдумывай блоки и sourceKey, которых нет во входных данных.",
  ].join(" ");
  const answer = await desktop.providers.chatRequest({
    ...chatRoute(provider, "medium"),
    messages: [
      { role: "system", content: instruction },
      {
        role: "user",
        content: JSON.stringify({
          structure: sourceStructureDigest(response),
          ambiguities: response.ambiguities || [],
        }),
      },
    ],
  });
  const match = String(answer.content || "").match(/\{[\s\S]*\}/);
  if (!match) return null;
  let operations: unknown;
  try {
    operations = (JSON.parse(match[0]) as { operations?: unknown }).operations;
  } catch {
    return null;
  }
  if (!Array.isArray(operations) || !operations.length) return null;
  const applied = await api<{ blocks: BlockParseResp["blocks"]; sourceArtifact: unknown; appliedCount: number }>(
    "/api/block-parse/refine", { blocks: response.blocks, operations },
  );
  if (!applied?.appliedCount) return null;
  setStatus(id, `AI-уточнение: ${applied.appliedCount} правок`);
  return { ...response, blocks: applied.blocks, sourceArtifact: applied.sourceArtifact as never };
}

const DESIGN_SYSTEM_SECTION_TYPES = new Set([
  "navbar", "hero", "logo-cloud", "feature-grid", "feature-alternating", "stats", "steps",
  "gallery", "testimonials", "pricing", "comparison", "team", "blog-grid", "faq", "cta",
  "contact-form", "newsletter", "banner", "footer", "source-block",
]);

function renderableDesignSystemMaster(component: { templateIr?: IRObject; masterIr?: IRObject }): IRObject | null {
  if (component.templateIr) return deepClone(component.templateIr);
  const master = component.masterIr;
  const tree = Array.isArray(master?.tree) ? master.tree : [];
  const root = tree[0] as Record<string, any> | undefined;
  if (!master || !root) return null;
  if (DESIGN_SYSTEM_SECTION_TYPES.has(String(root.type || ""))) return deepClone(master);
  const frame = root.frame && typeof root.frame === "object"
    ? Object.fromEntries(["width", "height"].filter((key) => root.frame[key] != null).map((key) => [key, deepClone(root.frame[key])]))
    : {};
  return {
    version: master.version,
    tokens: deepClone(master.tokens),
    tree: [{
      id: "ds-master-preview", type: "source-block", variant: "component-master", props: {},
      ...(Object.keys(frame).length ? { frame } : {}), children: [deepClone(root)],
    }],
  } as IRObject;
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
  designSystems: DesignSystemsRegistry;
  designSystemPicker: DesignSystemPickerConfig;
  projectHydrated: boolean;
  statuses: Record<number, NodeStatus>;
  /* run-based ноды в полёте запроса (спиннер на ноде); runtime-поле, в сейв не попадает */
  busy: Record<number, boolean>;
  progresses: Record<number, { startedAt: number; expectedMs: number; label: string; percent?: number }>;

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
  setProgress: (id: number, progress: { expectedMs: number; label: string; percent?: number } | null) => void;
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
  addVideoChainPage: (options?: { url?: string; provider?: string }) => void;
  switchPage: (id: string) => void;
  renamePage: (id: string, name: string) => void;
  deletePage: (id: string) => void;
  loadPersistedProject: () => Promise<void>;
  refreshDesignSystems: () => Promise<void>;
  createDesignSystemFromSource: (sourceId: number, options?: { name?: string }) => Promise<number | null>;
  promoteVariantToDesignSystem: (generatorId: number) => Promise<number | null>;
  recordVariantTaste: (generatorId: number, kind: "accepted" | "rejected") => Promise<boolean>;
  setDesignSystemPicker: (patch: Partial<DesignSystemPickerConfig>) => void;
  publishDesignSystem: (nodeId: number) => Promise<boolean>;
  setDefaultDesignSystem: (nodeId: number) => Promise<boolean>;
  rebuildDesignSystemFromSource: (nodeId: number) => Promise<boolean>;
  saveDesignSystemDocument: (nodeId: number, document: Record<string, unknown>) => Promise<boolean>;
  restorePublishedDesignSystem: (nodeId: number, ref?: { systemId?: string; revision?: number }) => Promise<boolean>;
  applyDesignSystemToEditor: (nodeId: number, componentKey: string) => { editNodeId: number; previousIr: IRObject | null } | null;
  restoreDesignSystemEditorApply: (editNodeId: number, previousIr: IRObject | null) => void;
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
const initialDesignSystems: DesignSystemsRegistry =
  (projectSaved as unknown as { designSystems?: DesignSystemsRegistry } | null)?.designSystems
  || { systems: [], defaultSystemRef: null };

export interface DesignSystemsRegistry {
  systems: Array<Record<string, unknown> & { systemId: string; name: string; status: string; revision: number; contentHash?: string }>;
  defaultSystemRef: { systemId: string; revision: number; contentHash?: string } | null;
}

export interface DesignSystemPickerConfig {
  selection: "inherit" | "none" | string;
  usageMode: "strict" | "extend" | "style-only";
  fixtureProfile: string;
}

const emptyPicker: DesignSystemPickerConfig = {
  selection: "inherit",
  usageMode: "strict",
  fixtureProfile: "typical",
};

function pinnedDesignSystemRef(
  data: Record<string, unknown>,
  registry: DesignSystemsRegistry,
  picker?: DesignSystemPickerConfig,
): Record<string, unknown> | null {
  const dsSelection = String(data.designSystemSelection || picker?.selection || "inherit");
  if (dsSelection === "none") return null;
  const usageMode = String(data.designSystemUsageMode || picker?.usageMode || "strict");
  const fixture = String(data.designSystemFixture || picker?.fixtureProfile || "typical");
  const target = dsSelection === "inherit" ? registry.defaultSystemRef?.systemId : dsSelection;
  const system = registry.systems?.find((sys) => sys.systemId === target && sys.status === "published");
  if (!system) return null;
  const inheritRef = registry.defaultSystemRef;
  const revision = dsSelection === "inherit" ? (inheritRef?.revision ?? system.revision) : system.revision;
  const contentHash = (dsSelection === "inherit" ? inheritRef?.contentHash : undefined) || system.contentHash || "";
  return {
    systemId: system.systemId,
    revision,
    contentHash,
    usageMode,
    mockFixtureProfile: fixture,
  };
}

async function fetchDesignSystemsList(): Promise<DesignSystemsRegistry> {
  try {
    const resp = await fetch("/api/design-system/list");
    if (!resp.ok) return { systems: [], defaultSystemRef: null };
    const data = await resp.json();
    return { systems: data.systems || [], defaultSystemRef: data.defaultSystemRef || null };
  } catch {
    return { systems: [], defaultSystemRef: null };
  }
}

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
  designSystems: initialDesignSystems,
  designSystemPicker: emptyPicker,
  // A clean desktop profile has no localStorage snapshot. Until SQLite has
  // answered, the empty canvas must not sync over the canonical project.
  projectHydrated: Boolean(projectSaved),
  nodes: hydratePageBridgeNodes(initialActiveGraph.nodes, initialChannels),
  edges: initialActiveGraph.edges,
  view: initialActiveGraph.view,
  nextId: initialActiveGraph.nextId,
  pages: initialPages,
  activePageId: initialActivePageId,
  channels: initialChannels,
  statuses: {},
  busy: {},
  /* Прогресс длинных операций (импорт/генерация): асимптотическая кривая в
   * UI, реальное завершение снимает прогресс и пишет итоговое время в статус */
  progresses: {},

  /* Зеркало addNode (nodes.js:256-264): id из nextId, координаты Math.round */
  addNode: (type, x, y) => {
    const id = get().nextId;
    const rx = Math.round(x);
    const ry = Math.round(y);
    const data = defaultData(type);
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
    const before = get().nodes.find((n) => n.id === sid);
    if (!before) return;
    // No-op патч не будит стор: каждый set пересоздаёт массив nodes и будит
    // все подписки (автосейв-компаратор, канвас), а поля ввода шлют setNodeData
    // на каждое нажатие. Запись ir всегда считается изменением (бампается
    // _irRevision), равенство остальных ключей — по ссылке.
    const beforeData = before.data as Record<string, unknown>;
    const isNoop = !Object.prototype.hasOwnProperty.call(patch, "ir")
      && Object.keys(patch).every((key) => beforeData[key] === (patch as Record<string, unknown>)[key]);
    if (isNoop) return;
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

  /* Backend stages can supply a measured percent. Updates preserve startedAt so
   * elapsed time remains the duration of the whole operation. */
  setProgress: (id, progress) => {
    set((state) => ({
      progresses: progress
        ? { ...state.progresses, [id]: {
            startedAt: state.progresses[id]?.startedAt ?? Date.now(),
            expectedMs: Math.max(1_000, progress.expectedMs),
            label: progress.label,
            ...(Number.isFinite(progress.percent) ? { percent: Math.max(0, Math.min(100, Number(progress.percent))) } : {}),
          } }
        : Object.fromEntries(Object.entries(state.progresses).filter(([key]) => Number(key) !== id)),
    }));
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
      } else if (cons.type === "designui") {
        const artifact = pullInput(nodes, edges, cons, "artifact");
        if (artifact && typeof artifact === "object") {
          get().setNodeData(consId, { artifact: deepClone(artifact), selectedComponent: 0 });
          get().setStatus(consId, "Design UI synchronized", "ok");
          get().propagate(consId, visited);
        }
      } else if (cons.type === "designsystem") {
        const artifact = pullInput(nodes, edges, cons, "artifact");
        if (artifact && typeof artifact === "object") {
          get().setNodeData(consId, { sourceUpdate: true });
          get().setStatus(consId, "Source changed — review and Sync before publishing", "ok");
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
    const desktop = window.designDNA;
    const effort: "medium" | "high" | "max" = ["medium", "high", "max"].includes(data.effort)
      ? data.effort
      : "medium";
    const provider = nodeProvider(data.provider);
    const count = Math.max(1, Math.min(2, Number(data.count) || 1));
    const providerLabel = provider === "codex"
      ? PROVIDER_LABELS.codex
      : `${PROVIDER_LABELS[provider]} · ${effort}`;
    get().setStatus(id, `Генерация (${providerLabel}, ${count})… 20–120 сек`);
    get().setBusy(id, true);
    const startedAt = Date.now();
    get().setProgress(id, { expectedMs: 90_000, label: `Генерация · ${providerLabel}` });
    try {
      const designSystemRef = pinnedDesignSystemRef(
        data as unknown as Record<string, unknown>,
        get().designSystems,
        get().designSystemPicker,
      );
      const request = {
        brief,
        count,
        provider,
        effort,
        styleHint,
        tokens,
        preset: data.preset || undefined,
        designSystem: designSystemRef,
      };
      let res: GenerateResp;
      if (!desktop) {
        res = await api<GenerateResp>("/api/generate", request);
      } else {
        const prepared = await api<GenerateResp>("/api/generate", { ...request, prepareOnly: true });
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить запросы генератора");
        const rawOutputs: string[] = [];
        for (const prompt of prepared.prompts) {
          const answer = await desktop.providers.chatRequest({
            ...chatRoute(provider, effort),
            messages: prompt.messages,
          });
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
      get().setStatus(id, `Готово: вариантов ${variants.length}${errNote}${qaNote}${designNote} · ${((Date.now() - startedAt) / 1000).toFixed(0)}с`, "ok");
      get().propagate(id);
    } catch (e) {
      const msg = friendlyProviderError(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Генератор: " + msg, "error");
    } finally {
      get().setProgress(id, null);
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
    const startedAt = Date.now();
    get().setProgress(id, { expectedMs: 90_000, label: data.mode === "screenshot" ? "Скриншот → IR" : "Импорт Source" });
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
        get().setNodeData(id, { blocks, tokens: dna.tokens, sourceArtifact: null });
        const secs = ((Date.now() - startedAt) / 1000).toFixed(0);
        get().setStatus(id, ir ? `Готово: capture + Style DNA · ${secs}с` : "Не удалось получить IR из скриншота", ir ? "ok" : "err");
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
        const desktop = window.designDNA;
        const initial = await api<BlockParseResp | BlockParseJobResp>("/api/block-parse", {
          url,
          asyncJob: true,
          fullResolutionEvidence: !!desktop,
          useAuthenticatedSession: !!data.authenticatedSession && !!window.designDNA?.sourceAuth,
          viewports: [
            { name: "desktop", width: 1440, height: 900 },
            { name: "tablet", width: 768, height: 1024 },
            { name: "mobile", width: 390, height: 844 },
          ],
        });
        let res: BlockParseResp;
        if ("jobId" in initial) {
          let job = initial;
          const started = Date.now();
          const deadline = started + 12 * 60_000;
          while (job.status === "queued" || job.status === "running") {
            get().setProgress(id, {
              expectedMs: 90_000,
              label: job.stageLabel || "Source Import",
              percent: job.progress,
            });
            get().setStatus(id, `${job.stageLabel || "Source Import"} · ${Math.round(job.progress)}%`);
            if (Date.now() >= deadline) throw new Error("Source Import превысил лимит 12 минут");
            // Бэкофф: первые 10 с опрашиваем часто (стадии сменяются быстро),
            // дальше реже — импорт идёт минутами, а каждый опрос это полный
            // IPC → stdio → ASGI round-trip.
            const elapsed = Date.now() - started;
            const delay = elapsed < 10_000 ? 400 : elapsed < 60_000 ? 1_000 : 2_000;
            await new Promise((resolve) => setTimeout(resolve, delay));
            job = await apiGet<BlockParseJobResp>(`/api/block-parse/job/${encodeURIComponent(job.jobId)}`);
          }
          if (job.status === "error") throw new Error(job.error || "Source Import завершился с ошибкой");
          if (!job.result) throw new Error("Source Import завершился без результата");
          res = job.result;
        } else {
          // Compatibility with web/dev servers and intercepted UI fixtures.
          res = initial;
        }
        // Source screenshots are comparison evidence. Persist them before the
        // large editable IR enters state; the generic autosave traversal is
        // intentionally time-boxed and may otherwise reach these fields too
        // late, leaving Compare empty after a restart.
        await offloadSourceEvidenceInPlace(res.blocks || []);
        // AI-уточнение: детерминированный разбор перечислил, чего не смог
        // решить сам; модель переименовывает компоненты и уточняет роли блоков.
        // IR не меняется — fidelity-гейт этим путём обойти нельзя.
        if (data.aiRefine && res.ambiguities?.length && window.designDNA) {
          try {
            const refined = await refineSourceWithAi(
              res, nodeProvider(data.aiProvider), get().setStatus, id,
            );
            if (refined) res = refined;
          } catch (error) {
            // Уточнение опционально: детерминированный результат остаётся в силе.
            get().setStatus(id, `AI-уточнение пропущено: ${friendlyProviderError(error)}`);
          }
        }
        const litBefore = new Set(data.blocks.filter((b) => b.lit).map((b) => b.name));
        const blocks = (res.blocks || []).map((b) => ({
          ...b,
          cached: !!res.cached || !!b.cached,
          lit: litBefore.has(b.name),
        }));
        const timingsMs = res.diagnostics?.timingsMs || {};
        const measuredTotalMs = Number(timingsMs.total);
        get().setNodeData(id, {
          blocks,
          tokens: res.tokens || null,
          sourceArtifact: res.sourceArtifact || null,
          importedUrl: url,
          lastRun: {
            cached: !!res.cached,
            pipelineVersion: res.diagnostics?.pipelineVersion,
            totalMs: Number.isFinite(measuredTotalMs) ? measuredTotalMs : Date.now() - startedAt,
            timingsMs,
          },
        });
        const sid = String(id);
        const alive = new Set<string>(["tokens", ...blocks.map((b) => b.name)]);
        set((state) => ({
          edges: state.edges.filter((e) => e.source !== sid || alive.has(e.sourceHandle ?? "")),
        }));
        const errCount = blocks.filter((b) => b.error).length;
        const authNote = res.authWarning ? ` · ${res.authWarning}` : "";
        const cacheNote = res.cached ? " · локальный кэш" : "";
        const secs = ((Number.isFinite(measuredTotalMs) ? measuredTotalMs : Date.now() - startedAt) / 1000).toFixed(1);
        get().setStatus(id, `${blocks.length} блоков (${errCount} ошибок) · Source Import${cacheNote}${authNote} · ${secs}с`, errCount ? "err" : "ok");
      }
      get().propagate(id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Source Import: " + msg, "error");
    } finally {
      get().setProgress(id, null);
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
        designSystem: pinnedDesignSystemRef(
          data as unknown as Record<string, unknown>,
          get().designSystems,
          get().designSystemPicker,
        ),
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
          const answer = await desktop.providers.chatRequest({
            provider: "openai",
            model: "gpt-5.6-sol",
            messages: p.messages,
            reasoning: { effort: "medium" },
          });
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
        provider: nodeProvider(data.provider),
        effort: ["medium", "high", "max"].includes(data.effort) ? data.effort : "medium",
        mask: data.mask,
        designSystem: pinnedDesignSystemRef(
          data as unknown as Record<string, unknown>,
          get().designSystems,
          get().designSystemPicker,
        ),
      };
      if (tokensRaw && typeof tokensRaw === "object") payload.tokens = tokensRaw;
      let res: ReskinResp;
      const desktop = window.designDNA;
      if (!desktop) {
        res = await api<ReskinResp>("/api/reskin", payload);
      } else {
        // desktop: сервер готовит reskin-промпт, аккаунт отвечает, сервер
        // делает merge-back/валидацию — креденшелы не покидают main-процесс
        const prepared = await api<{ prompts: Array<{ messages: import("./api").ApiChatMessage[] }> }>(
          "/api/reskin", { ...payload, prepareOnly: true },
        );
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить промпт рестайла");
        const effort = ["medium", "high", "max"].includes(data.effort) ? data.effort : "medium";
        const answer = await desktop.providers.chatRequest({
          ...chatRoute(nodeProvider(data.provider), effort),
          messages: prepared.prompts[0].messages,
        });
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
          const answer = await desktop.providers.chatRequest({
            provider: "openai",
            model: "gpt-5.6-sol",
            messages: pending.messages,
            reasoning: { effort: "high" },
          });
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
      progresses: {},
    }));
  },

  refreshDesignSystems: async () => {
    const list = await fetchDesignSystemsList();
    set({ designSystems: list });
  },

  /* Создание Design System из Source (ТЗ §7.1): нода рядом с Source,
   * сборка draft на сервере, карточка заполняется summary. */
  createDesignSystemFromSource: async (sourceId, options) => {
    const st = get();
    const source = st.nodes.find((n) => Number(n.id) === Number(sourceId));
    if (!source || source.type !== "sourceimport") return null;
    const data = source.data as SourceImportNodeData;
    if (!data.blocks?.length) {
      get().setStatus(sourceId, "Source не содержит блоков — сначала импорт", "err");
      return null;
    }
    const node = get().addNode("designsystem", source.position.x + 380, source.position.y);
    const dsId = Number(node.id);
    get().connect({ node: sourceId, port: "artifact" }, { node: dsId, port: "artifact" });
    get().setStatus(dsId, "Собираю UI Kit из Source…");
    get().setBusy(dsId, true);
    try {
      const resp = await fetch("/api/design-system/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceNodeId: String(sourceId), sourceUrl: data.url || "",
          blocks: data.blocks, tokens: data.tokens || {},
          sourceArtifact: data.sourceArtifact || null,
          name: options?.name || `UI Kit · ${data.url || "Source"}`,
          capturedAt: String((data as SourceImportNodeData & { capturedAt?: string }).capturedAt || ""),
        }),
      });
      const result = await resp.json();
      if (result.error) {
        get().setStatus(dsId, "Ошибка: " + result.error, "err");
        get().deleteNode(dsId);
        return null;
      }
      get().setNodeData(dsId, {
        systemId: result.document.id, name: result.document.name, status: "draft",
        revision: 0, summary: result.summary, sourceNodeId: sourceId,
        defaultSet: false, sourceUpdate: false,
        document: result.document,
      } as unknown as Partial<DesignSystemNodeData>);
      get().setStatus(dsId, `Черновик готов: ${result.summary.components} компонентов · ${result.summary.variants} вариантов`, "ok");
      return dsId;
    } catch (e) {
      get().setStatus(dsId, "Ошибка: " + (e instanceof Error ? e.message : String(e)), "err");
      return null;
    } finally {
      get().setBusy(dsId, false);
    }
  },

  promoteVariantToDesignSystem: async (generatorId) => {
    const source = get().nodes.find((node) => Number(node.id) === Number(generatorId));
    if (!source || source.type !== "generator") return null;
    const data = source.data as GeneratorNodeData;
    const active = data.variants?.[data.active];
    if (!active) {
      get().setStatus(generatorId, "Нет активного варианта для закрепления", "err");
      return null;
    }
    get().setBusy(generatorId, true);
    get().setStatus(generatorId, "Закрепляю identity как Design System…");
    let createdId: number | null = null;
    try {
      const resp = await fetch("/api/design-system/identity/promote", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Style · ${String(data.ownPrompt || "Generator").trim().slice(0, 48)}`,
          sourceNodeId: String(generatorId), ir: active, visualReferences: [],
        }),
      });
      const result = await resp.json();
      if (!resp.ok || result.error || !result.document) throw new Error(result.error || `HTTP ${resp.status}`);
      const node = get().addNode("designsystem", source.position.x + 380, source.position.y + 120);
      createdId = Number(node.id);
      get().setNodeData(createdId, {
        systemId: result.document.id, name: result.document.name, status: "draft",
        revision: 0, summary: result.summary, sourceNodeId: generatorId,
        defaultSet: false, sourceUpdate: false, document: result.document,
      } as unknown as Partial<DesignSystemNodeData>);
      get().setStatus(createdId, `Identity закреплена · ${result.summary.identitySignatures || 0} signatures · ${result.summary.identityTests || 0} tests`, "ok");
      const meta = (active as Record<string, any>).meta || {};
      await fetch("/api/project/taste/outcome", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "promoted", payload: {
          systemId: result.document.id,
          compiledContextHash: meta.compiledContextHash || "",
          archetypeId: meta.archetypeId || "",
          ruleIds: (result.document.identity?.signatures || []).map((item: any) => item.id),
        }}),
      });
      get().setStatus(generatorId, "Стиль закреплён в черновик Design System", "ok");
      return createdId;
    } catch (error) {
      if (createdId != null) get().deleteNode(createdId);
      const message = error instanceof Error ? error.message : String(error);
      get().setStatus(generatorId, "Не удалось закрепить стиль: " + message, "err");
      toast("Design Identity: " + message, "error");
      return null;
    } finally {
      get().setBusy(generatorId, false);
    }
  },

  recordVariantTaste: async (generatorId, kind) => {
    const source = get().nodes.find((node) => Number(node.id) === Number(generatorId));
    if (!source || source.type !== "generator") return false;
    const data = source.data as GeneratorNodeData;
    const active = data.variants?.[data.active] as Record<string, any> | undefined;
    if (!active) return false;
    const meta = active.meta || {};
    try {
      const resp = await fetch("/api/project/taste/outcome", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, payload: {
          systemId: meta.designSystemRef?.systemId || "",
          compiledContextHash: meta.compiledContextHash || "",
          archetypeId: meta.archetypeId || "",
          ruleIds: (meta.identityReport?.results || []).filter((item: any) => item.passed).map((item: any) => item.id),
        }}),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      get().setStatus(generatorId, kind === "accepted" ? "Вариант принят в Taste Memory" : "Вариант отклонён в Taste Memory", "ok");
      return true;
    } catch (error) {
      get().setStatus(generatorId, "Taste Memory: " + (error instanceof Error ? error.message : String(error)), "err");
      return false;
    }
  },

  setDesignSystemPicker: (patch) => {
    set((state) => ({ designSystemPicker: { ...state.designSystemPicker, ...patch } }));
  },

  publishDesignSystem: async (nodeId) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    get().setBusy(nodeId, true);
    get().setNodeData(nodeId, { busyAction: "publish", lastError: "" });
    get().setStatus(nodeId, "Публикация ревизии…");
    try {
      let document = (data.document || null) as Record<string, unknown> | null;
      if (!document && data.systemId) {
        const resp = await fetch("/api/design-system/get", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ systemId: data.systemId, revision: 0 }),
        });
        const got = await resp.json();
        document = got.document || null;
      }
      if (!document) {
        get().setStatus(nodeId, "Нет документа для публикации", "err");
        get().setNodeData(nodeId, { lastError: "Нет документа для публикации" });
        return false;
      }
      const pub = await fetch("/api/design-system/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
      });
      const result = await pub.json();
      if (result.errors?.length || result.error) {
        const message = result.errors?.[0]?.message || result.error || "публикация блокирована";
        get().setStatus(nodeId, `Публикация блокирована: ${message}`, "err");
        get().setNodeData(nodeId, { lastError: message });
        return false;
      }
      get().setNodeData(nodeId, {
        status: "published",
        revision: result.document.revision,
        summary: result.summary,
        contentHash: result.document.contentHash || "",
        // опубликованная копия не хранится в ноде: ревизия живёт на сервере
        // (design_system_revisions), документ подтянется по ссылке
        // systemId@revision при следующем открытии редактора — автосейв
        // графа не таскает мегабайтные снимки
        document: null,
        lastError: "",
      });
      get().setStatus(nodeId, `Опубликовано v${result.document.revision}${result.duplicate ? " (без изменений)" : ""}`, "ok");
      await get().refreshDesignSystems();
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      get().setStatus(nodeId, "Ошибка: " + message, "err");
      get().setNodeData(nodeId, { lastError: message });
      return false;
    } finally {
      get().setBusy(nodeId, false);
      get().setNodeData(nodeId, { busyAction: "" });
    }
  },

  setDefaultDesignSystem: async (nodeId) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    if (!data.systemId) return false;
    get().setBusy(nodeId, true);
    get().setNodeData(nodeId, { busyAction: "default", lastError: "" });
    get().setStatus(nodeId, "Назначаю системой проекта…");
    try {
      const resp = await fetch("/api/design-system/default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemId: data.systemId }),
      });
      const result = await resp.json();
      if (result.error) {
        get().setStatus(nodeId, "Ошибка: " + result.error, "err");
        get().setNodeData(nodeId, { lastError: result.error });
        return false;
      }
      const selectedId = Number(nodeId);
      set((state) => ({
        nodes: state.nodes.map((node) => {
          if (node.type !== "designsystem") return node;
          const isSelected = Number(node.id) === selectedId;
          return {
            ...node,
            data: {
              ...node.data,
              defaultSet: isSelected,
              ...(isSelected ? { lastError: "" } : {}),
            },
          } as FlowNode;
        }),
      }));
      await get().refreshDesignSystems();
      get().setStatus(nodeId, "Назначена системой проекта по умолчанию", "ok");
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      get().setStatus(nodeId, "Ошибка: " + message, "err");
      get().setNodeData(nodeId, { lastError: message });
      return false;
    } finally {
      get().setBusy(nodeId, false);
      get().setNodeData(nodeId, { busyAction: "" });
    }
  },

  rebuildDesignSystemFromSource: async (nodeId) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    const sourceNode = get().nodes.find((x) => Number(x.id) === Number(data.sourceNodeId));
    if (!sourceNode) {
      get().setStatus(nodeId, "Source-нода не найдена", "err");
      get().setNodeData(nodeId, { lastError: "Source-нода не найдена" });
      return false;
    }
    get().setBusy(nodeId, true);
    get().setNodeData(nodeId, { busyAction: "sync", lastError: "" });
    get().setStatus(nodeId, "Синхронизация с Source…");
    try {
      const resp = await fetch("/api/design-system/build", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceNodeId: data.sourceNodeId, sourceUrl: (sourceNode.data as SourceImportNodeData).url || "",
          blocks: (sourceNode.data as SourceImportNodeData).blocks || [],
          tokens: (sourceNode.data as SourceImportNodeData).tokens || {},
          sourceArtifact: (sourceNode.data as SourceImportNodeData).sourceArtifact || null,
          name: data.name,
          capturedAt: String((sourceNode.data as SourceImportNodeData & { capturedAt?: string }).capturedAt || ""),
        }),
      });
      const result = await resp.json();
      if (result.error) {
        get().setStatus(nodeId, "Ошибка: " + result.error, "err");
        get().setNodeData(nodeId, { lastError: result.error });
        return false;
      }
      get().setNodeData(nodeId, {
        systemId: result.document.id,
        name: result.document.name,
        status: "draft",
        summary: result.summary,
        sourceUpdate: false,
        document: result.document,
        lastError: "",
      });
      get().setStatus(nodeId, "Черновик пересобран из Source — проверьте и опубликуйте", "ok");
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      get().setStatus(nodeId, "Ошибка: " + message, "err");
      get().setNodeData(nodeId, { lastError: message });
      return false;
    } finally {
      get().setBusy(nodeId, false);
      get().setNodeData(nodeId, { busyAction: "" });
    }
  },

  saveDesignSystemDocument: async (nodeId, document) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    try {
      const resp = await fetch("/api/design-system/save-draft", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
      });
      const result = await resp.json();
      if (result.error) {
        get().setNodeData(nodeId, { lastError: result.error });
        get().setStatus(nodeId, "Ошибка: " + result.error, "err");
        return false;
      }
      get().setNodeData(nodeId, {
        document: result.document || document,
        summary: result.summary,
        status: "draft",
        lastError: "",
      });
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      get().setNodeData(nodeId, { lastError: message });
      get().setStatus(nodeId, "Ошибка: " + message, "err");
      return false;
    }
  },

  restorePublishedDesignSystem: async (nodeId, ref) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    const systemId = String(ref?.systemId || data.systemId || "");
    const revision = Number(ref?.revision || data.revision || 0);
    if (!systemId) {
      get().setNodeData(nodeId, { lastError: "Нет опубликованной ревизии для восстановления" });
      return false;
    }
    try {
      const resp = await fetch("/api/design-system/restore-published", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemId, revision }),
      });
      const result = await resp.json();
      if (result.error || !result.document) {
        get().setNodeData(nodeId, { lastError: result.error || "Не удалось восстановить опубликованную ревизию" });
        get().setStatus(nodeId, "Ошибка: " + (result.error || "restore failed"), "err");
        return false;
      }
      get().setNodeData(nodeId, {
        document: null,
        contentHash: result.document.contentHash || "",
        summary: result.summary,
        status: "published",
        revision: result.document.revision,
        lastError: "",
      });
      await get().refreshDesignSystems();
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      get().setNodeData(nodeId, { lastError: message });
      get().setStatus(nodeId, "Ошибка: " + message, "err");
      return false;
    }
  },

  applyDesignSystemToEditor: (nodeId, componentKey) => {
    const st = get();
    const dsNode = st.nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!dsNode || dsNode.type !== "designsystem") return null;
    const data = dsNode.data as DesignSystemNodeData;
    const document = (data.document || {}) as { components?: Record<string, { templateIr?: IRObject; masterIr?: IRObject; componentKey?: string }> };
    const comp = document.components?.[componentKey];
    const templateIr = comp ? renderableDesignSystemMaster(comp) : null;
    if (!templateIr) {
      get().setStatus(nodeId, "Нет template IR у выбранного компонента", "err");
      return null;
    }
    const existing = st.nodes.find((x) => {
      if (x.type !== "edit") return false;
      const master = (x.data as Record<string, unknown>)._dsMaster as { systemId?: string; componentKey?: string } | undefined;
      return master?.systemId === data.systemId && master?.componentKey === componentKey;
    });
    const created = existing || get().addNode("edit", dsNode.position.x + 360, dsNode.position.y);
    const editNodeId = Number(created.id);
    const current = get().nodes.find((x) => Number(x.id) === editNodeId);
    const previousIr = ((current?.data as { ir?: IRObject | null } | undefined)?.ir || null) as IRObject | null;
    get().setNodeData(editNodeId, {
      ir: deepClone(templateIr),
      _dsMaster: { systemId: data.systemId, componentKey, nodeId },
      _dsPreviousIr: previousIr,
    });
    window.dispatchEvent(new Event("designdna:ensure-editor"));
    get().setStatus(nodeId, `Мастер «${componentKey}» открыт в DNA Editor`, "ok");
    return { editNodeId, previousIr };
  },

  restoreDesignSystemEditorApply: (editNodeId, previousIr) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(editNodeId));
    if (!n || n.type !== "edit") return;
    if (previousIr) get().setNodeData(editNodeId, { ir: deepClone(previousIr) });
    else get().setNodeData(editNodeId, { ir: null });
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
      progresses: {},
    }));
  },

  /* Параллельная видео-ветка — отдельной страницей, не трогая текущий граф:
   * Source Import (url, по умолчанию rsale.net) → Generator → Interaction
   * Recorder → Motion Editor (MP4). AI-звено использует фиксированный
   * gpt-5.6-sol; effort задаётся самой Generator-нодой. */
  addVideoChainPage: (options) => {
    const rawUrl = (options?.url || "rsale.net").trim() || "rsale.net";
    const url = /^[a-z][a-z\d+.-]*:\/\//i.test(rawUrl)
      ? rawUrl
      : rawUrl.startsWith("//") ? `https:${rawUrl}` : `https://${rawUrl}`;
    const host = url.replace(/^https?:\/\//, "").replace(/\/.*$/, "") || "source";
    const provider = "openai";
    let nextId = 1;
    const mkNode = (type: NodeType, x: number, y: number, patch: Record<string, unknown> = {}) => ({
      id: String(nextId++),
      type,
      position: { x: Math.round(x), y: Math.round(y) },
      initialWidth: 260,
      initialHeight: 120,
      data: { ...defaultData(type), ...patch },
    }) as FlowNode;
    // один ряд слева-направо: ширины нод (360/260/300/420/390) + зазор 50px,
    // перекрытий нет даже с длинным списком блоков Source Import
    const source = mkNode("sourceimport", 40, 120, { mode: "url", url, mine: true });
    const prompt = mkNode("prompt", 450, 120, {
      text:
        `Видео-версия главной страницы ${host} по Style DNA источника: сохрани цвета, ` +
        "шрифты и ритм секций. Собери динамичный лендинг под 15-секундный ролик: " +
        "hero с крупным заголовком и CTA, две-три короткие секции с ясной иерархией, " +
        "финальный экран с призывом. Усиль контраст и крупность типографики — " +
        "текст должен читаться в видео.",
    });
    const generator = mkNode("generator", 760, 120, { provider, count: 1 });
    const recorder = mkNode("recorder", 1110, 120);
    const motion = mkNode("motion", 1580, 120);
    const nodes = [source, prompt, generator, recorder, motion];
    const edge = (fromNode: number, fromPort: string, toNode: number, toPort: string) =>
      makeRfEdge(nodes, { node: fromNode, port: fromPort }, { node: toNode, port: toPort });
    const edges = [
      edge(Number(prompt.id), "out", Number(generator.id), "prompt"),
      edge(Number(source.id), "tokens", Number(generator.id), "tokens"),
      edge(Number(generator.id), "ir", Number(recorder.id), "ir"),
      edge(Number(generator.id), "ir", Number(motion.id), "ir"),
      edge(Number(recorder.id), "interaction", Number(motion.id), "interaction"),
    ];
    const id = pageId();
    const page: FlowPage = {
      id,
      name: `${host} → видео`,
      nodes,
      edges,
      view: { ...DEFAULT_VIEW },
      nextId,
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
      progresses: {},
    }));
    // вписать цепочку в экран: ноды измеряются асинхронно, поэтому дважды
    setTimeout(fitFlowView, 80);
    setTimeout(fitFlowView, 450);
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
      progresses: {},
    });
    // каждая страница начинается с полного вида: без ручного зума
    setTimeout(fitFlowView, 80);
    setTimeout(fitFlowView, 450);
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
      progresses: {},
    });
  },

  loadPersistedProject: async () => {
    void get().refreshDesignSystems(); // registry не блокирует загрузку проекта
    const project = await loadPagesProjectFromDb();
    if (!project) {
      set({ projectHydrated: true });
      return;
    }
    // Гонка гидратации: пока шёл fetch, локальный граф мог измениться (пользователь
    // или GraphDev.add в тестах уже добавил ноды) — применять загруженный проект
    // поверх нельзя, он затёр бы локальные правки пустым/устаревшим состоянием.
    if (localDirtySinceInit) {
      set({ projectHydrated: true });
      return;
    }
    const current = get();
    const dbNodeCount = project.pages.reduce((sum, page) => sum + page.nodes.length, 0);
    if (dbNodeCount === 0 && (current.nodes.length > 0 || current.edges.length > 0)) {
      set({ projectHydrated: true });
      return;
    }
    const activePage = project.pages.find((page) => page.id === project.activePageId) || project.pages[0];
    if (!activePage) {
      set({ projectHydrated: true });
      return;
    }
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
      progresses: {},
    });
    // Keep the canvas->store mirror closed for one task after publishing the
    // loaded arrays. Svelte effects may otherwise observe `projectHydrated`
    // before their local bound nodes receive the same snapshot and mirror the
    // temporary empty canvas back over the freshly loaded project.
    setTimeout(() => {
      set({ projectHydrated: true });
      fitFlowView();
      setTimeout(fitFlowView, 350);
    }, 0);
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


// AI-ассист редактора читает registry дизайн-систем отсюда (§16.2)
if (typeof window !== "undefined") (window as unknown as { __flowStore?: unknown }).__flowStore = useFlowStore;
