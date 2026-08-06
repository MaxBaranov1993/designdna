import { defaultData } from "./ports";
import { edgeKindOf, WIRE_COLORS } from "./dataflow";
import { toast } from "./toast";
import type {
  AnyNodeData,
  FlowEdge,
  FlowNode,
  LegacyEdgeEndpoint,
  LegacyEdgePayload,
  LegacyGraphPayload,
  LegacyNodePayload,
  LegacyView,
  NodeType,
} from "./types";

/* ОТДЕЛЬНЫЙ ключ сейва нового UI: legacy-граф (designai-graph-v1) не затирается.
 * Формат payload — designai-graph-v1 (те же имена полей, number-id, вложенные from/to). */
export const FLOW_LS_KEY = "designai-flow-v1";

export const DEFAULT_VIEW: LegacyView = { x: 80, y: 40, zoom: 1 };

export const NODE_TYPES: NodeType[] = [
  "prompt",
  "reference",
  "generator",
  "edit",
  "mix",
  "clone",
  "reproduce",
  "blockparse",
  "reskin",
];

/* Зеркало stripHeavy (nodes.js:1161-1172): при квоте выкидываем base64/data-URL
 * строки и строки >200 КБ, остальной граф сохраняется */
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

/* ---------- автосейв (зеркало save(), nodes.js:1174-1196) ---------- */

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let lastProvider: (() => LegacyGraphPayload) | null = null;
let lastSaveOk = true;

function writeGraph(payload: LegacyGraphPayload) {
  try {
    localStorage.setItem(FLOW_LS_KEY, JSON.stringify(payload));
    lastSaveOk = true;
  } catch {
    try {
      localStorage.setItem(FLOW_LS_KEY, JSON.stringify(stripHeavy(payload)));
      lastSaveOk = true;
      toast("localStorage переполнен — сохранил без скриншотов", "error");
    } catch {
      lastSaveOk = false;
      toast("Не удалось сохранить граф (localStorage переполнен). Экспортируйте в файл.", "error");
    }
  }
}

/* Дебаунс 300 мс — как nodes.js:1175-1176 */
export function scheduleSave(provider: () => LegacyGraphPayload) {
  lastProvider = provider;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (lastProvider) writeGraph(lastProvider());
  }, 300);
}

/* При закрытии вкладки: дожать незавершённый дебаунс; флаш, если запись не удалась
 * (зеркало nodes.js:1198-1200) */
window.addEventListener("beforeunload", (e) => {
  if (saveTimer && lastProvider) {
    clearTimeout(saveTimer);
    saveTimer = null;
    writeGraph(lastProvider());
  }
  if (!lastSaveOk) {
    e.preventDefault();
    e.returnValue = "";
  }
});

/* ---------- конвертация legacy <-> RF ---------- */

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

function legacyNodes(nodes: FlowNode[]): LegacyNodePayload[] {
  return nodes.map((n) => ({
    id: Number(n.id),
    type: n.type as NodeType,
    x: Math.round(n.position.x),
    y: Math.round(n.position.y),
    data: n.data as AnyNodeData,
  }));
}

function legacyEdges(edges: FlowEdge[]): LegacyEdgePayload[] {
  return edges.map((e) => ({
    from: { node: Number(e.source), port: e.sourceHandle ?? "" },
    to: { node: Number(e.target), port: e.targetHandle ?? "" },
  }));
}

/* Сейв: {nodes, edges, view, nextId} — точный payload legacy (nodes.js:1177-1180) */
export function buildSavePayload(st: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
}): LegacyGraphPayload {
  return { nodes: legacyNodes(st.nodes), edges: legacyEdges(st.edges), view: st.view, nextId: st.nextId };
}

/* Экспорт: тот же формат, но без nextId (nodes.js:1238-1249) */
export function buildExportPayload(st: { nodes: FlowNode[]; edges: FlowEdge[]; view: LegacyView }) {
  return { nodes: legacyNodes(st.nodes), edges: legacyEdges(st.edges), view: st.view };
}

/* legacy-payload -> состояние RF (строковые id — только в рантайме, FLOW-MIGRATION.md §2.3) */
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
        data: raw.data,
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
    // nextId пересчитывается как max(nextId, max(id)+1) — зеркало nodes.js:1214
    nextId: Math.max(payload.nextId || 1, maxId + 1),
  };
}

/* Разбор входящего JSON (localStorage или импорт legacy-формата).
 * id number<->string конвертируются здесь, в рантайме. Бросает Error при невалидном формате. */
export function parseLegacyPayload(input: unknown): LegacyGraphPayload {
  if (!input || typeof input !== "object") throw new Error("ожидался объект графа");
  const raw = input as Record<string, unknown>;
  if (raw.nodes != null && !Array.isArray(raw.nodes)) throw new Error("nodes должен быть массивом");
  if (raw.edges != null && !Array.isArray(raw.edges)) throw new Error("edges должен быть массивом");

  const known = new Set<string>(NODE_TYPES);
  let autoId = 1;
  const nodes: LegacyNodePayload[] = [];
  for (const rn of (raw.nodes as unknown[]) || []) {
    if (!rn || typeof rn !== "object") continue;
    const r = rn as Record<string, unknown>;
    if (typeof r.type !== "string" || !known.has(r.type)) continue; // неизвестный тип пропускаем
    let id = Number(r.id);
    if (!Number.isFinite(id) || id <= 0) id = autoId; // битый/строковый id → числовой
    autoId = Math.max(autoId, id) + 1;
    const data =
      r.data && typeof r.data === "object" ? (r.data as AnyNodeData) : defaultData(r.type as NodeType);
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

/* Чтение сейва: битый JSON молча игнорируется (пустой граф) — зеркало nodes.js:1221-1227 */
export function loadFromStorage(): LegacyGraphPayload | null {
  try {
    const rawStr = localStorage.getItem(FLOW_LS_KEY);
    if (!rawStr) return null;
    return parseLegacyPayload(JSON.parse(rawStr));
  } catch {
    return null;
  }
}

/* Скачивание JSON — зеркало экспорта (nodes.js:1243-1248) */
export function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
