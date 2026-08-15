/* DNA Editor — контроллер сессии: оркестрирует TS-движки (engine/renderer,
 * engine/geoedit, engine/irhistory) и React-каркас панелей. Селекторы и
 * семантика undo — контракт UI-тестов. */
import type { GeoHandle, GeoRef, GeoSel, IRHistoryHandle } from "./globals";
import { IRRenderer } from "../engine/renderer";
import { GeoEdit } from "../engine/geoedit";
import { IRHistory } from "../engine/irhistory";
import { DesignAIFontCatalog } from "../engine/fontCatalog";

/* ---------- DOM-refs: регистрируются React-компонентами ---------- */

export const dom = {
  overlay: null as HTMLDivElement | null,
  zoomLabel: null as HTMLSpanElement | null,
  viewports: null as HTMLSpanElement | null,
  responsiveSep: null as HTMLSpanElement | null,
  viewportWidth: null as HTMLInputElement | null,
  alignGroup: null as HTMLSpanElement | null,
  undoBtn: null as HTMLButtonElement | null,
  redoBtn: null as HTMLButtonElement | null,
  canvas: null as HTMLDivElement | null,
  canvasInner: null as HTMLDivElement | null,
  rulerH: null as HTMLCanvasElement | null,
  rulerV: null as HTMLCanvasElement | null,
  layersTree: null as HTMLDivElement | null,
  search: null as HTMLInputElement | null,
  dnaPanel: null as HTMLDivElement | null,
  dnaBody: null as HTMLDivElement | null,
  dnaFoot: null as HTMLDivElement | null,
  dnaMode: null as HTMLSpanElement | null,
};

/* ---------- сессия редактора (зеркало state в editor.js) ---------- */

export type NodeShim = { data: { ir: any } };

interface Session {
  ir: any;
  node: NodeShim;
  onSave: ((ir: any) => void) | null;
  onClose: ((saved: boolean) => void) | null;
  geo: GeoHandle | null;
  history: IRHistoryHandle;
  sel: GeoSel[];
  zoom: number;
  panX: number;
  panY: number;
  tool: string;
  viewport: string;
  previewWidth: number;
  activeIR: any;
  layerFlags: Record<string, { hidden?: boolean; locked?: boolean }>;
  layerQuery: string;
  dragLayerKey?: string | null;
  sourceContext: {
    registry: Record<string, { id: string; label: string; kind?: string; symbol?: string; confidence?: number }>;
    nodeSources: Record<string, string>;
    lensEnabled: boolean;
    activeSourceIds: Set<string>;
  };
}

let state: Session | null = null;
let dnaPanelState: {
  tokens: any;
  originalTokens: any;
  normalization?: any;
  tailwindText?: string;
} | null = null;

/* UI-хуки подключает store (чтобы не было циклического импорта) */
let ui: { setTool: (t: string) => void; setOpen: (v: boolean) => void; bumpInspector: () => void; bumpSources: () => void } = {
  setTool: () => {},
  setOpen: () => {},
  bumpInspector: () => {},
  bumpSources: () => {},
};
export function bindUi(hooks: typeof ui) {
  ui = hooks;
}

export function isActive() {
  return !!state;
}

const SOURCE_COLORS = ["#4F7CFF", "#F97316", "#10B981", "#A855F7", "#EC4899", "#06B6D4", "#EAB308", "#EF4444"];

function sourceColor(sourceId: string): string {
  if (!state) return SOURCE_COLORS[0];
  const ids = Object.keys(state.sourceContext.registry).sort();
  const index = Math.max(0, ids.indexOf(sourceId));
  return SOURCE_COLORS[index % SOURCE_COLORS.length];
}

function sourceIdForNode(node: any): string | null {
  if (!state || !node || typeof node !== "object") return null;
  const ref = node.sourceKey || node.id;
  return ref ? state.sourceContext.nodeSources[ref] || null : null;
}

export function sourceForRef(ref: GeoRef | null) {
  if (!state || !ref) return null;
  const node = canonicalNode(ref);
  let sourceId = sourceIdForNode(node);
  if (!sourceId && ref.secIdx != null) sourceId = sourceIdForNode((state.ir.tree || [])[ref.secIdx]);
  const record = sourceId ? state.sourceContext.registry[sourceId] : null;
  return record && sourceId ? { ...record, id: sourceId, color: sourceColor(sourceId) } : null;
}

export function sourceForSelection() {
  return state?.sel.length ? sourceForRef(state.sel[0].ref) : null;
}

export function getSourceLensView() {
  if (!state) return { enabled: false, sources: [] as any[] };
  const counts: Record<string, number> = {};
  Object.values(state.sourceContext.nodeSources).forEach((id) => { counts[id] = (counts[id] || 0) + 1; });
  const allVisible = state.sourceContext.activeSourceIds.size === 0;
  return {
    enabled: state.sourceContext.lensEnabled,
    sources: Object.values(state.sourceContext.registry)
      .sort((a, b) => a.label.localeCompare(b.label))
      .map((source) => ({
        ...source,
        color: sourceColor(source.id),
        count: counts[source.id] || 0,
        active: allVisible || state!.sourceContext.activeSourceIds.has(source.id),
      })),
  };
}

export function toggleSourceLens() {
  if (!state) return;
  state.sourceContext.lensEnabled = !state.sourceContext.lensEnabled;
  applySourceLens();
  ui.bumpSources();
}

export function toggleSourceFilter(sourceId: string) {
  if (!state || !state.sourceContext.registry[sourceId]) return;
  const active = state.sourceContext.activeSourceIds;
  if (active.has(sourceId)) active.delete(sourceId); else active.add(sourceId);
  if (active.size === Object.keys(state.sourceContext.registry).length) active.clear();
  applySourceLens();
  ui.bumpSources();
}

function applySourceLens() {
  if (!state || !dom.canvasInner) return;
  const inner = dom.canvasInner;
  inner.querySelectorAll<HTMLElement>(".source-lens-section,.source-lens-selected,.source-lens-dim").forEach((element) => {
    element.classList.remove("source-lens-section", "source-lens-selected", "source-lens-dim");
    element.style.removeProperty("--source-color");
    delete element.dataset.sourceLabel;
    delete element.dataset.sourceSymbol;
  });
  if (!state.sourceContext.lensEnabled) return;
  const active = state.sourceContext.activeSourceIds;
  (state.ir.tree || []).forEach((section: any, index: number) => {
    const sourceId = sourceIdForNode(section);
    const record = sourceId ? state!.sourceContext.registry[sourceId] : null;
    const element = domAtCanvas({ secIdx: index, path: null });
    if (!element || !sourceId || !record) return;
    element.classList.add("source-lens-section");
    if (active.size && !active.has(sourceId)) element.classList.add("source-lens-dim");
    element.style.setProperty("--source-color", sourceColor(sourceId));
    element.dataset.sourceLabel = record.label;
    element.dataset.sourceSymbol = record.symbol || "S";
  });
  state.sel.forEach((selection) => {
    const source = sourceForRef(selection.ref);
    const element = domAtCanvas(selection.ref);
    if (!source || !element) return;
    element.classList.add("source-lens-selected");
    element.style.setProperty("--source-color", source.color);
    element.dataset.sourceLabel = source.label;
    element.dataset.sourceSymbol = source.symbol || "S";
  });
}

function getByPath(obj: any, path: string) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

const FONT_CATALOG = DesignAIFontCatalog;
const FONT_FAMILIES = FONT_CATALOG
  ? FONT_CATALOG.families
  : ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];

function fontOptionsHtml(selected?: string, autoLabel?: string | null) {
  const auto = autoLabel == null ? "" : `<option value="">${autoLabel}</option>`;
  if (!FONT_CATALOG || !FONT_CATALOG.groups) {
    return auto + FONT_FAMILIES.map((ff) => `<option value="${ff}" ${ff === selected ? "selected" : ""}>${ff}</option>`).join("");
  }
  return auto + FONT_CATALOG.groups
    .map((group) =>
      `<optgroup label="${esc(group.label)}">${group.fonts
        .map((ff) => `<option value="${ff}" ${ff === selected ? "selected" : ""}>${ff}</option>`)
        .join("")}</optgroup>`,
    )
    .join("");
}


/* ---------- тулбар / инструменты ---------- */

/* Инструменты, которые geoedit уже умеет; ellipse/line/image добавляются в движок
 * параллельно — rail зовёт setTool всегда, а при отказе движка откатываемся на select. */
export function setTool(tool: string) {
  if (!state) return;
  state.tool = tool;
  ui.setTool(tool);
  if (dom.canvas) dom.canvas.style.cursor = tool === "hand" ? "grab" : "default";
  // синхронизируем geoedit: создание rect/text/frame и hand-панорама
  if (state.geo && state.geo.getTool() !== tool) {
    try {
      state.geo.setTool(tool);
      if (state.geo.getTool() !== tool) throw new Error("engine rejected tool");
    } catch {
      console.warn(`GeoEdit: инструмент "${tool}" пока не поддержан движком — откат на select`);
      state.tool = "select";
      ui.setTool("select");
      try {
        state.geo.setTool("select");
      } catch {
        /* движок недоступен — игнорируем */
      }
      if (dom.canvas) dom.canvas.style.cursor = "default";
    }
  }
}

export function setViewport(viewport: string) {
  if (!state || !["desktop", "tablet", "mobile"].includes(viewport)) return;
  const widths: Record<string, number> = { desktop: 1440, tablet: 768, mobile: 390 };
  activateViewport(viewport, widths[viewport]);
}

function viewportForWidth(width: number) {
  return width < 640 ? "mobile" : width < 1024 ? "tablet" : "desktop";
}

export function setPreviewWidth(value: string | number) {
  if (!state) return;
  const width = Math.max(320, Math.min(2560, Math.round(Number(value) || 1440)));
  activateViewport(viewportForWidth(width), width);
}

function activateViewport(viewport: string, width: number) {
  if (!state) return;
  if (state.activeIR) syncActiveIR();
  state.viewport = viewport;
  state.previewWidth = width;
  // прокидываем выбранное устройство в канонический IR: превью ноды и downstream
  // (Page → провода) показывают тот же вьюпорт, что редактировали последним
  if (state.ir && state.ir.responsive) {
    state.ir.meta = state.ir.meta || {};
    state.ir.meta.activeViewport = viewport;
  }
  dom.viewports?.querySelectorAll("[data-viewport]").forEach((b) => {
    b.classList.toggle("active", (b as HTMLElement).dataset.viewport === viewport);
  });
  if (dom.viewportWidth) dom.viewportWidth.value = String(width);
  state.sel = [];
  renderCanvas();
  renderLayers();
  renderInspector();
  zoomFit();
}

export function handleAct(act: string) {
  if (!state) return;
  if (act === "save") save();
  else if (act === "close") close();
  else if (act === "undo") undo();
  else if (act === "redo") redo();
  else if (act === "style-dna") openStyleDnaInspector();
  else if (act === "close-style-dna") closeStyleDnaInspector();
  else if (act === "reset-style-dna") resetStyleDnaInspector();
  else if (act === "apply-style-dna") void applyStyleDnaFromInspector();
  else if (act === "zoom-in") zoomBy(1.2);
  else if (act === "zoom-out") zoomBy(1 / 1.2);
  else if (act === "zoom-fit") zoomFit();
  else if (act.startsWith("align-") || act.startsWith("distribute-")) {
    if (!state.geo) return;
    const map: Record<string, keyof GeoHandle> = {
      "align-left": "alignLeft", "align-center-h": "alignCenterH", "align-right": "alignRight",
      "align-top": "alignTop", "align-center-v": "alignCenterV", "align-bottom": "alignBottom",
      "distribute-h": "distributeH", "distribute-v": "distributeV",
    };
    const fn = map[act];
    const geo = state.geo;
    if (fn && typeof geo[fn] === "function") (geo[fn] as () => void)();
  } else if (act === "forward") state.geo && state.geo.bringForward();
  else if (act === "backward") state.geo && state.geo.sendBackward();
  else if (act === "group") state.geo && state.geo.groupSelection();
  else if (act === "ungroup") state.geo && state.geo.ungroupSelection();
}

/* ---------- открытие / закрытие ---------- */

/** Фаза 1 открытия: состояние + не-layout части (вызывается из store.openEditor). */
export function open(
  node: NodeShim,
  onSave: (ir: any) => void,
  onClose: (saved: boolean) => void,
  sourceContext?: { registry?: Record<string, any>; nodeSources?: Record<string, string> },
) {
  upgradeSourceNesting(node.data.ir);
  state = {
    ir: node.data.ir,
    node,
    onSave,
    onClose,
    geo: null,
    history: IRHistory.createHistory({ limit: 50 }),
    sel: [], // массив выделенных {ref, label, node}
    zoom: 1,
    panX: 40,
    panY: 40,
    tool: "select",
    viewport: "desktop",
    previewWidth: 1440,
    activeIR: null,
    layerFlags: {}, // refKey -> {hidden, locked}; сессия редактора, не часть IR
    layerQuery: "",
    sourceContext: {
      registry: sourceContext?.registry || {},
      nodeSources: sourceContext?.nodeSources || {},
      lensEnabled: Object.keys(sourceContext?.registry || {}).length > 1,
      activeSourceIds: new Set(),
    },
  };
  const st = state;
  const responsive = !!(st.ir && st.ir.responsive && st.ir.responsive.viewports);
  // вьюпорт из графа: Page/Source Import прокидывают meta.activeViewport вниз —
  // редактор открывается на том же устройстве, что показывает нода
  const irVp = st.ir && st.ir.meta && st.ir.meta.activeViewport;
  if (responsive && ["desktop", "tablet", "mobile"].includes(irVp)) st.viewport = irVp;
  const viewportMeta = responsive ? st.ir.responsive.viewports[st.viewport] : null;
  st.previewWidth =
    (viewportMeta && viewportMeta.width ? viewportMeta.width : st.ir.frame && st.ir.frame.width) || 1440;
  if (dom.viewports) dom.viewports.hidden = !responsive;
  if (dom.responsiveSep) dom.responsiveSep.hidden = !responsive;
  dom.viewports?.querySelectorAll("[data-viewport]").forEach((b) => {
    b.classList.toggle("active", (b as HTMLElement).dataset.viewport === st.viewport);
  });
  if (dom.viewportWidth) dom.viewportWidth.value = String(st.previewWidth);
  if (dom.search) dom.search.value = "";
  return true;
}

/** Фаза 2 открытия: вызывается EditorApp, когда overlay уже display:flex
 *  (zoomFit/линейки требуют реальной раскладки). */
export function finishOpen() {
  if (!state) return;
  renderCanvas();
  renderLayers();
  renderInspector();
  updateUndoBtn();
  setTool("select");
  requestAnimationFrame(zoomFit);
}

function upgradeSourceNesting(ir: any) {
  if (!ir || !Array.isArray(ir.tree)) return false;
  let changed = false;
  ir.tree.forEach((sec: any) => {
    if (!sec || !(sec.type === "source-block" || sec.variant === "dom-capture") || !Array.isArray(sec.children)) return;
    if (sec.children.some((ch: any) => ch && Array.isArray(ch.children) && ch.children.length)) return;
    const sf = sec.frame || ir.frame || {};
    const rootArea = Math.max(1, Number(sf.width || 0) * Number(sf.height || 0));
    const assigned = new Set<number>();
    const containers: { el: any; index: number; kids: { child: any; index: number }[]; area: number }[] = [];
    sec.children.forEach((el: any, i: number) => {
      if (!el || el.type !== "rect" || !el.frame) return;
      const f = el.frame;
      const w = Number(f.width || 0), h = Number(f.height || 0);
      const area = w * h;
      const bg = (el.style && el.style.background) || el.fill || "";
      const hasVisual = !!bg || Number(el.radius || 0) > 0 || Number(el.style && el.style.borderWidth || 0) > 0;
      if (!hasVisual || w < 18 || h < 12 || w > 460 || h > 96 || area > rootArea * 0.28) return;
      const kids: { child: any; index: number }[] = [];
      sec.children.forEach((child: any, ci: number) => {
        if (ci === i || assigned.has(ci) || !child || !child.frame) return;
        if (!["text", "image", "icon"].includes(child.type)) return;
        const cf = child.frame;
        const cx = Number(cf.x || 0) + Number(cf.width || 0) / 2;
        const cy = Number(cf.y || 0) + Number(cf.height || 0) / 2;
        if (cx >= Number(f.x || 0) && cx <= Number(f.x || 0) + w &&
            cy >= Number(f.y || 0) && cy <= Number(f.y || 0) + h) {
          kids.push({ child, index: ci });
        }
      });
      if (!kids.length) return;
      containers.push({ el, index: i, kids, area });
    });
    containers.sort((a, b) => a.area - b.area);
    const byRect = new Map<number, { child: any; index: number }[]>();
    containers.forEach((c) => {
      if (assigned.has(c.index)) return;
      const usableKids = c.kids.filter((k) => !assigned.has(k.index));
      if (!usableKids.length) return;
      usableKids.forEach((k) => assigned.add(k.index));
      byRect.set(c.index, usableKids);
    });
    if (!byRect.size) return;
    const next: any[] = [];
    sec.children.forEach((el: any, i: number) => {
      if (assigned.has(i)) return;
      const kids = byRect.get(i);
      if (!kids) { next.push(el); return; }
      const f = el.frame || {};
      const texts = kids.map((k) => k.child).filter((ch: any) => ch.type === "text");
      const label = texts.map((t: any) => t.text || "").join(" ").trim();
      const bg = ((el.style && el.style.background) || el.fill || "").toLowerCase();
      const isAction = label && label.length <= 42 && (
        /найти|войти|разместить|search|login|sign|post|submit|buy|send/i.test(label) ||
        !["#ffffff", "#fff", "transparent"].includes(bg)
      );
      const isInput = !isAction && (Number(f.width || 0) >= 170 || /поиск|ищет|search|email|phone/i.test(label));
      const frame = Object.assign({}, f, { layout: "free", clip: true });
      const style = Object.assign({}, el.style || {});
      if (el.fill && !style.background) style.background = el.fill;
      let group: any;
      if (isAction) {
        group = { type: "button", text: label, variant: "primary", style, frame, children: [] };
      } else if (isInput) {
        group = { type: "input", placeholder: label, style, frame, children: [] };
      } else {
        group = { type: "card", role: "source-container", style, frame, children: [] };
      }
      kids.sort((a, b) => a.index - b.index).forEach((k) => {
        const child = JSON.parse(JSON.stringify(k.child));
        child.frame = Object.assign({}, child.frame || {});
        child.frame.x = Math.round((Number(child.frame.x || 0) - Number(f.x || 0)) * 1000) / 1000;
        child.frame.y = Math.round((Number(child.frame.y || 0) - Number(f.y || 0)) * 1000) / 1000;
        // text/heading children must not carry box visual styles — those belong to the container
        if (child.type === "text" || child.type === "heading") {
          const s = child.style || {};
          delete s.background; delete s.borderColor; delete s.borderWidth;
          delete s.borderRadius; delete s.boxShadow;
          child.style = s;
        }
        group.children.push(child);
      });
      next.push(group);
    });
    sec.children = next;
    changed = true;
  });
  return changed;
}

/* ---------- Style DNA Inspector ---------- */

export function openStyleDnaInspector() {
  if (!state || !dom.dnaPanel || !dom.dnaBody) return;
  dom.dnaPanel.classList.add("open");
  dom.dnaBody.innerHTML = '<div class="fe-dna-empty">Загрузка токенов…</div>';
  const existing = state.ir && state.ir.tokens;
  if (existing && existing.semantic && existing.primitives) {
    dnaPanelState = { tokens: deepClone(existing), originalTokens: deepClone(existing) };
    renderStyleDnaPanel();
  } else {
    void extractStyleDnaFromServer();
  }
}

export function closeStyleDnaInspector() {
  dom.dnaPanel?.classList.remove("open");
  dnaPanelState = null;
}

export function resetStyleDnaInspector() {
  if (!dnaPanelState) return;
  dnaPanelState.tokens = deepClone(dnaPanelState.originalTokens);
  renderStyleDnaPanel();
}

async function extractStyleDnaFromServer() {
  if (!state) return;
  try {
    const resp = await fetch("/api/style-dna/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: sanitizeIrForPost(state.ir) }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "HTTP " + resp.status);
    const tokens = data.tokens || {};
    dnaPanelState = { tokens: deepClone(tokens), originalTokens: deepClone(tokens) };
    renderStyleDnaPanel();
  } catch (e) {
    if (dom.dnaBody) {
      dom.dnaBody.innerHTML = `<div class="fe-dna-empty fe-dna-err">Ошибка загрузки: ${esc((e as Error).message)}</div>`;
    }
  }
}

async function applyStyleDnaFromInspector() {
  if (!state || !dnaPanelState) return;
  const foot = dom.dnaFoot;
  if (foot) foot.textContent = "Применение…";
  try {
    const resp = await fetch("/api/style-dna/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: sanitizeIrForPost(state.ir), tokens: dnaPanelState.tokens }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "HTTP " + resp.status);
    pushHistory();
    state.ir = data.ir || state.ir;
    state.node.data.ir = state.ir;
    dnaPanelState.originalTokens = deepClone(dnaPanelState.tokens);
    rerenderEditorCanvas();
    if (foot) foot.textContent = "Токены применены";
    setTimeout(() => { if (foot) foot.textContent = ""; }, 2000);
  } catch (e) {
    if (foot) foot.textContent = "Ошибка: " + (e as Error).message;
  }
}

function renderStyleDnaPanel() {
  const body = dom.dnaBody;
  const foot = dom.dnaFoot;
  const modeTag = dom.dnaMode;
  if (!body || !dnaPanelState || !state) return;
  const tokens = dnaPanelState.tokens;
  const semantic = tokens.semantic || {};
  const primitives = tokens.primitives || {};
  if (modeTag) modeTag.textContent = tokens.mode || semantic.mode || "light";

  const bindings = collectBindings(state.ir);
  const counts: Record<string, number> = {};
  for (const b of bindings) {
    const key = b.token;
    counts[key] = (counts[key] || 0) + 1;
  }

  const colorKeys = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"];
  let html = "";

  // Semantic colors
  html += `<div class="fe-dna-section"><div class="fe-dna-label">Semantic colors</div>`;
  for (const key of colorKeys) {
    const val = semantic[key] || "";
    const hex = colorHex(val);
    const alpha = colorAlpha(val);
    const count = counts["semantic." + key] || 0;
    html += `<div class="fe-dna-row" data-token="semantic.${key}">
      <label>${esc(key)}</label>
      <input type="color" value="${hex}" data-key="${key}" data-kind="color">
      <input type="text" value="${esc(val)}" data-key="${key}" data-kind="color-text" title="hex / rgba">
      <button class="fe-dna-highlight" data-highlight="semantic.${key}" title="Подсветить связанные">${count}</button>
    </div>
    <div class="fe-dna-row" data-token="semantic.${key}-alpha">
      <label style="width:60px">α ${Math.round(alpha * 100)}%</label>
      <input type="range" min="0" max="100" value="${Math.round(alpha * 100)}" data-key="${key}" data-kind="color-alpha">
    </div>`;
  }
  html += `</div>`;

  // Radii / spacing / fonts
  html += `<div class="fe-dna-section"><div class="fe-dna-label">Layout & type</div>`;
  html += dnaNumberRow("buttonRadius", semantic.buttonRadius, "semantic.buttonRadius", counts);
  html += dnaNumberRow("cardRadius", semantic.cardRadius, "semantic.cardRadius", counts);
  html += dnaNumberRow("inputRadius", semantic.inputRadius, "semantic.inputRadius", counts);
  html += dnaNumberRow("sectionGap", semantic.sectionGap, "semantic.sectionGap", counts);
  html += dnaNumberRow("containerWidth", semantic.containerWidth, "semantic.containerWidth", counts);
  html += `</div>`;

  html += `<div class="fe-dna-section"><div class="fe-dna-label">Fonts</div>`;
  html += dnaFontRow("display", semantic.displayFont, counts);
  html += dnaFontRow("body", semantic.bodyFont, counts);
  html += `</div>`;

  // Primitives
  html += `<div class="fe-dna-section"><div class="fe-dna-label">Primitives</div>`;
  if ((primitives.colors || []).length) {
    html += `<div class="fe-dna-meta">Colors (${primitives.colors.length})</div>`;
    for (const c of primitives.colors.slice(0, 24)) {
      html += `<div class="fe-dna-row"><span class="fe-dna-primitive" style="color:${esc(c)}">■</span><span class="fe-dna-primitive">${esc(c)}</span></div>`;
    }
  }
  if ((primitives.fonts || []).length) {
    html += `<div class="fe-dna-meta" style="margin-top:8px">Fonts (${primitives.fonts.length})</div>`;
    for (const f of primitives.fonts) {
      html += `<div class="fe-dna-primitive">${esc(f.family)} ${esc(f.weight)}</div>`;
    }
  }
  if ((primitives.radii || []).length) {
    html += `<div class="fe-dna-meta" style="margin-top:8px">Radii</div>`;
    html += `<div class="fe-dna-primitive">${primitives.radii.join(", ")}</div>`;
  }
  if ((primitives.spacings || []).length) {
    html += `<div class="fe-dna-meta" style="margin-top:8px">Spacings</div>`;
    html += `<div class="fe-dna-primitive">${primitives.spacings.join(", ")}</div>`;
  }
  html += `</div>`;

  html += `<div class="fe-dna-section"><div class="fe-dna-label">Normalize & Tailwind</div>
    <div class="fe-dna-meta">Exact IR remains canonical. Normalize is applied only after preview.</div>
    <div class="fe-dna-workflow-actions">
      <button class="fe-btn" data-dna-action="preview-normalize">Preview Normalize</button>
      <button class="fe-btn" data-dna-action="tailwind-exact">Exact Tailwind</button>
      <button class="fe-btn" data-dna-action="tailwind-normalized">Normalized Tailwind</button>
      <button class="fe-btn" data-dna-action="copy-tailwind" disabled>Copy classes</button>
    </div>
    <div id="feDnaWorkflowResult"></div>
  </div>`;

  body.innerHTML = html;
  if (foot) foot.textContent = `${bindings.length} bindings · ${Object.keys(counts).length} tokens`;
  wireStyleDnaEvents(body, bindings);
}

function dnaNumberRow(label: string, value: any, token: string, counts: Record<string, number>) {
  const count = counts[token] || 0;
  return `<div class="fe-dna-row" data-token="${esc(token)}">
    <label>${esc(label)}</label>
    <input type="number" value="${value == null ? "" : value}" data-kind="number" data-token="${esc(token)}">
    <button class="fe-dna-highlight" data-highlight="${esc(token)}" title="Подсветить связанные">${count}</button>
  </div>`;
}

function dnaFontRow(label: string, font: any, counts: Record<string, number>) {
  const f = font || { family: "Inter", weight: 400 };
  const token = `semantic.${label}Font`;
  const count = counts[token] || 0;
  return `<div class="fe-dna-row" data-token="${esc(token)}">
    <label>${esc(label)}</label>
    <select data-kind="font-family" data-token="${esc(token)}" class="fe-dna-fontsel">${fontOptionsHtml(f.family)}</select>
    <input type="number" value="${f.weight}" data-kind="font-weight" data-token="${esc(token)}" style="width:55px">
    <button class="fe-dna-highlight" data-highlight="${esc(token)}" title="Подсветить связанные">${count}</button>
  </div>`;
}

function wireStyleDnaEvents(body: HTMLElement, bindings: { ref: GeoRef; token: string }[]) {
  // color pickers
  body.querySelectorAll<HTMLInputElement>("input[data-kind='color']").forEach((inp) => {
    inp.addEventListener("input", () => {
      const key = inp.dataset.key!;
      const text = body.querySelector<HTMLInputElement>(`input[data-kind='color-text'][data-key='${key}']`);
      const alphaInp = body.querySelector<HTMLInputElement>(`input[data-kind='color-alpha'][data-key='${key}']`);
      const alpha = alphaInp ? parseInt(alphaInp.value, 10) / 100 : 1;
      const val = withAlpha(inp.value, alpha);
      if (text) text.value = val;
      setSemanticToken(key, val);
    });
  });
  body.querySelectorAll<HTMLInputElement>("input[data-kind='color-text']").forEach((inp) => {
    inp.addEventListener("change", () => {
      const key = inp.dataset.key!;
      const picker = body.querySelector<HTMLInputElement>(`input[data-kind='color'][data-key='${key}']`);
      const alphaInp = body.querySelector<HTMLInputElement>(`input[data-kind='color-alpha'][data-key='${key}']`);
      const val = inp.value.trim();
      const hex = colorHex(val);
      const alpha = colorAlpha(val);
      if (picker && hex) picker.value = hex;
      if (alphaInp) alphaInp.value = String(Math.round(alpha * 100));
      setSemanticToken(key, val);
    });
  });
  body.querySelectorAll<HTMLInputElement>("input[data-kind='color-alpha']").forEach((inp) => {
    inp.addEventListener("input", () => {
      const key = inp.dataset.key!;
      const picker = body.querySelector<HTMLInputElement>(`input[data-kind='color'][data-key='${key}']`);
      const text = body.querySelector<HTMLInputElement>(`input[data-kind='color-text'][data-key='${key}']`);
      const alpha = parseInt(inp.value, 10) / 100;
      const val = withAlpha(picker ? picker.value : text ? text.value : "#000000", alpha);
      if (text) text.value = val;
      setSemanticToken(key, val);
    });
  });
  // numbers
  body.querySelectorAll<HTMLInputElement>("input[data-kind='number']").forEach((inp) => {
    inp.addEventListener("change", () => {
      const token = inp.dataset.token!;
      const key = token.replace("semantic.", "");
      const val = parseFloat(inp.value);
      if (Number.isFinite(val)) setSemanticToken(key, val);
    });
  });
  // fonts
  body.querySelectorAll<HTMLSelectElement>("select[data-kind='font-family']").forEach((sel) => {
    sel.addEventListener("change", () => {
      const token = sel.dataset.token!;
      const key = token.replace("semantic.", "");
      const obj = dnaPanelState && dnaPanelState.tokens.semantic[key];
      if (obj) obj.family = sel.value;
    });
  });
  body.querySelectorAll<HTMLInputElement>("input[data-kind='font-weight']").forEach((inp) => {
    inp.addEventListener("change", () => {
      const token = inp.dataset.token!;
      const key = token.replace("semantic.", "");
      const val = parseInt(inp.value, 10);
      if (Number.isFinite(val) && dnaPanelState) dnaPanelState.tokens.semantic[key].weight = val;
    });
  });
  // highlight
  body.querySelectorAll<HTMLButtonElement>("button[data-highlight]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const token = btn.dataset.highlight;
      const refs = bindings.filter((b) => b.token === token).map((b) => b.ref);
      if (state && state.geo && refs.length) state.geo.selectMulti(refs);
    });
  });
  body.querySelectorAll<HTMLButtonElement>("button[data-dna-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.dnaAction;
      if (action === "preview-normalize") void previewStyleNormalization();
      else if (action === "apply-normalize") applyNormalizationPreview();
      else if (action === "tailwind-exact") void loadTailwindProjection("exact");
      else if (action === "tailwind-normalized") void loadTailwindProjection("normalized");
      else if (action === "copy-tailwind") void copyTailwindClasses();
    });
  });
}

function workflowResult() {
  return document.getElementById("feDnaWorkflowResult");
}

async function previewStyleNormalization() {
  if (!state || !dnaPanelState) return;
  const result = workflowResult();
  if (result) result.innerHTML = '<div class="fe-dna-result fe-dna-empty">Building preview...</div>';
  try {
    const resp = await fetch("/api/style/normalize/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: sanitizeIrForPost(state.ir), tolerance: 0.12 }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "HTTP " + resp.status);
    dnaPanelState.normalization = data;
    const patch = data.patch || [];
    if (!result) return;
    const changes = patch.slice(0, 12).map((change: any) =>
      `<div class="fe-dna-change"><strong>${esc(change.path)}</strong><br>${esc(JSON.stringify(change.before))} -> ${esc(JSON.stringify(change.after))}</div>`,
    ).join("");
    result.innerHTML = `<div class="fe-dna-result">
      <div class="fe-dna-meta">${patch.length} properties · risk ${esc((data.visualDelta || {}).risk || "none")}</div>
      ${changes || '<div class="fe-dna-empty">Already aligned with Style DNA scale.</div>'}
      ${patch.length > 12 ? `<div class="fe-dna-meta">+ ${patch.length - 12} more changes</div>` : ""}
      ${patch.length ? '<button class="fe-btn primary" data-dna-action="apply-normalize" style="width:100%;margin-top:8px">Apply Normalize</button>' : ""}
    </div>`;
    const apply = result.querySelector('[data-dna-action="apply-normalize"]');
    if (apply) apply.addEventListener("click", applyNormalizationPreview);
  } catch (e) {
    if (result) result.innerHTML = `<div class="fe-dna-result fe-dna-err">${esc((e as Error).message)}</div>`;
  }
}

function applyNormalizationPreview() {
  if (!state || !dnaPanelState || !dnaPanelState.normalization || !dnaPanelState.normalization.normalizedIr) return;
  const changed = (dnaPanelState.normalization.patch || []).length;
  pushHistory();
  state.ir = deepClone(dnaPanelState.normalization.normalizedIr);
  state.node.data.ir = state.ir;
  dnaPanelState.tokens = deepClone(state.ir.tokens || dnaPanelState.tokens);
  dnaPanelState.originalTokens = deepClone(dnaPanelState.tokens);
  dnaPanelState.normalization = null;
  rerenderEditorCanvas();
  renderLayers();
  renderStyleDnaPanel();
  if (dom.dnaFoot) dom.dnaFoot.textContent = `Normalized ${changed} properties`;
}

async function loadTailwindProjection(mode: string) {
  if (!state || !dnaPanelState) return;
  const result = workflowResult();
  if (result) result.innerHTML = `<div class="fe-dna-result fe-dna-empty">Building ${esc(mode)} projection...</div>`;
  try {
    const resp = await fetch("/api/export/tailwind", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: sanitizeIrForPost(state.ir), mode }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "HTTP " + resp.status);
    const lines: string[] = [];
    for (const node of (data.nodes || []).slice(0, 30)) {
      const classes = Object.values(node.classes || {}).flat().join(" ");
      lines.push(`${node.sourceKey}: ${classes}`);
    }
    dnaPanelState.tailwindText = lines.join("\n");
    if (result) {
      result.innerHTML = `<div class="fe-dna-result">
        <div class="fe-dna-meta">${esc(mode)} · ${(data.nodes || []).length} nodes · ${(data.diagnostics || []).length} diagnostics</div>
        <pre class="fe-dna-code">${esc(dnaPanelState.tailwindText || "No editable nodes")}</pre>
      </div>`;
    }
    const copy = document.querySelector<HTMLButtonElement>('[data-dna-action="copy-tailwind"]');
    if (copy) copy.disabled = !dnaPanelState.tailwindText;
  } catch (e) {
    if (result) result.innerHTML = `<div class="fe-dna-result fe-dna-err">${esc((e as Error).message)}</div>`;
  }
}

async function copyTailwindClasses() {
  if (!dnaPanelState || !dnaPanelState.tailwindText || !navigator.clipboard) return;
  await navigator.clipboard.writeText(dnaPanelState.tailwindText);
  if (dom.dnaFoot) dom.dnaFoot.textContent = "Tailwind classes copied";
}

function setSemanticToken(key: string, value: any) {
  if (!dnaPanelState) return;
  dnaPanelState.tokens.semantic[key] = value;
  // keep legacy color map in sync
  const colorKeys = new Set(["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"]);
  if (colorKeys.has(key) && dnaPanelState.tokens.color) {
    dnaPanelState.tokens.color[key] = value;
  }
}

function collectBindings(ir: any) {
  const out: { ref: GeoRef; token: string; property: string; viewport?: string }[] = [];
  function visit(node: any, ref: GeoRef) {
    if (!node || typeof node !== "object") return;
    const bindings = node.styleBindings || {};
    for (const [prop, binding] of Object.entries<any>(bindings)) {
      if (binding && binding.token) out.push({ ref, token: binding.token, property: prop });
    }
    const responsive = node.responsive || {};
    for (const [vp, override] of Object.entries<any>(responsive)) {
      if (!override || !override.styleBindings) continue;
      for (const [prop, binding] of Object.entries<any>(override.styleBindings)) {
        if (binding && binding.token) out.push({ ref, token: binding.token, property: prop, viewport: vp });
      }
    }
    (node.children || []).forEach((child: any, i: number) =>
      visit(child, { ...ref, path: (ref.path ? ref.path + "." : "") + "children." + i }));
  }
  (ir.tree || []).forEach((sec: any, i: number) => visit(sec, { secIdx: i, path: null }));
  return out;
}

function colorHex(value: any) {
  const s = String(value || "").trim().toLowerCase();
  if (/^#[0-9a-f]{3}$/.test(s)) return "#" + s[1] + s[1] + s[2] + s[2] + s[3] + s[3];
  if (/^#[0-9a-f]{6}$/.test(s)) return s;
  if (/^#[0-9a-f]{8}$/.test(s)) return s.slice(0, 7);
  if (/^rgba?\(/.test(s)) {
    const m = s.match(/\d+\.?\d*/g);
    if (m && m.length >= 3) {
      const toHex = (n: string) => {
        const x = Math.max(0, Math.min(255, Math.round(Number(n))));
        return x.toString(16).padStart(2, "0");
      };
      return "#" + toHex(m[0]) + toHex(m[1]) + toHex(m[2]);
    }
  }
  return "#888888";
}

function colorAlpha(value: any) {
  const s = String(value || "").trim().toLowerCase();
  if (/^#[0-9a-f]{8}$/.test(s)) return parseInt(s.slice(7, 9), 16) / 255;
  if (/^rgba?\(/.test(s)) {
    const m = s.match(/\d+\.?\d*/g);
    if (m && m.length >= 4) return Math.max(0, Math.min(1, Number(m[3])));
  }
  return 1;
}

function withAlpha(hex: string, alpha: number) {
  const base = colorHex(hex);
  if (alpha >= 0.999) return base;
  const a = Math.max(0, Math.min(255, Math.round(alpha * 255))).toString(16).padStart(2, "0");
  return base + a;
}

function deepClone(obj: any) {
  return JSON.parse(JSON.stringify(obj));
}

/** Клон IR для POST-пayload'ов без runtime-ключей (__path/__responsiveHidden).
 *  renderer.materializeResponsiveIR аннотирует канонический IR через __path
 *  (этот side-effect нужен syncActiveIR для ключей sourceNodeMap, в памяти не трогаем),
 *  но серверная schema их отклоняет (422) — чистим только копию на провод. */
function sanitizeIrForPost(ir: any) {
  const clone = deepClone(ir);
  const walk = (node: any) => {
    if (!node || typeof node !== "object") return;
    delete node.__path;
    delete node.__responsiveHidden;
    (node.children || []).forEach(walk);
  };
  (clone.tree || []).forEach(walk);
  return clone;
}

/* ---------- сохранение / история ---------- */

function save() {
  if (!state) return;
  syncActiveIR();
  if (state.onSave) state.onSave(state.ir);
  close(true);
}

export function close(saved?: boolean) {
  if (state && state.onClose) state.onClose(!!saved);
  if (state && state.geo) { state.geo.destroy(); state.geo = null; }
  state = null;
  dnaPanelState = null;
  dom.dnaPanel?.classList.remove("open");
  ui.setOpen(false);
}

export function pushHistory() {
  if (!state) return;
  // ключ коалесценции — текущее выделение: серии быстрых правок
  // одного выделения (nudge стрелками) сливаются в одну запись
  const key = state.sel.map((s) => s.ref.secIdx + ":" + (s.ref.path || "")).join(",");
  state.history.push(() => state!.ir, key);
  updateUndoBtn();
}

function undo() {
  if (!state) return;
  const snap = state.history.undo(() => state!.ir);
  if (!snap) return;
  state.ir = snap;
  state.node.data.ir = state.ir;
  if (state.geo) { state.geo.destroy(); state.geo = null; }
  renderCanvas();
  renderLayers();
  state.sel = [];
  renderInspector();
  updateUndoBtn();
  updateAlignVisibility();
}

function redo() {
  if (!state) return;
  const snap = state.history.redo(() => state!.ir);
  if (!snap) return;
  state.ir = snap;
  state.node.data.ir = state.ir;
  if (state.geo) { state.geo.destroy(); state.geo = null; }
  renderCanvas();
  renderLayers();
  state.sel = [];
  renderInspector();
  updateUndoBtn();
  updateAlignVisibility();
}

function updateUndoBtn() {
  if (!state) return;
  if (dom.undoBtn) dom.undoBtn.disabled = !state.history.canUndo();
  if (dom.redoBtn) dom.redoBtn.disabled = !state.history.canRedo();
}

function updateAlignVisibility() {
  if (!state) return;
  if (dom.alignGroup) dom.alignGroup.hidden = state.sel.length < 2;
}

/* ---------- канвас ---------- */

function buildActiveIR() {
  if (!state) return null;
  if (!state.ir || !state.ir.responsive || !state.ir.responsive.viewports) {
    state.activeIR = state.ir;
    return state.activeIR;
  }
  state.activeIR = IRRenderer.materializeResponsiveIR(state.ir, state.viewport);
  if (state.activeIR.frame && Number.isFinite(state.previewWidth)) state.activeIR.frame.width = state.previewWidth;
  delete state.activeIR.responsive;
  return state.activeIR;
}

function sourceNodeMap(ir: any) {
  const out = new Map<string, any>();
  function visit(node: any, fallback: string) {
    if (!node || typeof node !== "object") return;
    const key = node.sourceKey || node.__path || fallback;
    if (key) out.set(key, node);
    (node.children || []).forEach((child: any, i: number) => visit(child, `${fallback}.children.${i}`));
  }
  (ir.tree || []).forEach((sec: any, i: number) => visit(sec, `tree.${i}`));
  return out;
}

let manualSourceKey = 0;

function syncSharedStructure() {
  if (!state) return;
  const active = state.activeIR;
  const canonical = state.ir;
  if (!active || !canonical || !canonical.responsive) return;
  const targetByKey = sourceNodeMap(canonical);

  function ensureKey(node: any) {
    if (!node.sourceKey) node.sourceKey = `manual:${Date.now().toString(36)}:${++manualSourceKey}`;
    (node.children || []).forEach(ensureKey);
  }
  (active.tree || []).forEach(ensureKey);

  function cleanRuntime(node: any) {
    delete node.__path;
    delete node.__responsiveHidden;
    (node.children || []).forEach(cleanRuntime);
    return node;
  }

  function reconcile(activeParent: any, targetParent: any) {
    const next: any[] = [];
    (activeParent.children || []).forEach((activeChild: any) => {
      const key = activeChild.sourceKey;
      let targetChild = targetByKey.get(key);
      if (!targetChild) {
        targetChild = cleanRuntime(JSON.parse(JSON.stringify(activeChild)));
        targetByKey.set(key, targetChild);
      }
      next.push(targetChild);
      reconcile(activeChild, targetChild);
    });
    targetParent.children = next;
  }

  const canonicalSections = new Map((canonical.tree || []).map((sec: any) => [sec.sourceKey || sec.id, sec]));
  (active.tree || []).forEach((activeSec: any, index: number) => {
    const targetSec = canonicalSections.get(activeSec.sourceKey || activeSec.id) || canonical.tree[index];
    if (targetSec) reconcile(activeSec, targetSec);
  });
}

function syncActiveIR() {
  if (!state || !state.activeIR || state.activeIR === state.ir || !state.ir.responsive) return;
  syncSharedStructure();
  const source = sourceNodeMap(state.activeIR);
  const target = sourceNodeMap(state.ir);
  const sharedKeys = ["text", "title", "placeholder", "value", "label", "src", "alt", "href"];
  target.forEach((node, key) => {
    const active = source.get(key);
    if (!active) return;
    sharedKeys.forEach((prop) => {
      if (Object.prototype.hasOwnProperty.call(active, prop)) node[prop] = active[prop];
    });
    if (state!.viewport === "desktop") {
      if (active.frame) node.frame = JSON.parse(JSON.stringify(active.frame));
      if (active.style) node.style = JSON.parse(JSON.stringify(active.style));
    } else {
      node.responsive = node.responsive || {};
      const override = node.responsive[state!.viewport] || {};
      override.visible = true;
      if (active.frame) override.frame = JSON.parse(JSON.stringify(active.frame));
      if (active.style) override.style = JSON.parse(JSON.stringify(active.style));
      node.responsive[state!.viewport] = override;
    }
  });
}

function renderCanvas() {
  if (!state || !dom.canvasInner) return;
  const inner = dom.canvasInner;
  IRRenderer.renderIR(inner, buildActiveIR(), { fit: false }); // _frames применяет сам рендерер
  applyLayerFlags();
  applyTransform();
  attachGeoEdit();
  applySourceLens();
}

/* ---------- флаги слоёв (hide/lock): сессия редактора, вне IR ---------- */

function refKeyOf(ref: GeoRef) {
  return ref.secIdx + ":" + (ref.path || "");
}

/** true если ref или любой предок (карточка/секция/артборд) несёт флаг kind. */
function refFlag(ref: GeoRef, kind: "hidden" | "locked") {
  if (!state || !state.layerFlags) return false;
  const check = (si: number | null, p: string | null) => {
    const f = state!.layerFlags[si + ":" + (p || "")];
    return !!(f && f[kind]);
  };
  let path: string | null = ref.path || null;
  while (path) {
    if (check(ref.secIdx, path)) return true;
    const segs = path.split(".");
    segs.pop(); segs.pop();
    path = segs.length ? segs.join(".") : null;
  }
  if (ref.secIdx != null && check(ref.secIdx, null)) return true;
  return check(null, null);
}

function domAtCanvas(ref: GeoRef): HTMLElement | null {
  const inner = dom.canvasInner;
  if (!inner) return null;
  if (ref.secIdx == null) return inner.querySelector('[class^="ir-"]') as HTMLElement | null;
  const secEl = inner.querySelector(`[data-ir-sec="${ref.secIdx}"]`);
  if (!secEl) return null;
  if (ref.path == null) return secEl as HTMLElement;
  return (secEl.querySelector(`[data-ir-path="${ref.path}"]`) ||
         secEl.querySelector(`[data-ir-path^="${ref.path}"]`)) as HTMLElement | null;
}

/** hidden-слои убираются с канваса; locked живут, но не выделяются (geoedit.isLocked). */
function applyLayerFlags() {
  if (!state || !state.layerFlags) return;
  for (const [key, f] of Object.entries(state.layerFlags)) {
    const [si, path] = key.split(":");
    const el = domAtCanvas({ secIdx: si === "null" ? null : Number(si), path: path || null });
    if (el) el.style.display = f.hidden ? "none" : "";
  }
}

function toggleLayerFlag(ref: GeoRef, kind: "hidden" | "locked") {
  if (!state) return;
  const key = refKeyOf(ref);
  const f = state.layerFlags[key] || (state.layerFlags[key] = {});
  f[kind] = !f[kind];
  if (f[kind] && state.sel.some((s) => refKeyOf(s.ref) === key) && state.geo) state.geo.clear();
  applyLayerFlags();
  renderLayers();
}

function applyTransform() {
  if (!state || !dom.canvasInner || !dom.canvas) return;
  const inner = dom.canvasInner;
  inner.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  const canvas = dom.canvas;
  canvas.style.backgroundSize = `${20 * state.zoom}px ${20 * state.zoom}px`;
  canvas.style.backgroundPosition = `${state.panX}px ${state.panY}px`;
  if (dom.zoomLabel) dom.zoomLabel.textContent = Math.round(state.zoom * 100) + "%";
  drawRulers();
}

export function drawRulers() {
  if (!state || !dom.canvas || !dom.rulerH || !dom.rulerV) return;
  const canvas = dom.canvas;
  const cr = canvas.getBoundingClientRect();
  const rulerH = dom.rulerH;
  const rulerV = dom.rulerV;
  const w = Math.ceil(cr.width - 24), h = Math.ceil(cr.height - 24);
  if (w <= 0 || h <= 0) return;
  rulerH.width = w; rulerH.height = 24;
  rulerV.width = 24; rulerV.height = h;
  const ctxH = rulerH.getContext("2d");
  const ctxV = rulerV.getContext("2d");
  if (!ctxH || !ctxV) return;
  ctxH.clearRect(0, 0, w, 24);
  ctxV.clearRect(0, 0, 24, h);
  ctxH.fillStyle = "#a1a1aa"; ctxH.font = "9px Inter, sans-serif"; ctxH.textBaseline = "top";
  ctxV.fillStyle = "#a1a1aa"; ctxV.font = "9px Inter, sans-serif"; ctxV.textBaseline = "middle";

  const z = state.zoom;
  // адаптивный шаг: при малом зуме показываем только крупные деления
  const minorStep = z >= 0.5 ? 8 : z >= 0.25 ? 16 : 32;
  const majorStep = z >= 0.5 ? 100 : z >= 0.25 ? 200 : 400;
  const offsetX = state.panX - 24; // сдвиг линейки относительно канваса (24px = ширина вертикальной линейки)
  const offsetY = state.panY - 24;

  // горизонтальная линейка
  const startX = Math.floor(-offsetX / z / minorStep) * minorStep;
  const endX = Math.ceil((w - offsetX) / z / minorStep) * minorStep;
  for (let px = startX; px <= endX; px += minorStep) {
    const screenX = px * z + offsetX;
    if (screenX < 0 || screenX > w) continue;
    const isMajor = px % majorStep === 0;
    ctxH.strokeStyle = isMajor ? "#a1a1aa" : "#3f3f46";
    ctxH.beginPath();
    ctxH.moveTo(screenX, isMajor ? 0 : 16);
    ctxH.lineTo(screenX, 24);
    ctxH.stroke();
    if (isMajor) ctxH.fillText(String(px), screenX + 2, 2);
  }

  // вертикальная линейка
  const startY = Math.floor(-offsetY / z / minorStep) * minorStep;
  const endY = Math.ceil((h - offsetY) / z / minorStep) * minorStep;
  for (let py = startY; py <= endY; py += minorStep) {
    const screenY = py * z + offsetY;
    if (screenY < 0 || screenY > h) continue;
    const isMajor = py % majorStep === 0;
    ctxV.strokeStyle = isMajor ? "#a1a1aa" : "#3f3f46";
    ctxV.beginPath();
    ctxV.moveTo(isMajor ? 0 : 16, screenY);
    ctxV.lineTo(24, screenY);
    ctxV.stroke();
    if (isMajor) {
      ctxV.save();
      ctxV.translate(10, screenY + 2);
      ctxV.rotate(-Math.PI / 2);
      ctxV.fillText(String(py), 0, 0);
      ctxV.restore();
    }
  }
}

function zoomBy(factor: number) {
  if (!state || !dom.canvas) return;
  const canvas = dom.canvas;
  const r = canvas.getBoundingClientRect();
  const cx = r.width / 2, cy = r.height / 2;
  const z = Math.min(3, Math.max(0.15, state.zoom * factor));
  state.panX = cx - (cx - state.panX) * (z / state.zoom);
  state.panY = cy - (cy - state.panY) * (z / state.zoom);
  state.zoom = z;
  applyTransform();
}

export function zoomFit() {
  if (!state || !dom.canvasInner || !dom.canvas) return;
  const inner = dom.canvasInner;
  const irEl = inner.querySelector('[class^="ir-"]') as HTMLElement | null;
  if (!irEl) return;
  const canvas = dom.canvas;
  const cr = canvas.getBoundingClientRect();
  const iw = irEl.offsetWidth || 960, ih = irEl.offsetHeight || 600;
  const z = Math.min(1, Math.min((cr.width - 60) / iw, (cr.height - 60) / ih));
  state.zoom = Math.max(0.15, z);
  state.panX = (cr.width - iw * state.zoom) / 2;
  state.panY = (cr.height - ih * state.zoom) / 2;
  applyTransform();
}

/* Панорама/зум канваса — навешивается CanvasStage один раз на живой элемент. */
export function onCanvasPointerDown(e: PointerEvent) {
  if (!state || !dom.canvas) return;
  if (state.tool !== "hand" && e.button !== 1) return;
  const target = e.target as HTMLElement;
  if (target.closest('[class^="ir-"]') || target.closest(".fe-rail")) return;
  e.preventDefault();
  const canvas = dom.canvas;
  canvas.style.cursor = "grabbing";
  const sx = e.clientX, sy = e.clientY, px = state.panX, py = state.panY;
  const move = (ev: PointerEvent) => {
    if (!state) return;
    state.panX = px + ev.clientX - sx;
    state.panY = py + ev.clientY - sy;
    applyTransform();
  };
  const up = () => {
    if (dom.canvas) dom.canvas.style.cursor = state && state.tool === "hand" ? "grab" : "default";
    window.removeEventListener("pointermove", move);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up, { once: true });
}

export function onCanvasWheel(e: WheelEvent) {
  if (!state || !dom.canvas) return;
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
  const r = dom.canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const z = Math.min(3, Math.max(0.15, state.zoom * factor));
  state.panX = mx - (mx - state.panX) * (z / state.zoom);
  state.panY = my - (my - state.panY) * (z / state.zoom);
  state.zoom = z;
  applyTransform();
}

/** Адаптер: «скролл» руки = панорама канваса (panX/panY). */
const panAdapter = {
  get scrollLeft() { return state ? -state.panX : 0; },
  set scrollLeft(v: number) { if (state) { state.panX = -v; applyTransform(); } },
  get scrollTop() { return state ? -state.panY : 0; },
  set scrollTop(v: number) { if (state) { state.panY = -v; applyTransform(); } },
};

function attachGeoEdit() {
  if (!state || !dom.canvasInner) return;
  if (state.geo) state.geo.destroy();
  const inner = dom.canvasInner;
  const previewEl = inner;
  state.geo = GeoEdit.attach({
    previewEl,
    tools: true,
    escapeViaHandle: true, // Esc обрабатываем сами через geo.consumeEscape()
    isLocked: (ref: GeoRef) => refFlag(ref, "locked"), // locked-слои не выделяются на канвасе
    scrollEl: panAdapter,
    onToolChange: (t: string) => { if (state && state.tool !== t) setTool(t); },
    getIR: () => (state ? state.activeIR || state.ir : null),
    getScale: () => {
      const irEl = inner.querySelector('[class^="ir-"]') as HTMLElement | null;
      if (!irEl) return 1;
      const dw = Number(irEl.dataset.designWidth) || IRRenderer.DESIGN_WIDTH;
      const w = irEl.getBoundingClientRect().width;
      return w > 0 ? w / dw : 1;
    },
    onCommit: () => pushHistory(),
    onMutated: () => {
      if (!state) return;
      syncActiveIR();
      const savedRefs = state.sel.map((s) => s.ref);
      IRRenderer.renderIR(inner, buildActiveIR(), { fit: false });
      applyLayerFlags();
      applyTransform();
      attachGeoEdit();
      renderLayers();
      if (savedRefs.length && state.geo) {
        state.geo.selectMulti(savedRefs);
      }
      applySourceLens();
      // во время drag-scrub инспектор не перестраиваем — иначе умрёт pointer capture
      if (!inspScrubbing) renderInspector();
    },
    onSelect: (sels: GeoSel[]) => {
      if (!state) return;
      state.sel = sels || [];
      // во время drag-scrub не перестраиваем инспектор — умрёт pointer capture
      if (!inspScrubbing) renderInspector();
      renderLayers();
      updateAlignVisibility();
      applySourceLens();
    },
  });
  // инструмент переживает ре-аттач после мутаций
  if (state.tool !== "select") state.geo.setTool(state.tool);
}

/* ---------- слои ---------- */

function propsElements(sec: any) {
  const p = sec.props || {};
  const items: { path: string; label: string; icon: string }[] = [];
  if (p.logoText) items.push({ path: "props.logoText", label: "logo: " + p.logoText, icon: "◆" });
  if (p.links) p.links.forEach((l: any, i: number) => items.push({ path: `props.links.${i}`, label: "link: " + (l.label || ""), icon: "→" }));
  if (p.cta && p.cta.text) items.push({ path: "props.cta", label: "cta: " + p.cta.text, icon: "⬛" });
  if (p.badge) items.push({ path: "props.badge", label: "badge: " + p.badge, icon: "•" });
  if (p.heading) items.push({ path: "props.heading", label: "heading: " + String(p.heading).slice(0, 22), icon: "H" });
  if (p.subheading) items.push({ path: "props.subheading", label: "sub: " + String(p.subheading).slice(0, 22), icon: "T" });
  if (p.ctaPrimary && p.ctaPrimary.text) items.push({ path: "props.ctaPrimary", label: "btn: " + p.ctaPrimary.text, icon: "⬛" });
  if (p.ctaSecondary && p.ctaSecondary.text) items.push({ path: "props.ctaSecondary", label: "btn: " + p.ctaSecondary.text, icon: "⬜" });
  if (p.media) items.push({ path: "props.media", label: "media", icon: "▣" });
  if (p.text && !p.heading) items.push({ path: "props.text", label: "text: " + String(p.text).slice(0, 22), icon: "T" });
  if (p.tiers) p.tiers.forEach((tier: any, i: number) => items.push({ path: `props.tiers.${i}`, label: "tier: " + tier.name, icon: "$" }));
  if (p.items && sec.type === "faq") p.items.forEach((item: any, i: number) => items.push({ path: `props.items.${i}`, label: "faq: " + String(item.question).slice(0, 20), icon: "?" }));
  if (p.items && sec.type === "stats") p.items.forEach((item: any, i: number) => items.push({ path: `props.items.${i}`, label: "stat: " + item.value, icon: "#" }));
  return items;
}

export function renderLayers() {
  const tree = dom.layersTree;
  if (!tree || !state) return;
  tree.innerHTML = "";
  if (!state.ir || !state.ir.tree) return;
  // артборд
  addLayerItem(tree, state.ir, { secIdx: null, path: null }, 0, "Артборд");
  state.ir.tree.forEach((sec: any, si: number) => {
    const secLabel = sec.type + (sec.props && sec.props.heading ? ` · ${String(sec.props.heading).slice(0, 18)}` : "");
    addLayerItem(tree, sec, { secIdx: si, path: null }, 1, secLabel);
    // props-элементы
    propsElements(sec).forEach((pe) => {
      addLayerItem(tree, getByPath(sec, pe.path) || {}, { secIdx: si, path: pe.path }, 2, pe.label, pe.icon);
    });
    renderChildLayers(tree, sec.children || [], si, "children", 2);
  });
}

function layerLabel(el: any, maxText: number) {
  const base = el.type === "card" && el.role ? "div" : el.type;
  const suffix = el.text ? ` · ${String(el.text).slice(0, maxText)}`
    : el.title ? ` · ${String(el.title).slice(0, maxText)}`
    : el.placeholder ? ` · ${String(el.placeholder).slice(0, maxText)}`
    : "";
  return base + suffix;
}

function renderChildLayers(tree: HTMLElement, children: any[], secIdx: number, basePath: string, depth: number) {
  children.forEach((el, i) => {
    const path = `${basePath}.${i}`;
    addLayerItem(tree, el, { secIdx, path }, depth, layerLabel(el, depth > 2 ? 14 : 16));
    if (el.children && el.children.length) {
      renderChildLayers(tree, el.children, secIdx, `${path}.children`, depth + 1);
    }
  });
}

function addLayerItem(
  container: HTMLElement, irNode: any, ref: GeoRef, depth: number, label: string, iconOverride?: string,
) {
  if (!state) return;
  if (state.layerQuery && !label.toLowerCase().includes(state.layerQuery.toLowerCase())) return;
  const key = refKeyOf(ref);
  const fl = state.layerFlags[key] || {};
  const div = document.createElement("div");
  div.className = "fe-layer depth-" + Math.min(depth, 3);
  if (depth > 3) div.style.paddingLeft = 48 + (depth - 3) * 12 + "px";
  div.dataset.key = key;
  // reorder drag&drop — только не-артборд
  if (!(ref.secIdx == null && ref.path == null)) {
    div.draggable = true;
    div.addEventListener("dragstart", (e) => {
      if (!state) return;
      state.dragLayerKey = key;
      if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
    });
    div.addEventListener("dragend", () => {
      if (!state) return;
      state.dragLayerKey = null;
      // подсветка могла остаться на любой строке панели (dragover без drop/dragleave)
      dom.overlay?.querySelectorAll(".fe-layer.drop-target")
        .forEach((el) => el.classList.remove("drop-target"));
    });
    div.addEventListener("dragover", (e) => { e.preventDefault(); div.classList.add("drop-target"); });
    div.addEventListener("dragleave", () => div.classList.remove("drop-target"));
    div.addEventListener("drop", (e) => {
      e.preventDefault();
      dom.overlay?.querySelectorAll(".fe-layer.drop-target")
        .forEach((el) => el.classList.remove("drop-target"));
      if (!state) return;
      const fromKey = state.dragLayerKey;
      state.dragLayerKey = null;
      if (!fromKey || fromKey === key || !state.geo) return;
      const parse = (k: string) => { const i = k.indexOf(":"); return { si: k.slice(0, i), p: k.slice(i + 1) || null }; };
      const a = parse(fromKey), b = parse(key);
      const parentOf = (x: { si: string; p: string | null }) => (x.p ? x.p.split(".").slice(0, -2).join(".") : null);
      if (a.si !== b.si || parentOf(a) !== parentOf(b)) return; // только внутри одного родителя
      const to = parseInt((b.p || "0").split(".").pop()!);
      state.geo.moveSibling({ secIdx: a.si === "null" ? null : Number(a.si), path: a.p }, to);
    });
  }
  if (fl.hidden) div.classList.add("flag-hidden");
  if (fl.locked) div.classList.add("flag-locked");
  if (state.sel.some((s) => s.ref.secIdx === ref.secIdx && s.ref.path === ref.path)) div.classList.add("selected");
  const icons: Record<string, string> = {
    navbar: "☰", hero: "◈", card: "▢", heading: "H", text: "T", button: "⬛", image: "▣",
    badge: "•", pricing: "$", faq: "?", footer: "⊥",
  };
  const icon = iconOverride || (irNode.type === "card" && irNode.role ? "◇" : icons[irNode.type]) || "◇";
  const source = sourceForRef(ref);
  if (source) {
    div.classList.add("fe-layer-sourced");
    div.style.setProperty("--source-color", source.color);
    div.title = `Источник: ${source.label}`;
  }
  div.innerHTML = (source ? `<span class="fe-source-dot" title="${esc(source.label)}"></span>` : "") +
    `<span class="fe-li">${icon}</span><span class="fe-ln">${esc(label)}</span>` +
    `<button class="fe-lbtn" data-flag="hidden" title="Скрыть/показать слой">${fl.hidden ? "🚫" : "👁"}</button>` +
    `<button class="fe-lbtn" data-flag="locked" title="Залочить/разлочить">${fl.locked ? "🔒" : "🔓"}</button>`;
  div.addEventListener("click", (e) => {
    if (!state) return;
    const btn = (e.target as HTMLElement).closest("[data-flag]") as HTMLElement | null;
    if (btn) { toggleLayerFlag(ref, btn.dataset.flag as "hidden" | "locked"); return; }
    if (refFlag(ref, "locked")) return; // залочен — не выделяется
    if (state.geo) state.geo.select(ref);
  });
  container.appendChild(div);
}

export function setLayerQuery(q: string) {
  if (!state) return;
  state.layerQuery = q.trim();
  renderLayers();
}

/* ---------- инспектор ---------- */

/* Фаза A2: инспектор — чистый React (frontend/src/editor/inspector/*). Контроллер
 * больше не строит DOM: renderInspector() лишь бампит inspectorTick в store,
 * InspectorPanel перечитывает сессию через getSession() и перемонтирует дерево.
 * Во время label scrub-drag тик подавляется — иначе перемонтирование убьёт capture. */
let inspScrubbing = false;

export function setInspScrubbing(v: boolean) {
  inspScrubbing = v;
}

export function getSession(): Session | null {
  return state;
}

export function renderInspector() {
  if (!state || inspScrubbing) return;
  ui.bumpInspector();
}

export function canonicalNode(ref: GeoRef): any {
  if (!state || !state.ir || ref.secIdx == null) return state && state.ir;
  let node = (state.ir.tree || [])[ref.secIdx];
  if (node && ref.path) node = getByPath(node, ref.path);
  return node || null;
}

function activeSelectionNode(sel: GeoSel) {
  if (!state) return null;
  return (state.sel.find((item) => item.ref.secIdx === sel.ref.secIdx && item.ref.path === sel.ref.path) || sel).node || null;
}

function finishResponsiveMutation() {
  if (!state) return;
  state.sel = [];
  renderCanvas();
  renderLayers();
  renderInspector();
  zoomFit();
}

export function resetResponsiveOverride(sel: GeoSel) {
  if (!state || state.viewport === "desktop") return;
  const target = canonicalNode(sel.ref);
  if (!target || !target.responsive || !target.responsive[state.viewport]) return;
  pushHistory();
  delete target.responsive[state.viewport];
  if (!Object.keys(target.responsive).length) delete target.responsive;
  finishResponsiveMutation();
}

export function applyResponsiveToAll(sel: GeoSel) {
  if (!state) return;
  const source = activeSelectionNode(sel);
  const target = canonicalNode(sel.ref);
  if (!source || !target) return;
  pushHistory();
  if (source.frame) target.frame = deepClone(source.frame);
  if (source.style) target.style = deepClone(source.style);
  if (source.styleBindings) target.styleBindings = deepClone(source.styleBindings);
  for (const override of Object.values<any>(target.responsive || {})) {
    if (!override || typeof override !== "object") continue;
    delete override.frame;
    delete override.style;
    delete override.styleBindings;
  }
  finishResponsiveMutation();
}

export function copyResponsiveTo(sel: GeoSel, viewport: string) {
  if (!state || !["desktop", "tablet", "mobile"].includes(viewport)) return;
  const source = activeSelectionNode(sel);
  const target = canonicalNode(sel.ref);
  if (!source || !target) return;
  pushHistory();
  if (viewport === "desktop") {
    if (source.frame) target.frame = deepClone(source.frame);
    if (source.style) target.style = deepClone(source.style);
    if (source.styleBindings) target.styleBindings = deepClone(source.styleBindings);
  } else {
    target.responsive = target.responsive || {};
    const override = target.responsive[viewport] || {};
    if (source.frame) override.frame = deepClone(source.frame);
    if (source.style) override.style = deepClone(source.style);
    if (source.styleBindings) override.styleBindings = deepClone(source.styleBindings);
    target.responsive[viewport] = override;
  }
  finishResponsiveMutation();
}

export function rerenderEditorCanvas() {
  if (!state || !dom.canvasInner) return;
  const inner = dom.canvasInner;
  IRRenderer.renderIR(inner, buildActiveIR(), { fit: false }); // _frames применяет сам рендерер
  applyLayerFlags();
  applyTransform();
  attachGeoEdit();
  applySourceLens();
  renderLayers();
  if (state.sel.length && state.geo) state.geo.selectMulti(state.sel.map((s) => s.ref));
  renderInspector();
}

/* ---------- клавиатура ---------- */

export function onKeydown(e: KeyboardEvent) {
  if (!state) return;
  const ae = document.activeElement as HTMLElement | null;
  if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName))) return;
  if (e.key === "v" || e.key === "V" || e.key === "м" || e.key === "М") setTool("select");
  if (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р") setTool("hand");
  if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") setTool("rect");
  if (e.key === "t" || e.key === "T" || e.key === "е" || e.key === "Е") setTool("text");
  if (e.key === "f" || e.key === "F" || e.key === "а" || e.key === "А") setTool("frame");
  if (e.key === "o" || e.key === "O" || e.key === "щ" || e.key === "Щ") setTool("ellipse");
  if (e.key === "l" || e.key === "L" || e.key === "д" || e.key === "Д") setTool("line");
  if (e.key === "i" || e.key === "I" || e.key === "ш" || e.key === "Ш") setTool("image");
  if ((e.key === "z" || e.key === "Z" || e.key === "я" || e.key === "Я") && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (e.shiftKey) redo(); else undo();
  }
  if ((e.key === "y" || e.key === "Y" || e.key === "н" || e.key === "Н") && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    redo();
  }
  // Esc: сначала отдаём GeoEdit (выход из контейнера / снятие выделения);
  // закрываем редактор, только если geoedit событие не поглотил
  if (e.key === "Escape") {
    if (state.geo && state.geo.consumeEscape()) return;
    close();
  }
}

/* ---------- утилиты ---------- */

function esc(s: any) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
