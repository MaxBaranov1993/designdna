import { defaultData } from "./ports";
import { edgeKindOf, WIRE_COLORS } from "./dataflow";
import { isDesktopBlobUrl, offloadBlobsInPlace } from "../desktop/blobStore";
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
  SourceImportNodeData,
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
  "designui",
  "derive",
  "reskin",
  "qualitypass",
  "recorder",
  "motion",
  "pagebridge",
  "designsystem",
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

function compactReferenceEvidence(value: unknown): unknown {
  if (typeof value === "string") return isDesktopBlobUrl(value) ? value : undefined;
  if (Array.isArray(value)) {
    const compacted = value.map(compactReferenceEvidence).filter((item) => item !== undefined);
    return compacted.length ? compacted : undefined;
  }
  if (value && typeof value === "object") {
    const compacted: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      const kept = compactReferenceEvidence(child);
      if (kept !== undefined) compacted[key] = kept;
    }
    return Object.keys(compacted).length ? compacted : undefined;
  }
  return undefined;
}

/**
 * Browser screenshots are comparison evidence, not inline project state. Source
 * Import repeats them in several places, so raw data URLs are omitted. Desktop
 * content-addressed blob references are tiny, immutable evidence handles and must
 * survive restart; otherwise Design System Compare loses its Source crop.
 */
export function compactForStorage(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(compactForStorage);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(v as Record<string, unknown>)) {
      if (STORAGE_REFERENCE_KEYS.has(key)) {
        const evidence = compactReferenceEvidence(value);
        if (evidence !== undefined) out[key] = evidence;
        continue;
      }
      out[key] = compactForStorage(value);
    }
    return out;
  }
  return v;
}

/* ---------- автосейв: один compact + один stringify, запись в idle-слоте ----------
 *
 * Раньше каждое изменение графа сериализовалось 3-4 раза (две записи в
 * localStorage + POST в SQLite получали несжатый payload с base64-скриншотами)
 * и писало localStorage синхронно в кадре взаимодействия. Теперь:
 *  - compact и stringify выполняются ровно один раз, одну и ту же строку едят
 *    localStorage и POST /api/project/save (скриншоты — evidence, не состояние);
 *  - сама работа уезжает в requestIdleCallback с timeout-капом, чтобы
 *    dragstop/набор текста не платили за сериализацию мегабайтного проекта;
 *  - legacy-ключ designai-flow-v1 больше не пишется (читается только при
 *    миграции старых проектов), pages-ключ содержит всё. */

let projectSaveTimer: ReturnType<typeof setTimeout> | null = null;
let lastProjectProvider: (() => PagesProjectPayload) | null = null;
let idleWriteHandle: number | null = null;
let dbSaveTimer: ReturnType<typeof setTimeout> | null = null;
let lastDbProjectText: string | null = null;
let lsPagesDisabled = false;
/* Ревизия проекта (SHA-256 строки payload) с последнего load/save —
 * заголовок CAS для /api/project/save. */
let lastKnownRevision: string | null = null;

function scheduleIdleWrite(): void {
  if (idleWriteHandle != null) return; // отложенный write возьмёт свежий provider при исполнении
  if (typeof requestIdleCallback === "function") {
    idleWriteHandle = requestIdleCallback(
      () => {
        idleWriteHandle = null;
        if (lastProjectProvider) writeProjectNow(lastProjectProvider);
      },
      { timeout: 1200 },
    );
  } else {
    idleWriteHandle = setTimeout(() => {
      idleWriteHandle = null;
      if (lastProjectProvider) writeProjectNow(lastProjectProvider);
    }) as unknown as number;
  }
}

function cancelIdleWrite(): void {
  if (idleWriteHandle == null) return;
  if (typeof cancelIdleCallback === "function") {
    cancelIdleCallback(idleWriteHandle);
  } else {
    clearTimeout(idleWriteHandle as unknown as ReturnType<typeof setTimeout>);
  }
  idleWriteHandle = null;
}

/** Синхронная запись (путь beforeunload): без offload — страница может
 *  закрыться до завершения асинхронного шага, данные обязаны попасть в LS. */
function writeProjectSync(payload: PagesProjectPayload): void {
  const compact = compactForStorage(payload);
  const text = JSON.stringify(compact);
  lastDbProjectText = text;
  scheduleDbProjectSave();
  if (lsPagesDisabled) return;
  try {
    localStorage.setItem(FLOW_PAGES_LS_KEY, text);
  } catch {
    try {
      localStorage.setItem(FLOW_PAGES_LS_KEY, JSON.stringify(stripHeavy(compact)));
      toast("localStorage переполнен — проект страниц сохранён без тяжёлых данных", "error");
    } catch {
      lsPagesDisabled = true;
      localStorage.removeItem(FLOW_PAGES_LS_KEY);
      toast("localStorage переполнен - проект сохраняется в SQLite.", "error");
    }
  }
}

function writeProjectNow(provider: () => PagesProjectPayload): void {
  // Десктоп: длинные inline data:-URL выносим в blob-store ДО сериализации —
  // LS и SQLite-копия хранят короткие ddna://-ссылки. Offload мутирует живые
  // node.data на месте (img-src грузит блобы по протоколу); при недоступном
  // мосте просто пишем как есть — данные не теряются.
  void (async () => {
    const payload = provider();
    try {
      await offloadBlobsInPlace(payload);
    } catch {
      /* offload — оптимизация, не транзакция */
    }
    writeProjectSync(payload);
  })();
}

function scheduleDbProjectSave(): void {
  if (dbSaveTimer) clearTimeout(dbSaveTimer);
  dbSaveTimer = setTimeout(() => {
    dbSaveTimer = null;
    void flushDbProject();
  }, 250);
}

async function flushDbProject(): Promise<void> {
  const text = lastDbProjectText;
  if (!text) return;
  lastDbProjectText = null;
  try {
    // CAS по ревизии с последнего известного load/save. Конфликт (409 stale)
    // разрешаем одним ретраем с серверной ревизией — живое состояние редактора
    // важнее; повторный конфликт пишет безусловно, как раньше.
    const send = async (expectedRevision: string | null) =>
      fetch("/api/project/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // text — уже валидный JSON; склейка экономит повторный stringify мегабайтного payload
        body: `{"project":${text}${expectedRevision ? `,"expectedRevision":${JSON.stringify(expectedRevision)}` : ""}}`,
      });
    const resp = await send(lastKnownRevision);
    if (resp.status === 409) {
      const conflict = (await resp.clone().json().catch(() => ({}))) as { revision?: string; error?: string };
      // Fail closed: adopting the server revision and retrying would overwrite
      // changes made by another editor. Keep the local compact snapshot for
      // recovery and let the UI offer an explicit reload/merge decision.
      if (lastDbProjectText === null) lastDbProjectText = text;
      window.dispatchEvent(new CustomEvent("designdna:project-conflict", {
        detail: {
          expectedRevision: lastKnownRevision,
          currentRevision: typeof conflict.revision === "string" ? conflict.revision : null,
          error: conflict.error || "stale_revision",
        },
      }));
      return;
    }
    if (resp.ok) {
      const saved = (await resp.json().catch(() => null)) as { revision?: string } | null;
      if (saved?.revision) lastKnownRevision = saved.revision;
    } else if (lastDbProjectText === null) {
      lastDbProjectText = text;
    }
  } catch {
    // localStorage уже содержит актуальный compact; повторит следующий сейв или unload-beacon
    if (lastDbProjectText === null) lastDbProjectText = text;
  }
}

/* Дебаунс 300 мс, затем idle-слот */
export function scheduleProjectSave(provider: () => PagesProjectPayload) {
  lastProjectProvider = provider;
  if (projectSaveTimer) clearTimeout(projectSaveTimer);
  projectSaveTimer = setTimeout(() => {
    projectSaveTimer = null;
    if (lastProjectProvider) scheduleIdleWrite();
  }, 300);
}

/* При закрытии вкладки: дожать незавершённый дебаунс/idle синхронно и
 * отправить ожидающий SQLite-POST через sendBeacon */
window.addEventListener("beforeunload", () => {
  if (projectSaveTimer) {
    clearTimeout(projectSaveTimer);
    projectSaveTimer = null;
  }
  cancelIdleWrite();
  // Синхронный путь: offload не успеет до выгрузки страницы — пишем как есть
  if (lastProjectProvider) writeProjectSync(lastProjectProvider());
  if (dbSaveTimer) {
    clearTimeout(dbSaveTimer);
    dbSaveTimer = null;
  }
  if (lastDbProjectText && navigator.sendBeacon) {
    const expected = lastKnownRevision
      ? `,"expectedRevision":${JSON.stringify(lastKnownRevision)}`
      : "";
    navigator.sendBeacon(
      "/api/project/save",
      new Blob([`{"project":${lastDbProjectText}${expected}}`], { type: "application/json" }),
    );
    lastDbProjectText = null;
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
  return { ...base, style: `stroke: ${WIRE_COLORS[edgeKindOf(nodes, base)]}; stroke-width: 2;` };
}

function dataForStorage(type: NodeType, data: AnyNodeData): AnyNodeData {
  if (type !== "motion") return data;
  const { renderJob: _runtime, ...persistent } = data as AnyNodeData & { renderJob?: unknown };
  return persistent as AnyNodeData;
}

function dataForRuntime(type: NodeType, data: AnyNodeData): AnyNodeData {
  if (type === "motion") return { ...defaultData("motion"), ...data, renderJob: null } as AnyNodeData;
  if (type === "sourceimport") {
    const source = { ...defaultData("sourceimport"), ...data } as SourceImportNodeData;
    // Older saved projects already contain the complete local result but predate
    // importedUrl. Treat those blocks as hydrated instead of reloading the site.
    if (!("importedUrl" in (data as object)) && source.blocks.length > 0) source.importedUrl = source.url;
    return source;
  }
  return data;
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
  designSystems?: { systems: Array<Record<string, unknown>>; defaultSystemRef: { systemId: string; revision: number } | null };
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
    designSystems: (st as any).designSystems || { systems: [], defaultSystemRef: null },
  };
}

/* legacy-payload -> СЃРѕСЃС‚РѕСЏРЅРёРµ RF (СЃС‚СЂРѕРєРѕРІС‹Рµ id вЂ” С‚РѕР»СЊРєРѕ РІ СЂР°РЅС‚Р°Р№РјРµ) */
export function payloadToRf(payload: LegacyGraphPayload): {
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
} {
  let nodes: FlowNode[] = (payload.nodes || []).map(
    (raw) =>
      ({
        id: String(raw.id),
        type: raw.type,
        position: { x: raw.x, y: raw.y },
        // Bootstrap custom-node measurement after hydration; actual dimensions
        // are updated by Svelte Flow's ResizeObserver.
        initialWidth: 260,
        initialHeight: 120,
        data: dataForRuntime(raw.type, raw.data),
      }) as FlowNode,
  );
  let edges = (payload.edges || [])
    .map((e) => makeRfEdge(nodes, e.from, e.to))
    .filter((e) => nodes.some((node) => node.id === e.source) && nodes.some((node) => node.id === e.target));

  // One-way visual migration: Design UI used to be a large pass-through node
  // beside the Design System created from the same Source. Fold only paired
  // nodes; an unpaired legacy inspector remains readable instead of losing data.
  for (const legacyUi of nodes.filter((node) => node.type === "designui")) {
    const incoming = edges.find((edge) => edge.target === legacyUi.id && edge.targetHandle === "artifact");
    if (!incoming) continue;
    const system = nodes.find((node) => node.type === "designsystem"
      && Number((node.data as { sourceNodeId?: unknown }).sourceNodeId) === Number(incoming.source));
    if (!system) continue;

    const outgoing = edges.filter((edge) => edge.source === legacyUi.id && edge.sourceHandle === "artifact");
    nodes = nodes.filter((node) => node.id !== legacyUi.id);
    edges = edges.filter((edge) => edge.source !== legacyUi.id && edge.target !== legacyUi.id);

    if (!edges.some((edge) => edge.source === incoming.source && edge.target === system.id
      && edge.sourceHandle === "artifact" && edge.targetHandle === "artifact")) {
      edges.push(makeRfEdge(nodes,
        { node: Number(incoming.source), port: "artifact" },
        { node: Number(system.id), port: "artifact" }));
    }
    for (const edge of outgoing) {
      if (edge.target === system.id) continue;
      const replacement = makeRfEdge(nodes,
        { node: Number(incoming.source), port: "artifact" },
        { node: Number(edge.target), port: edge.targetHandle || "artifact" });
      if (!edges.some((candidate) => candidate.id === replacement.id)) edges.push(replacement);
    }
  }

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
    // Поддерживаемый выбор провайдера (Sol / Codex / Claude) сохраняется;
    // ретро-провайдеры (kimi/glm/zai/grok/zcode/auto) мигрируют на Sol.
    // Усилие переживает загрузку только если входит в продуктовый контракт.
    if (r.type === "generator" || r.type === "reskin") {
      const savedEffort = String((data as { effort?: unknown }).effort || "");
      const effort = new Set(["medium", "high", "max"]).has(savedEffort) ? savedEffort : "medium";
      const savedProvider = String((data as { provider?: unknown }).provider || "");
      const provider = new Set(["openai", "codex", "claude"]).has(savedProvider) ? savedProvider : "openai";
      data = { ...data, provider, effort } as AnyNodeData;
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

/** Разовая миграция legacy-блоба: проекты, сохранённые до compact-автосейва,
 *  несут мегабайты base64-превью в localStorage. Каждый бут распарсивал такой
 *  блоб целиком (замер: 18 МБ → FCP 3.2 с), поэтому при обнаружении —
 *  перезаписываем скомпакченной версией. Правки/данные не трогаем. */
export function compactLegacyLocalStorage(): void {
  try {
    const raw = localStorage.getItem(FLOW_PAGES_LS_KEY) || "";
    if (raw.length < 400_000) return;
    if (!raw.includes('"preview"') && !raw.includes("data:image/")) return;
    const compacted = JSON.stringify(compactForStorage(JSON.parse(raw)));
    if (compacted.length < raw.length) localStorage.setItem(FLOW_PAGES_LS_KEY, compacted);
  } catch {
    // битый блоб оставляем как есть — load обработает отказ
  }
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
    if (typeof data.revision === "string" && data.revision) lastKnownRevision = data.revision;
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
