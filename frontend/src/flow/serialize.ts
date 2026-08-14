import { defaultData } from "./ports";
import { edgeKindOf, WIRE_COLORS } from "./dataflow";
import { toast } from "./toast";
import type { ProjectLoadResp } from "./api";
import type {
  AnyNodeData,
  FlowEdge,
  FlowNode,
  FlowPage,
  LegacyEdgeEndpoint,
  LegacyEdgePayload,
  LegacyGraphPayload,
  LegacyNodePayload,
  LegacyView,
  NodeType,
  IRObject,
} from "./types";

/* РћРўР”Р•Р›Р¬РќР«Р™ РєР»СЋС‡ СЃРµР№РІР° РЅРѕРІРѕРіРѕ UI: legacy-РіСЂР°С„ (designai-graph-v1) РЅРµ Р·Р°С‚РёСЂР°РµС‚СЃСЏ.
 * Р¤РѕСЂРјР°С‚ payload вЂ” designai-graph-v1 (С‚Рµ Р¶Рµ РёРјРµРЅР° РїРѕР»РµР№, number-id, РІР»РѕР¶РµРЅРЅС‹Рµ from/to). */
export const FLOW_LS_KEY = "designai-flow-v1";
export const FLOW_PAGES_LS_KEY = "designai-flow-pages-v1";

export const DEFAULT_VIEW: LegacyView = { x: 80, y: 40, zoom: 1 };

export const NODE_TYPES: NodeType[] = [
  "prompt",
  "reference",
  "generator",
  "edit",
  "mix",
  "page",
  "sourceimport",
  "styledna",
  "derive",
  "reskin",
  "qualitypass",
  "recorder",
  "motion",
  "pagebridge",
];

/* Р—РµСЂРєР°Р»Рѕ stripHeavy (nodes.js:1161-1172): РїСЂРё РєРІРѕС‚Рµ РІС‹РєРёРґС‹РІР°РµРј base64/data-URL
 * СЃС‚СЂРѕРєРё Рё СЃС‚СЂРѕРєРё >200 РљР‘, РѕСЃС‚Р°Р»СЊРЅРѕР№ РіСЂР°С„ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ */
export function stripHeavy(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stripHeavy);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (typeof val === "string" && (val.startsWith("data:") || val.length > 200000)) continue;
      out[k] = stripHeavy(val);
    }
    return out;
  }
  return v;
}

const STORAGE_REFERENCE_KEYS = new Set(["sourcePreview", "preview", "previews"]);

/**
 * Browser screenshots are comparison evidence, not project state. Source Import
 * repeats them in block metadata, responsive viewport metadata and connected IR,
 * so persisting them can multiply one capture into many megabytes. Keep editable
 * image `src` values and all structure/layout data intact.
 */
export function compactForStorage(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(compactForStorage);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(v as Record<string, unknown>)) {
      if (STORAGE_REFERENCE_KEYS.has(key)) continue;
      out[key] = compactForStorage(value);
    }
    return out;
  }
  return v;
}

/* ---------- Р°РІС‚РѕСЃРµР№РІ (Р·РµСЂРєР°Р»Рѕ save(), nodes.js:1174-1196) ---------- */

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let lastProvider: (() => LegacyGraphPayload) | null = null;
let lastSaveOk = true;
let lsGraphDisabled = false;

function writeGraph(payload: LegacyGraphPayload) {
  if (lsGraphDisabled) return;
  const compact = compactForStorage(payload);
  try {
    localStorage.setItem(FLOW_LS_KEY, JSON.stringify(compact));
    lastSaveOk = true;
  } catch {
    try {
      localStorage.setItem(FLOW_LS_KEY, JSON.stringify(stripHeavy(compact)));
      lastSaveOk = true;
      toast("localStorage РїРµСЂРµРїРѕР»РЅРµРЅ вЂ” СЃРѕС…СЂР°РЅРёР» Р±РµР· СЃРєСЂРёРЅС€РѕС‚РѕРІ", "error");
    } catch {
      lsGraphDisabled = true;
      localStorage.removeItem(FLOW_LS_KEY);
      lastSaveOk = true;
      return;
    }
  }
}

/* Р”РµР±Р°СѓРЅСЃ 300 РјСЃ вЂ” РєР°Рє nodes.js:1175-1176 */
export function scheduleSave(provider: () => LegacyGraphPayload) {
  lastProvider = provider;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (lastProvider) writeGraph(lastProvider());
  }, 300);
}

/* РџСЂРё Р·Р°РєСЂС‹С‚РёРё РІРєР»Р°РґРєРё: РґРѕР¶Р°С‚СЊ РЅРµР·Р°РІРµСЂС€С‘РЅРЅС‹Р№ РґРµР±Р°СѓРЅСЃ; С„Р»Р°С€, РµСЃР»Рё Р·Р°РїРёСЃСЊ РЅРµ СѓРґР°Р»Р°СЃСЊ
 * (Р·РµСЂРєР°Р»Рѕ nodes.js:1198-1200) */
window.addEventListener("beforeunload", (e) => {
  if (saveTimer && lastProvider) {
    clearTimeout(saveTimer);
    saveTimer = null;
    writeGraph(lastProvider());
  }
  if (projectSaveTimer && lastProjectProvider) {
    clearTimeout(projectSaveTimer);
    projectSaveTimer = null;
    writeProject(lastProjectProvider());
  }
  if (dbSaveTimer && lastDbProject) {
    clearTimeout(dbSaveTimer);
    dbSaveTimer = null;
    const body = JSON.stringify({ project: lastDbProject });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/project/save", new Blob([body], { type: "application/json" }));
    } else {
      void saveProjectToDb(lastDbProject);
    }
  }
  if (!lastSaveOk) {
    e.preventDefault();
    e.returnValue = "";
  }
});

/* ---------- РєРѕРЅРІРµСЂС‚Р°С†РёСЏ legacy <-> RF ---------- */

export function makeRfEdge(
  nodes: FlowNode[],
  from: LegacyEdgeEndpoint,
  to: LegacyEdgeEndpoint,
): FlowEdge {
  const base = {
    id: `e${from.node}:${from.port}-${to.node}:${to.port}`,
    source: String(from.node),
    sourceHandle: from.port,
    target: String(to.node),
    targetHandle: to.port,
  };
  return { ...base, style: { stroke: WIRE_COLORS[edgeKindOf(nodes, base)], strokeWidth: 2 } };
}

function dataForStorage(type: NodeType, data: AnyNodeData): AnyNodeData {
  if (type !== "motion") return data;
  const { renderJob: _runtime, ...persistent } = data as AnyNodeData & { renderJob?: unknown };
  return persistent as AnyNodeData;
}

function dataForRuntime(type: NodeType, data: AnyNodeData): AnyNodeData {
  if (type !== "motion") return data;
  return { ...defaultData("motion"), ...data, renderJob: null } as AnyNodeData;
}

function legacyNodes(nodes: FlowNode[]): LegacyNodePayload[] {
  return nodes.map((n) => ({
    id: Number(n.id),
    type: n.type as NodeType,
    x: Math.round(n.position.x),
    y: Math.round(n.position.y),
    data: dataForStorage(n.type as NodeType, n.data as AnyNodeData),
  }));
}

function legacyEdges(edges: FlowEdge[]): LegacyEdgePayload[] {
  return edges.map((e) => ({
    from: { node: Number(e.source), port: e.sourceHandle ?? "" },
    to: { node: Number(e.target), port: e.targetHandle ?? "" },
  }));
}

/* РЎРµР№РІ: {nodes, edges, view, nextId} вЂ” С‚РѕС‡РЅС‹Р№ payload legacy (nodes.js:1177-1180) */
export function buildSavePayload(st: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
}): LegacyGraphPayload {
  return { nodes: legacyNodes(st.nodes), edges: legacyEdges(st.edges), view: st.view, nextId: st.nextId };
}

/* Р­РєСЃРїРѕСЂС‚: С‚РѕС‚ Р¶Рµ С„РѕСЂРјР°С‚, РЅРѕ Р±РµР· nextId (nodes.js:1238-1249) */
export function buildExportPayload(st: { nodes: FlowNode[]; edges: FlowEdge[]; view: LegacyView }) {
  return { nodes: legacyNodes(st.nodes), edges: legacyEdges(st.edges), view: st.view };
}

export type PagesProjectPayload = {
  version: "designai-pages-v1";
  activePageId: string;
  pages: {
    id: string;
    name: string;
    graph: LegacyGraphPayload;
  }[];
  channels?: Record<string, IRObject | null>;
};

export function buildPagesProjectPayload(st: {
  activePageId: string;
  pages: { id: string; name: string; nodes: FlowNode[]; edges: FlowEdge[]; view: LegacyView; nextId: number }[];
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
  channels: Record<string, IRObject | null>;
}): PagesProjectPayload {
  return {
    version: "designai-pages-v1",
    activePageId: st.activePageId,
    pages: st.pages.map((page) => {
      const graph =
        page.id === st.activePageId
          ? buildSavePayload(st)
          : buildSavePayload({
              nodes: page.nodes,
              edges: page.edges,
              view: page.view,
              nextId: page.nextId,
            });
      return { id: page.id, name: page.name, graph };
    }),
    channels: st.channels,
  };
}

let projectSaveTimer: ReturnType<typeof setTimeout> | null = null;
let lastProjectProvider: (() => PagesProjectPayload) | null = null;
let dbSaveTimer: ReturnType<typeof setTimeout> | null = null;
let lastDbProject: PagesProjectPayload | null = null;
let lsPagesDisabled = false;

function writeProject(payload: PagesProjectPayload) {
  lastDbProject = payload;
  scheduleDbProjectSave(lastDbProject);
  if (lsPagesDisabled) return;
  const compact = compactForStorage(payload);
  try {
    localStorage.setItem(FLOW_PAGES_LS_KEY, JSON.stringify(compact));
  } catch {
    try {
      localStorage.setItem(FLOW_PAGES_LS_KEY, JSON.stringify(stripHeavy(compact)));
      toast("localStorage РїРµСЂРµРїРѕР»РЅРµРЅ вЂ” РїСЂРѕРµРєС‚ СЃС‚СЂР°РЅРёС† СЃРѕС…СЂР°РЅС‘РЅ Р±РµР· С‚СЏР¶С‘Р»С‹С… РґР°РЅРЅС‹С…", "error");
    } catch {
      lsPagesDisabled = true;
      localStorage.removeItem(FLOW_PAGES_LS_KEY);
      toast("localStorage переполнен - проект сохраняется в SQLite.", "error");
    }
  }
}

function scheduleDbProjectSave(payload: PagesProjectPayload) {
  if (dbSaveTimer) clearTimeout(dbSaveTimer);
  dbSaveTimer = setTimeout(() => {
    dbSaveTimer = null;
    void saveProjectToDb(payload);
  }, 250);
}

async function saveProjectToDb(payload: PagesProjectPayload) {
  try {
    await fetch("/api/project/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: payload }),
    });
  } catch {
    // Local cache already contains the latest compact payload; the next edit will retry DB save.
  }
}

export function scheduleProjectSave(provider: () => PagesProjectPayload) {
  lastProjectProvider = provider;
  if (projectSaveTimer) clearTimeout(projectSaveTimer);
  projectSaveTimer = setTimeout(() => {
    projectSaveTimer = null;
    if (lastProjectProvider) writeProject(lastProjectProvider());
  }, 300);
}

/* legacy-payload -> СЃРѕСЃС‚РѕСЏРЅРёРµ RF (СЃС‚СЂРѕРєРѕРІС‹Рµ id вЂ” С‚РѕР»СЊРєРѕ РІ СЂР°РЅС‚Р°Р№РјРµ) */
export function payloadToRf(payload: LegacyGraphPayload): {
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
} {
  const nodes: FlowNode[] = (payload.nodes || []).map(
    (raw) =>
      ({
        id: String(raw.id),
        type: raw.type,
        position: { x: raw.x, y: raw.y },
        data: dataForRuntime(raw.type, raw.data),
      }) as FlowNode,
  );
  const ids = new Set(nodes.map((n) => n.id));
  const edges = (payload.edges || [])
    .map((e) => makeRfEdge(nodes, e.from, e.to))
    .filter((e) => ids.has(e.source) && ids.has(e.target));
  const maxId = nodes.reduce((m, n) => Math.max(m, Number(n.id) || 0), 0);
  return {
    nodes,
    edges,
    view: payload.view || { ...DEFAULT_VIEW },
    // nextId РїРµСЂРµСЃС‡РёС‚С‹РІР°РµС‚СЃСЏ РєР°Рє max(nextId, max(id)+1) вЂ” Р·РµСЂРєР°Р»Рѕ nodes.js:1214
    nextId: Math.max(payload.nextId || 1, maxId + 1),
  };
}

/* Р Р°Р·Р±РѕСЂ РІС…РѕРґСЏС‰РµРіРѕ JSON (localStorage РёР»Рё РёРјРїРѕСЂС‚ legacy-С„РѕСЂРјР°С‚Р°).
 * id number<->string РєРѕРЅРІРµСЂС‚РёСЂСѓСЋС‚СЃСЏ Р·РґРµСЃСЊ, РІ СЂР°РЅС‚Р°Р№РјРµ. Р‘СЂРѕСЃР°РµС‚ Error РїСЂРё РЅРµРІР°Р»РёРґРЅРѕРј С„РѕСЂРјР°С‚Рµ. */
export function parseLegacyPayload(input: unknown): LegacyGraphPayload {
  if (!input || typeof input !== "object") throw new Error("РѕР¶РёРґР°Р»СЃСЏ РѕР±СЉРµРєС‚ РіСЂР°С„Р°");
  const raw = input as Record<string, unknown>;
  if (raw.nodes != null && !Array.isArray(raw.nodes)) throw new Error("nodes РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РјР°СЃСЃРёРІРѕРј");
  if (raw.edges != null && !Array.isArray(raw.edges)) throw new Error("edges РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РјР°СЃСЃРёРІРѕРј");

  const known = new Set<string>(NODE_TYPES);
  let autoId = 1;
  const nodes: LegacyNodePayload[] = [];
  for (const rn of (raw.nodes as unknown[]) || []) {
    if (!rn || typeof rn !== "object") continue;
    const r = rn as Record<string, unknown>;
    if (typeof r.type !== "string" || !known.has(r.type)) continue; // РЅРµРёР·РІРµСЃС‚РЅС‹Р№ С‚РёРї РїСЂРѕРїСѓСЃРєР°РµРј
    let id = Number(r.id);
    if (!Number.isFinite(id) || id <= 0) id = autoId; // Р±РёС‚С‹Р№/СЃС‚СЂРѕРєРѕРІС‹Р№ id в†’ С‡РёСЃР»РѕРІРѕР№
    autoId = Math.max(autoId, id) + 1;
    let data =
      r.data && typeof r.data === "object" ? (r.data as AnyNodeData) : defaultData(r.type as NodeType);
    // Старые графы могли хранить vendor-specific model values.
    // Legacy provider values are normalized to the single user-owned Codex route.
    if (r.type === "generator") {
      data = { ...data, provider: "codex" } as AnyNodeData;
    }
    data = dataForRuntime(r.type as NodeType, data);
    nodes.push({ id, type: r.type as NodeType, x: Number(r.x) || 0, y: Number(r.y) || 0, data });
  }

  const ids = new Set(nodes.map((n) => n.id));
  const edges: LegacyEdgePayload[] = [];
  for (const re of (raw.edges as unknown[]) || []) {
    if (!re || typeof re !== "object") continue;
    const r = re as Record<string, unknown>;
    const from = r.from as Record<string, unknown> | undefined;
    const to = r.to as Record<string, unknown> | undefined;
    if (!from || !to) continue;
    const fn = Number(from.node);
    const tn = Number(to.node);
    if (!ids.has(fn) || !ids.has(tn) || typeof from.port !== "string" || typeof to.port !== "string")
      continue;
    edges.push({ from: { node: fn, port: from.port }, to: { node: tn, port: to.port } });
  }

  const rv = raw.view as Record<string, unknown> | undefined;
  const view: LegacyView =
    rv && typeof rv === "object"
      ? {
          x: Number.isFinite(Number(rv.x)) ? Number(rv.x) : DEFAULT_VIEW.x,
          y: Number.isFinite(Number(rv.y)) ? Number(rv.y) : DEFAULT_VIEW.y,
          zoom: Number.isFinite(Number(rv.zoom)) && Number(rv.zoom) > 0 ? Number(rv.zoom) : 1,
        }
      : { ...DEFAULT_VIEW };

  const nextIdRaw = Number(raw.nextId);
  return {
    nodes,
    edges,
    view,
    nextId: Number.isFinite(nextIdRaw) && nextIdRaw > 0 ? nextIdRaw : undefined,
  };
}

/* Р§С‚РµРЅРёРµ СЃРµР№РІР°: Р±РёС‚С‹Р№ JSON РјРѕР»С‡Р° РёРіРЅРѕСЂРёСЂСѓРµС‚СЃСЏ (РїСѓСЃС‚РѕР№ РіСЂР°С„) вЂ” Р·РµСЂРєР°Р»Рѕ nodes.js:1221-1227 */
export function loadFromStorage(): LegacyGraphPayload | null {
  try {
    const rawStr = localStorage.getItem(FLOW_LS_KEY);
    if (!rawStr) return null;
    return parseLegacyPayload(JSON.parse(rawStr));
  } catch {
    return null;
  }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return Boolean(v && typeof v === "object" && !Array.isArray(v));
}

export function parsePagesPayload(input: unknown): {
  activePageId: string;
  pages: FlowPage[];
  channels: Record<string, IRObject | null>;
} | null {
  if (!isObject(input) || input.version !== "designai-pages-v1" || !Array.isArray(input.pages)) return null;
  const pages: FlowPage[] = [];
  for (const rawPage of input.pages) {
    if (!isObject(rawPage)) continue;
    const id = typeof rawPage.id === "string" && rawPage.id.trim() ? rawPage.id : `page-${pages.length + 1}`;
    const name = typeof rawPage.name === "string" && rawPage.name.trim() ? rawPage.name.trim() : `Page ${pages.length + 1}`;
    try {
      const graph = payloadToRf(parseLegacyPayload(rawPage.graph));
      pages.push({ id, name, ...graph });
    } catch {
      // broken page payloads are ignored so one damaged page does not kill the project
    }
  }
  if (!pages.length) return null;
  const channelsRaw = isObject(input.channels) ? input.channels : {};
  const channels: Record<string, IRObject | null> = {};
  for (const [key, value] of Object.entries(channelsRaw)) {
    if (typeof key === "string" && (value === null || isObject(value))) channels[key] = value as IRObject | null;
  }
  const activeRaw = typeof input.activePageId === "string" ? input.activePageId : "";
  const activePageId = pages.some((page) => page.id === activeRaw) ? activeRaw : pages[0].id;
  return { activePageId, pages, channels };
}

export function loadPagesProjectFromStorage(): {
  activePageId: string;
  pages: FlowPage[];
  channels: Record<string, IRObject | null>;
} | null {
  try {
    const rawStr = localStorage.getItem(FLOW_PAGES_LS_KEY);
    if (!rawStr) return null;
    return parsePagesPayload(JSON.parse(rawStr));
  } catch {
    return null;
  }
}

export async function loadPagesProjectFromDb(): Promise<{
  activePageId: string;
  pages: FlowPage[];
  channels: Record<string, IRObject | null>;
} | null> {
  try {
    const resp = await fetch("/api/project/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!resp.ok) return null;
    const data = (await resp.json()) as ProjectLoadResp;
    if (!data.project) return null;
    return parsePagesPayload(data.project);
  } catch {
    return null;
  }
}

/* РЎРєР°С‡РёРІР°РЅРёРµ JSON вЂ” Р·РµСЂРєР°Р»Рѕ СЌРєСЃРїРѕСЂС‚Р° (nodes.js:1243-1248) */
export function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
