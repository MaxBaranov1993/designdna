/* DNA Editor — контроллер сессии: оркестрирует TS-движки (engine/renderer,
 * engine/geoedit, engine/irhistory) и React-каркас панелей. Селекторы и
 * семантика undo — контракт UI-тестов. */
import type { GeoHandle, GeoRef, GeoSel, IRHistoryHandle } from "./globals";
import { IRRenderer } from "../engine/renderer";
import { GeoEdit } from "../engine/geoedit";
import { IRHistory } from "../engine/irhistory";
import { DesignAIFontCatalog } from "../engine/fontCatalog";
import { findByKey, isSourceKeyPath, locateByKey, parentKeyByKey } from "../engine/sourcepath";
import type { AssistPreview, AssistRequest } from "./aiTypes";
import { EDITOR_ACTION_GROUPS } from "./actionInventory";
import { toast } from "../flow/toast";

/* ---------- DOM-refs: регистрируются React-компонентами ---------- */

export const dom = {
  overlay: null as HTMLDivElement | null,
  zoomLabel: null as HTMLElement | null,
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

export type EditorDraft = { baseRevision: number; draftRevision: number; ir: any };
export type NodeShim = {
  data: { ir: any };
  draft?: EditorDraft | null;
  currentRevision?: () => number;
  persistDraft?: (draft: EditorDraft) => void;
  clearDraft?: () => void;
  commitDraft?: (expectedRevision: number, ir: any) => boolean;
};

interface Session {
  ir: any;
  node: NodeShim;
  onSave: ((ir: any, expectedRevision: number) => boolean) | null;
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
  baseUpstreamRevision: number;
  draftRevision: number;
  persistedFingerprint: string;
  /* Отпечаток IR, совпадающий с нодой: расхождение = несохранённые правки */
  cleanFingerprint: string;
  sessionId: number;
  layerFlags: Record<string, { hidden?: boolean; locked?: boolean }>;
  layerQuery: string;
  dragLayerKey?: string | null;
  sourceContext: {
    registry: Record<string, { id: string; label: string; kind?: string; symbol?: string; confidence?: number }>;
    nodeSources: Record<string, string>;
    lensEnabled: boolean;
    activeSourceIds: Set<string>;
    layoutEvidence: Array<{ nodeRef: string; role: string; anchor: string; viewport: string; maxWidth: number; inlineGutter: number; confidence: number; basis: string }>;
  };
}

export type SmartAxisProposal = {
  id: string;
  targetWidth: number;
  gutter: number;
  referenceLabel: string;
  affectedLabels: string[];
  baseDraftRevision: number;
  baseSessionId: number;
  changeSet: Record<string, any>;
  patches: Array<{ sectionIndex: number; beforeFrame: any; afterFrame: any; beforeResponsive: any; afterResponsive: any }>;
};

export type EditorQualityProposal = {
  status: "loading" | "ready" | "error";
  passed: boolean;
  violations: Array<{ rule?: string; path?: string; message?: string; severity?: string }>;
  journal: Array<Record<string, any> | string>;
  fixedIr: any | null;
  baseDraftRevision: number;
  baseSessionId: number;
  error?: string;
};

export type HarmonizerProposal = {
  status: "loading" | "ready" | "error";
  sourceCount: number;
  tokens: any | null;
  harmonizedIr: any | null;
  baseDraftRevision: number;
  baseSessionId: number;
  error?: string;
};

export type ResponsiveAutopilotProposal = {
  status: "loading" | "ready" | "error";
  candidateIr: any | null;
  decisions: Array<{ kind: string; label: string; count: number }>;
  warnings: Array<{ rule?: string; path?: string; message?: string }>;
  baseDraftRevision: number;
  baseSessionId: number;
  error?: string;
};

export type IntentLock = "brand" | "content" | "geometry" | "appearance" | "responsive" | "source-link";

let state: Session | null = null;
let nextSessionId = 1;
let dnaPanelState: {
  tokens: any;
  originalTokens: any;
  normalization?: any;
  tailwindText?: string;
} | null = null;
let aiAssistState: AssistPreview | null = null;
let aiAssistBaseFingerprint: string | null = null;
let aiAssistScopeModeTouched = false;
let aiAssistAbort: AbortController | null = null;
let overlayCancelGen = 0;
let aiAssistFormState: AssistRequest = {
  prompt: "",
  action: "custom",
  scopeMode: "single",
  constraints: { allowContent: true, allowStyle: true, allowFrame: true, allowColor: true },
  provider: "openai",
  effort: "medium",
  designSystemSelection: "inherit",
};

/* UI-хуки подключает store (чтобы не было циклического импорта) */
let ui: { setTool: (t: string) => void; setSnap: (v: boolean) => void; setSnapStep: (v: SnapStep) => void; setOpen: (v: boolean) => void; bumpInspector: () => void; bumpSources: () => void; setSmartAxisProposal: (proposal: SmartAxisProposal | null) => void; setQualityProposal: (proposal: EditorQualityProposal | null) => void; setHarmonizerProposal: (proposal: HarmonizerProposal | null) => void; setResponsiveProposal: (proposal: ResponsiveAutopilotProposal | null) => void; setIntentLocksOpen: (open: boolean) => void; setSemanticSelectOpen: (open: boolean) => void; setAiBusy: (busy: boolean) => void; setAiError: (error: string) => void; setAiPreview: (preview: AssistPreview | null) => void; setAiProgress: (progress: import("./aiTypes").AssistProgress | null) => void; setCloseConfirm: (open: boolean) => void; setRulesOpen: (open: boolean) => void; setComponentsOpen: (open: boolean) => void } = {
  setTool: () => {},
  setSnap: () => {},
  setSnapStep: () => {},
  setOpen: () => {},
  bumpInspector: () => {},
  bumpSources: () => {},
  setSmartAxisProposal: () => {},
  setQualityProposal: () => {},
  setHarmonizerProposal: () => {},
  setResponsiveProposal: () => {},
  setIntentLocksOpen: () => {},
  setSemanticSelectOpen: () => {},
  setAiBusy: () => {},
  setAiError: () => {},
  setAiPreview: () => {},
  setAiProgress: () => {},
  setCloseConfirm: () => {},
  setRulesOpen: () => {},
  setComponentsOpen: () => {},
};
export function bindUi(hooks: typeof ui) {
  ui = hooks;
}

export function isActive() {
  return !!state;
}

export function getAiAssistFormState(): AssistRequest {
  return deepClone(aiAssistFormState);
}

/* Both desktop and the Python server honor the selected AI account. */
export const ASSIST_PROVIDERS = ["openai", "astra", "claude", "codex"] as const;

export function assistProviderAvailable(provider: string): boolean {
  return (ASSIST_PROVIDERS as readonly string[]).includes(provider);
}

export function setAiAssistFormState(next: Partial<AssistRequest>) {
  if (next.provider !== undefined && !assistProviderAvailable(String(next.provider))) next.provider = "openai";
  if (next.effort !== undefined && !["medium", "high", "max"].includes(String(next.effort))) next.effort = "medium";
  aiAssistFormState = {
    ...aiAssistFormState,
    ...next,
    constraints: { ...aiAssistFormState.constraints, ...(next.constraints || {}) },
  };
}

export function setAiAssistScopeMode(scopeMode: AssistRequest["scopeMode"]) {
  aiAssistScopeModeTouched = true;
  setAiAssistFormState({ scopeMode });
}

export function hasExplicitAiAssistScopeMode() {
  return aiAssistScopeModeTouched;
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
  if (ref && state.sourceContext.nodeSources[ref]) return state.sourceContext.nodeSources[ref];
  // дубликаты/вставки несут свежие ключи (rekeyCloneKeys): атрибуция —
  // через исходный ключ поддерева, сохранённый в sourceMeta.derivedFromKey
  const derived = node.sourceMeta && node.sourceMeta.derivedFromKey;
  if (derived && state.sourceContext.nodeSources[derived]) return state.sourceContext.nodeSources[derived];
  return null;
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

const ALL_INTENT_LOCKS: IntentLock[] = ["brand", "content", "geometry", "appearance", "responsive", "source-link"];

function nodeLocks(node: any): IntentLock[] {
  return Array.isArray(node?.constraints?.intentLocks) ? node.constraints.intentLocks.filter((lock: string) => ALL_INTENT_LOCKS.includes(lock as IntentLock)) : [];
}

function hasIntentLock(node: any, lock: IntentLock): boolean {
  return nodeLocks(state?.ir).includes(lock) || nodeLocks(node).includes(lock);
}

function selectedLockTargets(): any[] {
  if (!state) return [];
  const indices = [...new Set(state.sel.map((selection) => selection.ref.secIdx).filter((index): index is number => typeof index === "number"))];
  return indices.length ? indices.map((index) => state!.ir.tree?.[index]).filter(Boolean) : [state.ir];
}

export function getIntentLockView() {
  const targets = selectedLockTargets();
  return {
    scope: state?.sel.length ? `${targets.length} выбранн. блок(а)` : "Весь документ",
    locks: ALL_INTENT_LOCKS.filter((lock) => targets.length > 0 && targets.every((target) => nodeLocks(target).includes(lock))),
  };
}

export function setIntentLocks(locks: IntentLock[]) {
  if (!state) return;
  const targets = selectedLockTargets();
  pushHistory();
  targets.forEach((target) => {
    target.constraints = target.constraints || {};
    target.constraints.intentLocks = [...new Set(locks)].filter((lock) => ALL_INTENT_LOCKS.includes(lock));
  });
  persistDraft();
  ui.setIntentLocksOpen(false);
  rerenderEditorCanvas();
  updateUndoBtn();
}

export function closeIntentLocks() {
  ui.setIntentLocksOpen(false);
}

function applyIntentLockBadges() {
  if (!state || !dom.canvasInner) return;
  dom.canvasInner.querySelectorAll<HTMLElement>(".intent-locked").forEach((element) => {
    element.classList.remove("intent-locked");
    delete element.dataset.intentLocks;
  });
  (state.ir.tree || []).forEach((section: any, index: number) => {
    const locks = [...new Set([...nodeLocks(state!.ir), ...nodeLocks(section)])];
    const element = domAtCanvas({ secIdx: index, path: null });
    if (!element || !locks.length) return;
    element.classList.add("intent-locked");
    element.dataset.intentLocks = `🔒 ${locks.length}`;
  });
}

function preserveLockedFacets(original: any, candidate: any) {
  if (!original || !candidate) return candidate;
  const preserveNode = (before: any, after: any) => {
    if (!before || !after) return;
    if (hasIntentLock(before, "geometry")) after.frame = deepClone(before.frame);
    if (hasIntentLock(before, "responsive")) after.responsive = deepClone(before.responsive);
    if (hasIntentLock(before, "appearance") || hasIntentLock(before, "brand")) {
      after.style = deepClone(before.style);
      after.styleBindings = deepClone(before.styleBindings);
    }
    if (hasIntentLock(before, "content")) {
      after.props = deepClone(before.props);
      for (const key of ["text", "title", "label", "placeholder", "src", "alt"]) if (key in before) after[key] = deepClone(before[key]);
    }
    if (hasIntentLock(before, "source-link")) {
      after.sourceKey = before.sourceKey;
      after.provenance = deepClone(before.provenance);
    }
    (before.children || []).forEach((child: any, index: number) => preserveNode(child, after.children?.[index]));
  };
  if (hasIntentLock(original, "brand") || hasIntentLock(original, "appearance")) candidate.tokens = deepClone(original.tokens);
  (original.tree || []).forEach((section: any, index: number) => preserveNode(section, candidate.tree?.[index]));
  return candidate;
}

function searchableNodeText(node: any): string {
  const values = [node?.type, node?.id, node?.text, node?.title, node?.label, node?.props?.heading, node?.props?.subheading, node?.props?.text];
  return values.filter(Boolean).join(" ").toLowerCase();
}

export function semanticSelect(query: string): number {
  if (!state || !state.geo) return 0;
  const normalized = query.trim().toLowerCase();
  if (!normalized) return 0;
  const sourceIds = Object.values(state.sourceContext.registry)
    .filter((source) => [source.id, source.label, source.symbol].filter(Boolean).some((value) => normalized.includes(String(value).toLowerCase())))
    .map((source) => source.id);
  const wantsButton = /cta|кноп|button|действи/.test(normalized);
  const wantsHeading = /заголов|heading|title|headline/.test(normalized);
  const wantsImage = /изображ|картин|фото|image|media/.test(normalized);
  const wantsCard = /карточ|card/.test(normalized);
  const wantsText = /текст|text|copy/.test(normalized);
  const semanticRequested = wantsButton || wantsHeading || wantsImage || wantsCard || wantsText;
  const refs: GeoRef[] = [];
  const add = (ref: GeoRef) => {
    if (refs.length >= 200 || refs.some((item) => item.secIdx === ref.secIdx && item.path === ref.path)) return;
    refs.push(ref);
  };
  (state.ir.tree || []).forEach((section: any, secIdx: number) => {
    const sectionSource = sourceIdForNode(section);
    if (sourceIds.length && (!sectionSource || !sourceIds.includes(sectionSource))) return;
    const props = section.props || {};
    if (wantsButton) {
      if (props.cta) add({ secIdx, path: "props.cta" });
      if (props.ctaPrimary) add({ secIdx, path: "props.ctaPrimary" });
      if (props.ctaSecondary) add({ secIdx, path: "props.ctaSecondary" });
    }
    if (wantsHeading && props.heading) add({ secIdx, path: "props.heading" });
    if (wantsImage && props.media) add({ secIdx, path: "props.media" });
    if (wantsText) {
      if (props.text) add({ secIdx, path: "props.text" });
      if (props.subheading) add({ secIdx, path: "props.subheading" });
    }
    // Адресация должна совпадать с data-ir-path рендера (annotatePaths):
    // внутри source-block/dom-capture секций путь — sourceKey, иначе числовой.
    const sourceSec = section.type === "source-block" || section.variant === "dom-capture";
    const visit = (node: any, path: string) => {
      const sourceId = sourceIdForNode(node) || sectionSource;
      if (sourceIds.length && (!sourceId || !sourceIds.includes(sourceId))) return;
      const type = String(node?.type || "").toLowerCase();
      const semanticMatch = (wantsButton && type === "button") || (wantsHeading && type === "heading") ||
        (wantsImage && ["image", "media"].includes(type)) || (wantsCard && type === "card") ||
        (wantsText && ["text", "heading"].includes(type));
      if (semanticMatch || (!semanticRequested && !sourceIds.length && searchableNodeText(node).includes(normalized))) add({ secIdx, path });
      (node.children || []).forEach((child: any, index: number) =>
        visit(child, sourceSec && child.sourceKey ? child.sourceKey : `${path}.children.${index}`));
    };
    (section.children || []).forEach((child: any, index: number) =>
      visit(child, sourceSec && child.sourceKey ? child.sourceKey : `children.${index}`));
    if (!semanticRequested && sourceIds.length) add({ secIdx, path: null });
    if (!semanticRequested && !sourceIds.length && searchableNodeText(section).includes(normalized)) add({ secIdx, path: null });
  });
  state.geo.selectMulti(refs);
  state.sel = refs.map((ref) => ({ ref, node: canonicalNode(ref), label: searchableNodeText(canonicalNode(ref)).slice(0, 60) })) as GeoSel[];
  renderLayers();
  renderInspector();
  updateAlignVisibility();
  applySourceLens();
  applyIntentLockBadges();
  return refs.length;
}

export function closeSemanticSelect() {
  ui.setSemanticSelectOpen(false);
}

function getByPath(obj: any, path: string) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

const FONT_CATALOG = DesignAIFontCatalog;
const FONT_FAMILIES = FONT_CATALOG
  ? FONT_CATALOG.families
  : ["Inter", "Sora", "Manrope", "Playfair Display", "Space Grotesk", "DM Sans", "IBM Plex Mono", "Montserrat"];

function fontOptionsHtml(selected?: string, autoLabel?: string | null) {
  const auto = autoLabel == null ? "" : `<option value="">${esc(autoLabel)}</option>`;
  if (!FONT_CATALOG || !FONT_CATALOG.groups) {
    return auto + FONT_FAMILIES.map((ff) => `<option value="${esc(ff)}" ${ff === selected ? "selected" : ""}>${esc(ff)}</option>`).join("");
  }
  return auto + FONT_CATALOG.groups
    .map((group) =>
      `<optgroup label="${esc(group.label)}">${group.fonts
        .map((ff) => `<option value="${esc(ff)}" ${ff === selected ? "selected" : ""}>${esc(ff)}</option>`)
        .join("")}</optgroup>`,
    )
    .join("");
}


/* ---------- тулбар / инструменты ---------- */

/* Инструменты, которые geoedit уже умеет; ellipse/line/image добавляются в движок
 * параллельно — rail зовёт setTool всегда, а при отказе движка откатываемся на select. */
const DRAW_TOOLS = new Set(["rect", "text", "frame", "ellipse", "line", "image"]);

export function setTool(tool: string) {
  if (!state) return;
  state.tool = tool;
  ui.setTool(tool);
  dom.overlay?.querySelectorAll<HTMLElement>(".fe-rail [data-tool]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === tool);
  });
  // Курсор — единственный признак включённого режима на самом холсте:
  // без него рисующий инструмент неотличим от обычного выделения.
  if (dom.canvas) dom.canvas.style.cursor = tool === "hand" ? "grab"
    : DRAW_TOOLS.has(tool) ? "crosshair" : "default";
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

/* Привязка к сетке: источник истины здесь (нужен drag-коммиту), зеркалится
 * в UI-стор через ui.setSnap/setSnapStep (панели читают $editorUi). */
export type SnapStep = 4 | 8 | 12 | 16;
let snapEnabled = true;
let snapStepPx: SnapStep = 8;
export function setSnap(v: boolean) {
  snapEnabled = v;
  ui.setSnap(v);
}
export function setSnapStep(v: number) {
  snapStepPx = ([4, 8, 12, 16].includes(v) ? v : 8) as SnapStep;
  ui.setSnapStep(snapStepPx);
}

export function setViewport(viewport: string) {
  if (!state || !["desktop", "tablet", "mobile"].includes(viewport)) return;
  // tablet 834 — только ширина превью в редакторе; responsive-материализация IR живёт на 768
  const widths: Record<string, number> = { desktop: 1440, tablet: 834, mobile: 390 };
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
    persistDraft();
  }
  dom.viewports?.querySelectorAll("[data-viewport]").forEach((b) => {
    const on = (b as HTMLElement).dataset.viewport === viewport;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
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
  else if (act === "close") requestClose();
  else if (act === "close-discard") discardAndClose();
  else if (act === "close-stay") dismissCloseConfirm();
  else if (act === "close-save") saveAndClose();
  else if (act === "undo") undo();
  else if (act === "redo") redo();
  else if (act === "style-dna") openStyleDnaInspector();
  else if (act === "smart-axis") planSmartAxis();
  else if (act === "quality-gate") void planQualityGate();
  else if (act === "harmonize") void planHarmonizer();
  else if (act === "responsive-autopilot") void planResponsiveAutopilot();
  else if (act === "intent-locks") ui.setIntentLocksOpen(true);
  else if (act === "semantic-select") ui.setSemanticSelectOpen(true);
  else if (act === "rules") ui.setRulesOpen(true);
  else if (act === "close-rules") ui.setRulesOpen(false);
  else if (act === "components") ui.setComponentsOpen(true);
  else if (act === "close-components") ui.setComponentsOpen(false);
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
  else if (act === "stretch-width") state.geo && state.geo.stretchWidth();
  else if (act === "reset-frame") state.geo && state.geo.resetFrame();
}

function stableRevisionId(): string {
  return `revision.editor-${state?.baseUpstreamRevision ?? 0}-${state?.draftRevision ?? 0}`;
}

function proposalStillCurrent(baseSessionId: number, baseDraftRevision: number): boolean {
  return !!state && state.sessionId === baseSessionId && state.draftRevision === baseDraftRevision;
}

function persistDraft(clearProposals = true) {
  if (!state) return;
  const fingerprint = JSON.stringify(state.ir);
  if (fingerprint === state.persistedFingerprint) return;
  state.draftRevision += 1;
  state.persistedFingerprint = fingerprint;
  state.node.persistDraft?.({
    baseRevision: state.baseUpstreamRevision,
    draftRevision: state.draftRevision,
    ir: deepClone(state.ir),
  });
  if (clearProposals) {
    ui.setSmartAxisProposal(null);
    ui.setQualityProposal(null);
    ui.setHarmonizerProposal(null);
    ui.setResponsiveProposal(null);
  }
}

function sectionLabel(section: any, index: number): string {
  return section?.props?.heading || section?.semantic?.label || section?.id || `Блок ${index + 1}`;
}

/** AI Layout Director: evidence chooses the axis; the mutation stays deterministic,
 * previewable and reversible through SemanticChangeSet + normal editor history. */
export function planSmartAxis() {
  if (!state) return;
  const viewport = state.viewport || "desktop";
  const evidence = state.sourceContext.layoutEvidence
    .filter((item) => item && Number(item.maxWidth) > 0 && (item.viewport === viewport || item.viewport === "desktop"))
    .sort((a, b) => Number(b.role === "page-content") - Number(a.role === "page-content") || Number(b.confidence || 0) - Number(a.confidence || 0));
  const best = evidence[0];
  const targetWidth = Math.max(320, Math.min(1920, Math.round(Number(best?.maxWidth || 1120))));
  const gutter = Math.max(0, Math.round(Number(best?.inlineGutter || 24)));
  const selected = new Set(state.sel.map((item) => item.ref.secIdx).filter((value) => value != null));
  const candidates = (state.ir.tree || [])
    .map((section: any, sectionIndex: number) => ({ section, sectionIndex }))
    .filter(({ section, sectionIndex }: any) => {
      if (selected.size && !selected.has(sectionIndex)) return false;
      if (hasIntentLock(section, "geometry") || hasIntentLock(section, "responsive")) return false;
      return !(section.type === "source-block" || section.variant === "dom-capture" || (section.frame?.layout === "free" && section.children?.length));
    });
  if (!candidates.length) {
    ui.setSmartAxisProposal(null);
    return;
  }
  const stamp = Date.now();
  const patches = candidates.map(({ section, sectionIndex }: any) => {
    const afterFrame = { ...(section.frame || {}), contentMaxWidth: targetWidth, contentGutter: gutter };
    const afterResponsive = deepClone(section.responsive || {});
    for (const [name, width, safeGutter] of [["tablet", 768, 24], ["mobile", 390, 16]] as Array<[string, number, number]>) {
      const override = afterResponsive[name] || {};
      override.frame = { ...(override.frame || {}), contentMaxWidth: Math.min(targetWidth, width - safeGutter * 2), contentGutter: safeGutter };
      afterResponsive[name] = override;
    }
    return { sectionIndex, beforeFrame: deepClone(section.frame || null), afterFrame, beforeResponsive: deepClone(section.responsive || null), afterResponsive };
  });
  const operations: Array<Record<string, any>> = patches.map((patch: SmartAxisProposal["patches"][number], index: number) => ({
    id: `axis.bind.${index + 1}`,
    kind: "bind-layout-axis",
    target: state!.ir.tree[patch.sectionIndex].sourceKey || state!.ir.tree[patch.sectionIndex].id,
    path: "/frame/contentMaxWidth",
    payload: { axis: "content-width", maxWidth: targetWidth, gutter, viewport },
  }));
  const inverseOperations: Array<Record<string, any>> = patches.map((patch: SmartAxisProposal["patches"][number], index: number) => ({
    id: `axis.unbind.${index + 1}`,
    inverseOf: operations[index].id,
    kind: "unbind-layout-axis",
    target: operations[index].target,
    path: "/frame/contentMaxWidth",
    payload: { frame: patch.beforeFrame, responsive: patch.beforeResponsive },
  }));
  const sourceId = best ? state.sourceContext.nodeSources[best.nodeRef] : null;
  const referenceLabel = sourceId ? state.sourceContext.registry[sourceId]?.label : null;
  ui.setSmartAxisProposal({
    id: `change.smart-axis.${stamp}`,
    targetWidth,
    gutter,
    referenceLabel: referenceLabel || (best ? "лучшее найденное ограничение" : "безопасная дизайн-сетка"),
    affectedLabels: candidates.map(({ section, sectionIndex }: any) => sectionLabel(section, sectionIndex)),
    baseDraftRevision: state.draftRevision,
    baseSessionId: state.sessionId,
    patches,
    changeSet: {
      version: "semantic-change-set/1.0",
      id: `change.smart-axis.${stamp}`,
      baseRevisionId: stableRevisionId(),
      intent: "Выровнять внутреннюю ширину выбранных блоков по общей смысловой оси",
      scope: operations.map((operation: Record<string, any>) => operation.target),
      preconditions: [{ kind: "revision-match", expected: stableRevisionId() }],
      operations,
      inverseOperations,
      validations: ["schema", "references", "responsive", "overflow", "visual"].map((kind) => ({ kind, status: "pending" })),
      atomic: true,
      status: "draft",
      actor: "ai-layout-director",
      createdAt: new Date().toISOString(),
      explanation: `Единая ось ${targetWidth}px получена из ${referenceLabel || "layout evidence"}; фон секций остаётся full-bleed.`,
    },
  });
}

export function dismissSmartAxisProposal() {
  overlayCancelGen += 1;
  ui.setSmartAxisProposal(null);
}

export function applySmartAxisProposal(proposal: SmartAxisProposal) {
  if (!state || !proposal || proposal.baseSessionId !== state.sessionId || proposal.baseDraftRevision !== state.draftRevision || proposal.changeSet.baseRevisionId !== stableRevisionId()) return;
  pushHistory();
  proposal.patches.forEach((patch) => {
    const section = state!.ir.tree?.[patch.sectionIndex];
    if (!section) return;
    section.frame = deepClone(patch.afterFrame);
    section.responsive = deepClone(patch.afterResponsive);
  });
  persistDraft(false);
  ui.setSmartAxisProposal(null);
  rerenderEditorCanvas();
  updateUndoBtn();
}

export async function planQualityGate() {
  if (!state) return;
  const cancelGen = ++overlayCancelGen;
  const baseDraftRevision = state.draftRevision;
  const baseSessionId = state.sessionId;
  const baseIr = deepClone(state.ir);
  ui.setQualityProposal({ status: "loading", passed: false, violations: [], journal: [], fixedIr: null, baseDraftRevision, baseSessionId });
  try {
    const response = await fetch("/api/quality-gate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: sanitizeIrForPost(baseIr), fix: true }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    if (cancelGen !== overlayCancelGen) return;
    if (!proposalStillCurrent(baseSessionId, baseDraftRevision)) {
      if (state?.sessionId === baseSessionId) ui.setQualityProposal({ status: "error", passed: false, violations: [], journal: [], fixedIr: null, baseDraftRevision, baseSessionId, error: "Макет изменился во время проверки. Запустите проверку ещё раз." });
      return;
    }
    ui.setQualityProposal({
      status: "ready",
      passed: Boolean(data.passed),
      violations: Array.isArray(data.violations) ? data.violations : [],
      journal: Array.isArray(data.journal) ? data.journal : [],
      fixedIr: data.fixed_ir ? preserveLockedFacets(baseIr, deepClone(data.fixed_ir)) : null,
      baseDraftRevision,
      baseSessionId,
    });
  } catch (error) {
    if (cancelGen !== overlayCancelGen) return;
    if (state?.sessionId === baseSessionId) ui.setQualityProposal({ status: "error", passed: false, violations: [], journal: [], fixedIr: null, baseDraftRevision, baseSessionId, error: (error as Error).message });
  }
}

export function dismissQualityProposal() {
  overlayCancelGen += 1;
  ui.setQualityProposal(null);
}

export function applyQualityProposal(proposal: EditorQualityProposal) {
  if (!state || proposal.status !== "ready" || !proposal.fixedIr || proposal.baseSessionId !== state.sessionId || proposal.baseDraftRevision !== state.draftRevision) return;
  pushHistory();
  state.ir = deepClone(proposal.fixedIr);
  persistDraft(false);
  ui.setQualityProposal(null);
  rerenderEditorCanvas();
  updateUndoBtn();
}

export async function planHarmonizer() {
  if (!state) return;
  const cancelGen = ++overlayCancelGen;
  const baseDraftRevision = state.draftRevision;
  const baseSessionId = state.sessionId;
  const baseIr = deepClone(state.ir);
  const sourceCount = Object.keys(state.sourceContext.registry).length || 1;
  ui.setHarmonizerProposal({ status: "loading", sourceCount, tokens: null, harmonizedIr: null, baseDraftRevision, baseSessionId });
  try {
    const cleanIr = sanitizeIrForPost(baseIr);
    const extractResponse = await fetch("/api/style-dna/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: cleanIr }),
    });
    const extracted = await extractResponse.json();
    if (!extractResponse.ok) throw new Error(extracted.detail || `HTTP ${extractResponse.status}`);
    if (cancelGen !== overlayCancelGen) return;
    if (!proposalStillCurrent(baseSessionId, baseDraftRevision)) {
      if (state?.sessionId === baseSessionId) ui.setHarmonizerProposal({ status: "error", sourceCount, tokens: null, harmonizedIr: null, baseDraftRevision, baseSessionId, error: "Макет изменился во время анализа. Запустите Harmonizer ещё раз." });
      return;
    }
    const applyResponse = await fetch("/api/style-dna/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: cleanIr, tokens: extracted.tokens }),
    });
    const applied = await applyResponse.json();
    if (!applyResponse.ok) throw new Error(applied.detail || `HTTP ${applyResponse.status}`);
    if (cancelGen !== overlayCancelGen) return;
    if (!proposalStillCurrent(baseSessionId, baseDraftRevision)) {
      if (state?.sessionId === baseSessionId) ui.setHarmonizerProposal({ status: "error", sourceCount, tokens: null, harmonizedIr: null, baseDraftRevision, baseSessionId, error: "Макет изменился во время применения Style DNA. Запустите Harmonizer ещё раз." });
      return;
    }
    const harmonizedIr = applied.ir ? preserveLockedFacets(baseIr, deepClone(applied.ir)) : null;
    ui.setHarmonizerProposal({ status: "ready", sourceCount, tokens: extracted.tokens || {}, harmonizedIr, baseDraftRevision, baseSessionId });
  } catch (error) {
    if (cancelGen !== overlayCancelGen) return;
    if (state?.sessionId === baseSessionId) ui.setHarmonizerProposal({ status: "error", sourceCount, tokens: null, harmonizedIr: null, baseDraftRevision, baseSessionId, error: (error as Error).message });
  }
}

export function dismissHarmonizerProposal() {
  overlayCancelGen += 1;
  ui.setHarmonizerProposal(null);
}

export function applyHarmonizerProposal(proposal: HarmonizerProposal) {
  if (!state || proposal.status !== "ready" || !proposal.harmonizedIr || proposal.baseSessionId !== state.sessionId || proposal.baseDraftRevision !== state.draftRevision) return;
  pushHistory();
  state.ir = deepClone(proposal.harmonizedIr);
  persistDraft(false);
  ui.setHarmonizerProposal(null);
  rerenderEditorCanvas();
  updateUndoBtn();
}

function responsiveOverride(node: any, viewport: "tablet" | "mobile") {
  node.responsive = node.responsive || {};
  node.responsive[viewport] = node.responsive[viewport] || {};
  node.responsive[viewport].frame = { ...(node.responsive[viewport].frame || {}) };
  return node.responsive[viewport];
}

export async function planResponsiveAutopilot() {
  if (!state) return;
  const cancelGen = ++overlayCancelGen;
  const baseDraftRevision = state.draftRevision;
  const baseSessionId = state.sessionId;
  const baseIr = deepClone(state.ir);
  ui.setResponsiveProposal({ status: "loading", candidateIr: null, decisions: [], warnings: [], baseDraftRevision, baseSessionId });
  try {
    const candidate = deepClone(sanitizeIrForPost(baseIr));
    const counters = { rails: 0, stacks: 0, widths: 0, type: 0, untouched: 0 };
    candidate.responsive = candidate.responsive || { viewports: {} };
    candidate.responsive.viewports = {
      ...(candidate.responsive.viewports || {}),
      desktop: { width: 1440, height: 900, ...(candidate.responsive.viewports?.desktop || {}) },
      tablet: { width: 768, height: 1024, ...(candidate.responsive.viewports?.tablet || {}) },
      mobile: { width: 390, height: 844, ...(candidate.responsive.viewports?.mobile || {}) },
    };
    const adaptNode = (node: any, allowStructural = true) => {
      if (!node || typeof node !== "object") return;
      const frame = node.frame || {};
      for (const [viewport, width, gutter] of [["tablet", 768, 24], ["mobile", 390, 16]] as Array<["tablet" | "mobile", number, number]>) {
        const override = responsiveOverride(node, viewport);
        const nextFrame = override.frame;
        if (typeof frame.width === "number" && frame.width > width - gutter * 2) {
          nextFrame.width = "fill";
          nextFrame.maxWidth = width - gutter * 2;
          counters.widths += 1;
        }
        if (allowStructural && viewport === "mobile" && frame.layout === "auto" && frame.direction === "row" && (node.children || []).length > 1) {
          nextFrame.direction = "column";
          nextFrame.wrap = false;
          nextFrame.gap = Math.min(Number(frame.gap || 16), 24);
          counters.stacks += 1;
        }
        const fontSize = Number(node.style?.fontSize || 0);
        if (viewport === "mobile" && fontSize > 30) {
          override.style = { ...(override.style || {}), fontSize: Math.max(28, Math.min(34, Math.round(fontSize * .82))) };
          counters.type += 1;
        }
      }
      (node.children || []).forEach((child: any) => adaptNode(child, allowStructural));
    };
    (candidate.tree || []).forEach((section: any) => {
      if (hasIntentLock(section, "responsive") || hasIntentLock(section, "geometry")) {
        counters.untouched += 1;
        return;
      }
      const sourceReproduction = section.type === "source-block" || section.variant === "dom-capture";
      if (sourceReproduction) {
        counters.untouched += 1;
        return;
      }
      const freeComposition = section.frame?.layout === "free" && section.children?.length;
      for (const [viewport, width, gutter] of [["tablet", 768, 24], ["mobile", 390, 16]] as Array<["tablet" | "mobile", number, number]>) {
        const override = responsiveOverride(section, viewport);
        override.frame.contentMaxWidth = Math.min(Number(section.frame?.contentMaxWidth || 1120), width - gutter * 2);
        override.frame.contentGutter = gutter;
        if (freeComposition) {
          override.frame.direction = "column";
          override.frame.wrap = false;
          override.frame.height = "hug";
          override.frame.gap = viewport === "mobile" ? 20 : 28;
          override.frame.padding = viewport === "mobile" ? [48, gutter, 56, gutter] : [64, gutter, 72, gutter];
          (section.children || []).forEach((child: any) => {
            const childOverride = responsiveOverride(child, viewport);
            childOverride.frame.absolute = false;
            childOverride.frame.width = ["button", "badge", "icon"].includes(child.type) ? "hug" : "fill";
            childOverride.frame.maxWidth = width - gutter * 2;
            if (["heading", "text", "badge", "button", "icon"].includes(child.type)) {
              childOverride.frame.height = "hug";
            } else if (["image", "video", "media"].includes(child.type)
              && typeof child.frame?.width === "number" && typeof child.frame?.height === "number") {
              const proportionalHeight = Math.round((width - gutter * 2) * child.frame.height / child.frame.width);
              childOverride.frame.height = Math.max(180, Math.min(viewport === "mobile" ? 280 : 440, proportionalHeight));
            }
          });
          counters.stacks += 1;
        }
        counters.rails += 1;
      }
      adaptNode(section);
    });
    const response = await fetch("/api/quality-gate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: candidate, fix: false }),
    });
    const quality = await response.json();
    if (!response.ok) throw new Error(quality.detail || `HTTP ${response.status}`);
    if (cancelGen !== overlayCancelGen) return;
    if (!proposalStillCurrent(baseSessionId, baseDraftRevision)) {
      if (state?.sessionId === baseSessionId) ui.setResponsiveProposal({ status: "error", candidateIr: null, decisions: [], warnings: [], baseDraftRevision, baseSessionId, error: "Макет изменился во время адаптации. Запустите Autopilot ещё раз." });
      return;
    }
    const decisions = [
      { kind: "rails", label: "Контентные оси", count: counters.rails },
      { kind: "stacks", label: "Row → column", count: counters.stacks },
      { kind: "widths", label: "Защита от overflow", count: counters.widths },
      { kind: "type", label: "Мобильная типографика", count: counters.type },
      { kind: "preserve", label: "Импорт без изменений", count: counters.untouched },
    ].filter((item) => item.count > 0);
    ui.setResponsiveProposal({ status: "ready", candidateIr: candidate, decisions, warnings: Array.isArray(quality.violations) ? quality.violations : [], baseDraftRevision, baseSessionId });
  } catch (error) {
    if (cancelGen !== overlayCancelGen) return;
    if (state?.sessionId === baseSessionId) ui.setResponsiveProposal({ status: "error", candidateIr: null, decisions: [], warnings: [], baseDraftRevision, baseSessionId, error: (error as Error).message });
  }
}

export function dismissResponsiveProposal() {
  overlayCancelGen += 1;
  ui.setResponsiveProposal(null);
}

export function applyResponsiveProposal(proposal: ResponsiveAutopilotProposal) {
  if (!state || proposal.status !== "ready" || !proposal.candidateIr || proposal.baseSessionId !== state.sessionId || proposal.baseDraftRevision !== state.draftRevision) return;
  pushHistory();
  state.ir = deepClone(proposal.candidateIr);
  persistDraft(false);
  ui.setResponsiveProposal(null);
  rerenderEditorCanvas();
  updateUndoBtn();
}

/* ---------- открытие / закрытие ---------- */

/** Фаза 1 открытия: состояние + не-layout части (вызывается из store.openEditor). */
/** Re-apply toolbar state when a lazily mounted Svelte toolbar registers its DOM refs. */
export function syncToolbarState() {
  if (!state) return;
  const responsive = !!(state.ir && state.ir.responsive && state.ir.responsive.viewports);
  if (dom.viewports) dom.viewports.hidden = !responsive;
  if (dom.responsiveSep) dom.responsiveSep.hidden = !responsive;
  dom.viewports?.querySelectorAll("[data-viewport]").forEach((button) => {
    const on = (button as HTMLElement).dataset.viewport === state?.viewport;
    button.classList.toggle("active", on);
    button.setAttribute("aria-pressed", String(on));
  });
  if (dom.viewportWidth) dom.viewportWidth.value = String(state.previewWidth);
}

export function open(
  node: NodeShim,
  onSave: (ir: any, expectedRevision: number) => boolean,
  onClose: (saved: boolean) => void,
  sourceContext?: { registry?: Record<string, any>; nodeSources?: Record<string, string>; layoutEvidence?: any[] },
) {
  aiAssistState = null;
  aiAssistBaseFingerprint = null;
  aiAssistScopeModeTouched = false;
  aiAssistFormState = {
    prompt: "", action: "custom", scopeMode: "single",
    constraints: { allowContent: true, allowStyle: true, allowFrame: true, allowColor: true },
  };
  const restoredDraft = node.draft && node.draft.ir ? node.draft : null;
  const upstreamRevision = node.currentRevision ? node.currentRevision() : 0;
  const startingIr = deepClone(restoredDraft ? restoredDraft.ir : node.data.ir);
  if (!startingIr) return false;
  state = {
    ir: startingIr,
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
    baseUpstreamRevision: restoredDraft ? restoredDraft.baseRevision : upstreamRevision,
    draftRevision: restoredDraft ? restoredDraft.draftRevision : 0,
    persistedFingerprint: JSON.stringify(startingIr),
    cleanFingerprint: "",
    sessionId: nextSessionId++,
    layerFlags: {}, // refKey -> {hidden, locked}; сессия редактора, не часть IR
    layerQuery: "",
    sourceContext: {
      registry: sourceContext?.registry || {},
      nodeSources: sourceContext?.nodeSources || {},
      lensEnabled: Object.keys(sourceContext?.registry || {}).length > 1,
      activeSourceIds: new Set(),
      layoutEvidence: sourceContext?.layoutEvidence || [],
    },
  };
  const upgraded = upgradeSourceNesting(state.ir);
  if (upgraded) persistDraft();
  // Чистая база — IR после нормализации открытия (иначе апгрейд вложенности
  // считался бы правкой); восстановленный черновик по определению грязный.
  state.cleanFingerprint = restoredDraft ? JSON.stringify(node.data.ir ?? null) : JSON.stringify(state.ir);
  const st = state;
  const responsive = !!(st.ir && st.ir.responsive && st.ir.responsive.viewports);
  // вьюпорт из графа: Page/Source Import прокидывают meta.activeViewport вниз —
  // редактор открывается на том же устройстве, что показывает нода
  const irVp = st.ir && st.ir.meta && st.ir.meta.activeViewport;
  if (responsive && ["desktop", "tablet", "mobile"].includes(irVp)) st.viewport = irVp;
  const viewportMeta = responsive ? st.ir.responsive.viewports[st.viewport] : null;
  st.previewWidth =
    (viewportMeta && viewportMeta.width ? viewportMeta.width : st.ir.frame && st.ir.frame.width) || 1440;
  syncToolbarState();
  if (dom.search) dom.search.value = "";
  return true;
}

/** Фаза 2 открытия: вызывается EditorApp, когда overlay уже display:flex
 *  (zoomFit/линейки требуют реальной раскладки). */
export function finishOpen() {
  if (!state) return;
  if (typeof window !== "undefined") window.__editorActions = EDITOR_ACTION_GROUPS;
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
    if (sec?.type === "contact-form") {
      sec.props = sec.props || {};
      if (!sec.props.submit || typeof sec.props.submit !== "object") {
        sec.props.submit = { type: "button", role: "form-submit" };
        changed = true;
      }
      (Array.isArray(sec.props.fields) ? sec.props.fields : []).forEach((field: any) => {
        if (!field || typeof field !== "object") return;
        if (!field.parts || typeof field.parts !== "object") {
          field.parts = {};
          changed = true;
        }
        if (!field.parts.label || typeof field.parts.label !== "object") {
          field.parts.label = { type: "text", role: "form-label" };
          changed = true;
        }
        if (!field.parts.control || typeof field.parts.control !== "object") {
          field.parts.control = { type: "input", role: "form-control" };
          changed = true;
        }
      });
    }
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
  setDnaActionsEnabled(false);
  dom.dnaBody.innerHTML = '<div class="fe-dna-empty">Загрузка токенов…</div>';
  const existing = state.ir && state.ir.tokens;
  if (existing && existing.semantic && existing.primitives) {
    dnaPanelState = { tokens: deepClone(existing), originalTokens: deepClone(existing) };
    renderStyleDnaPanel();
  } else {
    void extractStyleDnaFromServer();
  }
}

function setDnaActionsEnabled(enabled: boolean) {
  dom.overlay?.querySelectorAll<HTMLButtonElement>('[data-act="reset-style-dna"], [data-act="apply-style-dna"]').forEach((btn) => {
    btn.disabled = !enabled;
  });
}

export function closeStyleDnaInspector() {
  dom.dnaPanel?.classList.remove("open");
  dnaPanelState = null;
  setDnaActionsEnabled(false);
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
    setDnaActionsEnabled(false);
    if (dom.dnaBody) {
      dom.dnaBody.innerHTML = `<div class="fe-dna-empty fe-dna-err">Ошибка загрузки: ${esc((e as Error).message)}</div>`;
    }
  }
}

async function applyStyleDnaFromInspector() {
  if (!state || !dnaPanelState) return;
  const baseDraftRevision = state.draftRevision;
  const baseSessionId = state.sessionId;
  const baseIr = deepClone(state.ir);
  const foot = dom.dnaFoot;
  if (foot) foot.textContent = "Применение…";
  setDnaActionsEnabled(false);
  try {
    const resp = await fetch("/api/style-dna/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ir: sanitizeIrForPost(baseIr), tokens: deepClone(dnaPanelState.tokens) }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "HTTP " + resp.status);
    if (!proposalStillCurrent(baseSessionId, baseDraftRevision)) throw new Error("Макет изменился во время применения Style DNA. Повторите операцию.");
    pushHistory();
    state.ir = data.ir || state.ir;
    persistDraft();
    dnaPanelState.originalTokens = deepClone(dnaPanelState.tokens);
    rerenderEditorCanvas();
    if (foot) foot.textContent = "Токены применены";
    setDnaActionsEnabled(true);
    setTimeout(() => { if (foot) foot.textContent = ""; }, 2000);
  } catch (e) {
    setDnaActionsEnabled(true);
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
      html += `<div class="fe-dna-row"><span class="fe-dna-primitive" style="color:${colorHex(c)}">■</span><span class="fe-dna-primitive">${esc(c)}</span></div>`;
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
    html += `<div class="fe-dna-primitive">${primitives.radii.map((value: any) => esc(value)).join(", ")}</div>`;
  }
  if ((primitives.spacings || []).length) {
    html += `<div class="fe-dna-meta" style="margin-top:8px">Spacings</div>`;
    html += `<div class="fe-dna-primitive">${primitives.spacings.map((value: any) => esc(value)).join(", ")}</div>`;
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
  setDnaActionsEnabled(true);
  wireStyleDnaEvents(body, bindings);
}

function dnaNumberRow(label: string, value: any, token: string, counts: Record<string, number>) {
  const count = counts[token] || 0;
  return `<div class="fe-dna-row" data-token="${esc(token)}">
    <label>${esc(label)}</label>
    <input type="number" value="${value == null ? "" : esc(value)}" data-kind="number" data-token="${esc(token)}">
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
    <input type="number" value="${esc(f.weight)}" data-kind="font-weight" data-token="${esc(token)}" style="width:55px">
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
  persistDraft();
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
  if (obj === undefined) return undefined;
  return JSON.parse(JSON.stringify(obj));
}

/** Клон IR для POST-пayload'ов без runtime-ключей (__path/__responsiveHidden).
 *  renderer.materializeResponsiveIR аннотирует канонический IR через __path
 *  (этот side-effect нужен syncActiveIR для ключей sourceNodeMap, в памяти не трогаем),
 *  но серверная schema их отклоняет (422) — чистим только копию на провод. */
function sanitizeIrForPost(ir: any) {
  const clone = deepClone(ir);
  const viewportDefaults: Record<string, { width: number; height: number }> = {
    desktop: { width: 1440, height: 900 },
    tablet: { width: 768, height: 1024 },
    mobile: { width: 390, height: 844 },
  };
  const viewports = clone && clone.responsive && clone.responsive.viewports;
  if (viewports && typeof viewports === "object") {
    Object.entries(viewportDefaults).forEach(([name, fallback]) => {
      if (!viewports[name] || typeof viewports[name] !== "object") return;
      const viewport = viewports[name];
      if (!(Number.isFinite(viewport.width) && viewport.width > 0)) viewport.width = fallback.width;
      if (!(Number.isFinite(viewport.height) && viewport.height > 0)) {
        const documentHeight = name === "desktop" && Number.isFinite(clone.frame && clone.frame.height)
          && clone.frame.height > 0 ? clone.frame.height : fallback.height;
        viewport.height = documentHeight;
      }
    });
  }
  const walk = (node: any) => {
    if (!node || typeof node !== "object") return;
    delete node.__path;
    delete node.__responsiveHidden;
    (node.children || []).forEach(walk);
  };
  (clone.tree || []).forEach(walk);
  return clone;
}

function sourceKeyForSelection(sel: GeoSel) {
  if (!state) return "";
    const active = activeSelectionNode(sel);
    const canonical = canonicalNode(sel.ref);
    const sourceKey = active?.sourceKey || canonical?.sourceKey;
    if (sourceKey) return sourceKey;
    if (sel.ref.secIdx == null) return "";
    const suffix = sel.ref.path ? "/" + sel.ref.path.replace(/\./g, "/") : "";
    return `editor:/tree/${sel.ref.secIdx}${suffix}`;
}

function isAncestorRef(parent: GeoRef, child: GeoRef) {
  if (parent.secIdx == null) return child.secIdx != null;
  if (parent.secIdx !== child.secIdx) return false;
  if (parent.path == null) return child.path != null;
  if (!child.path) return false;
  // sourceKey-пути адресуются через '/', числовые — через '.'; бэкенд
  // (editor_assist nested_scope_normalized) нормализует так же
  const sep = isSourceKeyPath(parent.path) ? "/" : ".";
  return child.path.startsWith(parent.path + sep);
}

export function getAiScopeView(mode: "single" | "selection" | "document") {
  if (!state) return { items: [], excluded: [] };
  if (mode === "document") {
    // весь артборд: скоуп = все секции верхнего уровня
    const items = (state.ir.tree || []).map((section: any, secIdx: number) => ({
      ref: { secIdx, path: null } as GeoRef,
      label: sectionLabel(section, secIdx),
      sourceKey: sourceKeyForSelection({ ref: { secIdx, path: null }, node: section, label: "" } as GeoSel),
    })).filter((item: any) => item.sourceKey);
    return { items, excluded: [] };
  }
  const selected = mode === "single" ? state.sel.slice(0, 1) : state.sel;
  const excluded = mode === "selection"
    ? selected.filter((candidate) => selected.some((other) => candidate !== other && isAncestorRef(candidate.ref, other.ref)))
    : [];
  const items = selected.filter((candidate) => !excluded.includes(candidate));
  const map = (sel: GeoSel) => ({ label: sel.label || "Объект", ref: sel.ref, sourceKey: sourceKeyForSelection(sel) });
  return { items: items.map(map).filter((item) => item.sourceKey), excluded: excluded.map(map) };
}

function selectedSourceKeys(mode: "single" | "selection" | "document") {
  return getAiScopeView(mode).items.map((item: { sourceKey: string }) => item.sourceKey);
}

export function removeFromAiSelection(ref: GeoRef) {
  if (!state?.geo) return;
  const key = refKeyOf(ref);
  const refs = state.sel.filter((sel) => refKeyOf(sel.ref) !== key).map((sel) => sel.ref);
  if (refs.length) state.geo.selectMulti(refs);
}

function friendlyAiError(detail: string) {
  console.warn("AI assist rejected:", detail);
  if (/AI_STALE|изменился во время AI/i.test(detail)) return "Макет или выделение изменились во время работы AI. Запустите запрос ещё раз — ручные правки сохранены.";
  if (/Intent Lock|allowedColors|maxTextLength|защищ[её]н|ограничен/i.test(detail)) return "Эта часть объекта защищена ограничениями. Измените разрешения или выберите другой элемент.";
  if (/OpenAI API key|Codex не подключён|Claude не подключён|Codex CLI|Claude Code|нет подключённого AI-аккаунта|Agents\s*→\s*Connections/i.test(detail)) return "AI-аккаунт не подключён. Откройте Agents → Connections.";
  if (/outside|вне текущего выделения|не найден элемент/i.test(detail)) return "Выделение изменилось. Выберите объект ещё раз.";
  if (/schema|невалидн|структурн|children|sourceKey|patch|команд/i.test(detail)) return "AI предложил небезопасную правку. Уточните запрос.";
  if (/429|лимит|очередь/i.test(detail)) return "AI занят. Повторите через минуту.";
  // Ошибки дизайн-системы содержат готовое объяснение и действие — не прячем их
  if (/Design System/i.test(detail)) return detail;
  if (/timed out|timeout|время ожидания/i.test(detail)) return "AI не ответил за 3 минуты. Запрос остановлен — попробуйте ещё раз или сократите задачу.";
  return "Не удалось подготовить результат. Попробуйте уточнить запрос.";
}

function isAbortError(error: unknown) {
  return !!error && typeof error === "object" && ((error as Error).name === "AbortError" || (error as DOMException).name === "AbortError");
}

async function postAiAssist(payload: Record<string, unknown>, signal?: AbortSignal) {
  const response = await fetch("/api/editor/assist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

export async function requestAiAssist(request: AssistRequest) {
  // document-режим работает без выделения — скоуп это все секции
  if (!state || (request.scopeMode !== "document" && !state.sel.length)) return;
  const prompt = request.prompt.trim();
  if (!prompt) { ui.setAiError("Опишите, что нужно изменить"); return; }
  aiAssistAbort?.abort();
  aiAssistAbort = new AbortController();
  const { signal } = aiAssistAbort;
  ui.setAiBusy(true);
  ui.setAiError("");
  const startedAt = Date.now();
  ui.setAiProgress({ stage: "prepare", label: "Собираю контекст выделения", startedAt });
  aiAssistState = null;
  aiAssistBaseFingerprint = null;
  ui.setAiPreview(null);
  setAiAssistFormState(request);
  updateUndoBtn();
  const baseSessionId = state.sessionId;
  const baseFingerprint = JSON.stringify(sanitizeIrForPost(state.ir));
  const requestScopeKeys = selectedSourceKeys(request.scopeMode);
  const payload: Record<string, unknown> = {
    ir: sanitizeIrForPost(state.ir), prompt, action: request.action,
    provider: assistProviderAvailable(String(request.provider)) ? request.provider : "openai",
    effort: ["medium", "high", "max"].includes(String(request.effort)) ? request.effort : "medium",
    scope: { sourceKeys: requestScopeKeys, viewport: state.viewport },
    constraints: { allowStructure: false, ...request.constraints },
  };
  // Design System: разрешение в pinned ref (ТЗ §16.2)
  const dsSel = request.designSystemSelection || "inherit";
  if (dsSel !== "none") {
    // registry лежит в flow store — берём через глобальный стор
    try {
      const reg2 = (window as any).__flowStore?.getState?.()?.designSystems;
      if (reg2) {
        const target = dsSel === "inherit" ? reg2.defaultSystemRef?.systemId : dsSel;
        const system = reg2.systems?.find((sys: any) => sys.systemId === target && sys.status === "published");
        if (system) {
          (payload as any).designSystem = {
            systemId: system.systemId,
            revision: dsSel === "inherit" ? (reg2.defaultSystemRef?.revision ?? system.revision) : system.revision,
            contentHash: system.contentHash || "",
            usageMode: request.designSystemUsageMode || "strict",
          };
        }
      }
    } catch { /* нет registry — без системы */ }
  }
  try {
    let data: any;
    if (window.designDNA?.providers && request.action !== "adapt") {
      const prepared = await postAiAssist({ ...payload, prepareOnly: true }, signal);
      if (signal.aborted) return;
      if (Array.isArray(prepared.messages)) {
        ui.setAiProgress({ stage: "provider", label: "AI анализирует объект и готовит правки", startedAt });
        const effort = ["medium", "high", "max"].includes(String(request.effort))
          ? request.effort as "medium" | "high" | "max"
          : "medium";
        // Claude — подписочный CLI (opus + маппинг усилия в thinking-бюджет),
        // Codex — текстовый CLI без reasoning; Sol — дефолт для прочих значений.
        const provider = assistProviderAvailable(String(request.provider)) ? request.provider! : "openai";
        const route = provider === "codex"
          ? { provider, model: null }
          : { provider, model: provider === "claude" ? "opus" : provider === "astra" ? "gpt-6-astra" : "gpt-5.6-sol", reasoning: { effort } };
        const answer = await window.designDNA.providers.chatRequest({
          ...route,
          // CLI-транспорты оборачивают сообщения профильной инструкцией;
          // generator-профиль просил «сгенерируй Design IR» и ломал контракт
          // {summary, commands} инспектора — правкам нужен профиль editor.
          profile: "editor",
          messages: prepared.messages,
        });
        if (signal.aborted) return;
        ui.setAiProgress({ stage: "validate", label: "Проверяю ответ и строю предпросмотр", startedAt });
        data = await postAiAssist({ ...payload, rawOutput: answer.content }, signal);
      } else data = prepared;
    } else {
      if (request.action !== "adapt") ui.setAiProgress({ stage: "provider", label: "AI анализирует объект и готовит правки", startedAt });
      data = await postAiAssist(payload, signal);
      if (signal.aborted) return;
      ui.setAiProgress({ stage: "validate", label: "Проверяю ответ и строю предпросмотр", startedAt });
    }
    if (signal.aborted) return;
    if (!data?.previewIr || !Array.isArray(data.ops)) throw new Error("AI вернул неполный preview");
    const currentScopeKeys = state ? selectedSourceKeys(request.scopeMode) : [];
    if (!state || state.sessionId !== baseSessionId
      || JSON.stringify(sanitizeIrForPost(state.ir)) !== baseFingerprint
      || JSON.stringify(currentScopeKeys) !== JSON.stringify(requestScopeKeys)) {
      throw new Error("AI_STALE: макет или выделение изменился во время AI");
    }
    aiAssistState = data as AssistPreview;
    aiAssistBaseFingerprint = baseFingerprint;
    ui.setAiPreview(aiAssistState);
    dom.overlay?.classList.add("ai-previewing");
    rerenderEditorCanvas();
  } catch (error) {
    if (isAbortError(error) || signal.aborted) return;
    ui.setAiError(friendlyAiError(error instanceof Error ? error.message : String(error)));
  } finally {
    if (aiAssistAbort?.signal === signal) {
      ui.setAiBusy(false);
      ui.setAiProgress(null);
      updateUndoBtn();
    }
  }
}

export function cancelAiAssist() {
  const hadPreview = !!aiAssistState;
  const hadInFlight = !!aiAssistAbort;
  aiAssistAbort?.abort();
  aiAssistAbort = null;
  aiAssistState = null;
  aiAssistBaseFingerprint = null;
  dom.overlay?.classList.remove("ai-previewing");
  ui.setAiBusy(false);
  ui.setAiProgress(null);
  ui.setAiPreview(null);
  ui.setAiError("");
  updateUndoBtn();
  if (hadPreview || hadInFlight) rerenderEditorCanvas();
}

export function applyAiAssist() {
  if (aiAssistAbort) { aiAssistAbort.abort(); aiAssistAbort = null; }
  if (!state || !aiAssistState?.previewIr || aiAssistState.validation?.schema === false) return false;
  if (!aiAssistBaseFingerprint || JSON.stringify(sanitizeIrForPost(state.ir)) !== aiAssistBaseFingerprint) {
    aiAssistState = null;
    aiAssistBaseFingerprint = null;
    dom.overlay?.classList.remove("ai-previewing");
    ui.setAiPreview(null);
    ui.setAiError("Макет изменился после предпросмотра. AI-правка отменена, ручные изменения сохранены.");
    rerenderEditorCanvas();
    updateUndoBtn();
    return false;
  }
  pushHistory();
  state.ir = deepClone(aiAssistState.previewIr);
  state.activeIR = null;
  aiAssistState = null;
  aiAssistBaseFingerprint = null;
  dom.overlay?.classList.remove("ai-previewing");
  ui.setAiPreview(null);
  persistDraft();
  rerenderEditorCanvas();
  updateUndoBtn();
  return true;
}

/* ---------- сохранение / история ---------- */

function save() {
  if (!state) return;
  syncActiveIR();
  const saved = state.onSave ? state.onSave(deepClone(state.ir), state.baseUpstreamRevision) : false;
  if (saved) close(true);
}

/* ---------- защита несохранённых правок ----------
 * Раньше Esc/«Закрыть» молча стирали черновик (clearEditorDraft в onClose).
 * Теперь грязная сессия сначала спрашивает; «Не сохранять» — прежний путь. */
let closeConfirmOpen = false;

export function isDirty(): boolean {
  if (!state) return false;
  syncActiveIR();
  return JSON.stringify(state.ir) !== state.cleanFingerprint;
}

export function requestClose() {
  if (!state) return;
  if (!isDirty()) {
    close();
    return;
  }
  closeConfirmOpen = true;
  ui.setCloseConfirm(true);
}

export function dismissCloseConfirm() {
  closeConfirmOpen = false;
  ui.setCloseConfirm(false);
}

export function discardAndClose() {
  dismissCloseConfirm();
  close();
}

export function saveAndClose() {
  dismissCloseConfirm();
  save(); // при конфликте ревизий onSave вернёт false и редактор останется открытым
}

export function close(saved?: boolean) {
  closeConfirmOpen = false;
  if (state && state.onClose) state.onClose(!!saved);
  if (state && state.geo) { state.geo.destroy(); state.geo = null; }
  state = null;
  dnaPanelState = null;
  aiAssistAbort?.abort();
  aiAssistAbort = null;
  overlayCancelGen += 1;
  aiAssistState = null;
  aiAssistBaseFingerprint = null;
  if (typeof window !== "undefined") delete window.__editorActions;
  setDnaActionsEnabled(false);
  dom.overlay?.classList.remove("ai-previewing");
  dom.dnaPanel?.classList.remove("open");
  if (dom.overlay) dom.overlay.style.display = "none";
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

/** Общий сценарий undo/redo: восстановить снапшот и сохранить выделение,
 *  которое всё ещё резолвится в восстановленном IR (Figma-паттерн: undo не
 *  сбрасывает выбранный объект — иначе за undo нельзя продолжить правку). */
function restoreSnapshot(snap: any) {
  if (!state) return;
  // geoedit хранит свою operative selection (applyNum/delete и т.д. работают
  // по ней) — берём ссылки оттуда, state.sel мог не обновиться из-за
  // state_unsafe_mutation в onSelect
  const keepRefs = (state.geo ? state.geo.selections : []).map((s: any) => s.ref);
  const fallbackRefs = state.sel.map((s) => s.ref);
  state.ir = snap;
  persistDraft();
  if (state.geo) { state.geo.destroy(); state.geo = null; }
  renderCanvas(); // пересоздаёт geoedit с ПУСТОЙ selection
  const refs = keepRefs.length ? keepRefs : fallbackRefs;
  state.sel = refs
    .map((ref) => {
      const node = canonicalNode(ref);
      return node ? ({ ref, node, label: searchableNodeText(node).slice(0, 60) } as GeoSel) : null;
    })
    .filter((s): s is GeoSel => !!s);
  // без этого инспектор/applyNum после undo работают вхолостую: слушатели
  // geoedit применяют правки к его собственной (пустой) selection
  const restoredGeo = state.geo as GeoHandle | null;
  if (state.sel.length && restoredGeo) restoredGeo.selectMulti(state.sel.map((s) => s.ref));
  renderLayers();
  renderInspector();
  updateUndoBtn();
  updateAlignVisibility();
}

function undo() {
  if (!state) return;
  const snap = state.history.undo(() => state!.ir);
  if (!snap) return;
  restoreSnapshot(snap);
}

function redo() {
  if (!state) return;
  const snap = state.history.redo(() => state!.ir);
  if (!snap) return;
  restoreSnapshot(snap);
}

export function updateUndoBtn() {
  if (!state) return;
  const blocked = !!aiAssistState || !!aiAssistAbort;
  if (dom.undoBtn) dom.undoBtn.disabled = blocked || !state.history.canUndo();
  if (dom.redoBtn) dom.redoBtn.disabled = blocked || !state.history.canRedo();
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
  // Moving a top-level section converts the artboard from flow to free layout
  // before writing section x/y coordinates. Responsive editing happens on a
  // materialized clone, so persist that structural parent change as well;
  // otherwise the numeric x/y values are ignored and the section snaps back.
  if (state.activeIR.frame && state.activeIR.frame.layout &&
      state.activeIR.frame.layout !== state.ir.frame?.layout) {
    state.ir.frame = Object.assign({}, state.ir.frame || {}, {
      layout: state.activeIR.frame.layout,
    });
  }
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
      // Imported responsive sources may carry an explicit desktop override.
      // Keeping only the base frame makes the stale override win immediately
      // after rerender, so direct canvas edits appear to snap back on drop.
      const desktop = node.responsive && node.responsive.desktop;
      if (desktop) {
        if (active.frame) desktop.frame = JSON.parse(JSON.stringify(active.frame));
        if (active.style) desktop.style = JSON.parse(JSON.stringify(active.style));
      }
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

function syncSelectedRootFrame(active: any, target: any) {
  if (!state || !active?.frame || !target) return;
  const next = deepClone(active.frame);
  const viewport = state.viewport;
  const current = target.frame || {};

  // Width belongs to the viewport. All other artboard properties are shared;
  // a numeric height means the user intentionally replaced auto-height with a
  // manually editable size.
  if (viewport === "desktop") target.frame = next;
  else target.frame = { ...current, ...next, width: current.width };

  const viewports = target.responsive && target.responsive.viewports;
  const meta = viewports && viewports[viewport];
  if (meta) {
    if (typeof next.width === "number" && Number.isFinite(next.width)) meta.width = next.width;
    if (typeof next.height === "number" && Number.isFinite(next.height)) meta.height = next.height;
  }
}

/** Persist geometry/style for the exact refs being edited on the canvas.
 * Source-key reconciliation handles broad/structural changes, while this
 * direct path prevents viewport materialization from restoring an older
 * responsive frame immediately after pointer-up. */
function syncSelectedActiveGeometry() {
  if (!state || !state.activeIR || state.activeIR === state.ir || !state.ir.responsive) return;

  function at(ir: any, ref: GeoRef) {
    if (ref.secIdx == null) return ir;
    const section = ir && ir.tree && ir.tree[ref.secIdx];
    if (!section || ref.path == null) return section;
    if (ref.path.startsWith("props.")) return null;
    return isSourceKeyPath(ref.path) ? findByKey(section, ref.path) : getByPath(section, ref.path);
  }

  state.sel.forEach((sel) => {
    const active = at(state!.activeIR, sel.ref);
    const target = at(state!.ir, sel.ref);
    if (!active || !target) return;
    if (sel.ref.secIdx == null) {
      syncSelectedRootFrame(active, target);
      return;
    }
    if (state!.viewport === "desktop") {
      if (active.frame) target.frame = deepClone(active.frame);
      if (active.style) target.style = deepClone(active.style);
      const desktop = target.responsive && target.responsive.desktop;
      if (desktop) {
        if (active.frame) desktop.frame = deepClone(active.frame);
        if (active.style) desktop.style = deepClone(active.style);
      }
    } else {
      target.responsive = target.responsive || {};
      const override = target.responsive[state!.viewport] || {};
      override.visible = true;
      if (active.frame) override.frame = deepClone(active.frame);
      if (active.style) override.style = deepClone(active.style);
      target.responsive[state!.viewport] = override;
    }
  });
}

function renderCanvas() {
  if (!state || !dom.canvasInner) return;
  const inner = dom.canvasInner;
  IRRenderer.renderIR(inner, buildActiveIR(), { fit: false, viewport: state.viewport }); // _frames применяет сам рендерер
  applyLayerFlags();
  applyTransform();
  attachGeoEdit();
  applySourceLens();
  applyIntentLockBadges();
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
  const R = 22; // толщина линеек, синхронно с .fe-ruler-* в editor.css
  const w = Math.ceil(cr.width - R), h = Math.ceil(cr.height - R);
  if (w <= 0 || h <= 0) return;
  rulerH.width = w; rulerH.height = R;
  rulerV.width = R; rulerV.height = h;
  const ctxH = rulerH.getContext("2d");
  const ctxV = rulerV.getContext("2d");
  if (!ctxH || !ctxV) return;
  ctxH.clearRect(0, 0, w, R);
  ctxV.clearRect(0, 0, R, h);
  ctxH.fillStyle = "#a1a1aa"; ctxH.font = "9px Inter, sans-serif"; ctxH.textBaseline = "top";
  ctxV.fillStyle = "#a1a1aa"; ctxV.font = "9px Inter, sans-serif"; ctxV.textBaseline = "middle";

  const z = state.zoom;
  // адаптивный шаг: при малом зуме показываем только крупные деления
  const minorStep = z >= 0.5 ? 8 : z >= 0.25 ? 16 : 32;
  const majorStep = z >= 0.5 ? 100 : z >= 0.25 ? 200 : 400;
  const offsetX = state.panX - R; // сдвиг линейки относительно канваса (R = ширина вертикальной линейки)
  const offsetY = state.panY - R;

  // горизонтальная линейка
  const startX = Math.floor(-offsetX / z / minorStep) * minorStep;
  const endX = Math.ceil((w - offsetX) / z / minorStep) * minorStep;
  for (let px = startX; px <= endX; px += minorStep) {
    const screenX = px * z + offsetX;
    if (screenX < 0 || screenX > w) continue;
    const isMajor = px % majorStep === 0;
    ctxH.strokeStyle = isMajor ? "#a1a1aa" : "#3f3f46";
    ctxH.beginPath();
    ctxH.moveTo(screenX, isMajor ? 0 : R - 8);
    ctxH.lineTo(screenX, R);
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
    ctxV.moveTo(isMajor ? 0 : R - 8, screenY);
    ctxV.lineTo(R, screenY);
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

/** Клик по проценту в тулбаре — сброс зума к 100% (центр канваса). */
export function zoomReset() {
  if (!state || state.zoom === 1) return;
  zoomBy(1 / state.zoom);
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

/* ---------- привязка к сетке при drag ---------- */

/* Move-drag отличаем от nudge/инспектора по последнему pointerup внутри канваса
 * (commitMoveAll движка выполняется синхронно в этом же pointerup); Alt — без привязки. */
let lastCanvasUp = { t: 0, alt: false };
if (typeof window !== "undefined") {
  window.addEventListener(
    "pointerup",
    (e) => {
      if (dom.canvas && e.target instanceof Node && dom.canvas.contains(e.target)) {
        lastCanvasUp = { t: performance.now(), alt: e.altKey };
      }
    },
    true,
  );
}

/** Живой frame по ref в переданном IR — зеркало geoedit.getFrame (props.* живут в sec._frames). */
function frameAtRef(ir: any, ref: GeoRef): any {
  if (!ir) return null;
  if (ref.secIdx == null) return ir.frame;
  const section = ir.tree && ir.tree[ref.secIdx];
  if (!section) return null;
  if (ref.path == null) return section.frame;
  if (ref.path.startsWith("props.")) return section._frames && section._frames[ref.path];
  const node = isSourceKeyPath(ref.path) ? findByKey(section, ref.path) : getByPath(section, ref.path);
  return node && node.frame;
}

/* Снимок геометрии выделения на onCommit (до мутации): по нему onMutated отличает
 * move (x/y изменились, размер прежний) от resize/rotate. */
const moveSnapBase = new Map<string, { x: any; y: any; w: any; h: any }>();

function captureMoveSnapBase() {
  moveSnapBase.clear();
  if (!state) return;
  const ir = state.activeIR || state.ir;
  state.sel.forEach((sel) => {
    const f = frameAtRef(ir, sel.ref);
    if (f) moveSnapBase.set(refKeyOf(sel.ref), { x: f.x, y: f.y, w: f.width, h: f.height });
  });
}

/** Округление x/y move-коммита до шага сетки — ДО syncActiveIR/перерендера. */
function applyMoveGridSnap() {
  if (!state || !snapEnabled) return;
  if (lastCanvasUp.alt || performance.now() - lastCanvasUp.t > 150) return;
  // Смарт-гайды (выравнивание по соседям, равные зазоры) точнее сетки: дроп,
  // который лёг на гайд, не округляем к 8px — иначе x=500 превращался в 504.
  if (state.geo?.lastDragSmartSnapped?.()) return;
  const ir = state.activeIR || state.ir;
  state.sel.forEach((sel) => {
    const f = frameAtRef(ir, sel.ref);
    const base = moveSnapBase.get(refKeyOf(sel.ref));
    if (!f || !base || typeof f.x !== "number" || typeof f.y !== "number") return;
    if (f.x === base.x && f.y === base.y) return; // не move
    if (typeof base.w === "number" && (f.width !== base.w || f.height !== base.h)) return; // resize
    f.x = Math.round(f.x / snapStepPx) * snapStepPx;
    f.y = Math.round(f.y / snapStepPx) * snapStepPx;
  });
}

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
    onNotice: (message: string) => toast(message),
    getIR: () => (state ? state.activeIR || state.ir : null),
    getScale: () => {
      const irEl = inner.querySelector('[class^="ir-"]') as HTMLElement | null;
      if (!irEl) return 1;
      const dw = Number(irEl.dataset.designWidth) || IRRenderer.DESIGN_WIDTH;
      const w = irEl.getBoundingClientRect().width;
      return w > 0 ? w / dw : 1;
    },
    onCommit: () => {
      captureMoveSnapBase();
      pushHistory();
    },
    cancelCommit: () => {
      if (!state) return;
      state.history.cancelLast();
      updateUndoBtn();
    },
    onImageUpload: () => {
      void uploadImageForSelection();
    },
    onMutated: () => {
      if (!state) return;
      applyMoveGridSnap();
      syncActiveIR();
      syncSelectedActiveGeometry();
      persistDraft();
      const savedRefs = state.sel.map((s) => s.ref);
      IRRenderer.renderIR(inner, buildActiveIR(), { fit: false, viewport: state.viewport, incremental: true });
      applyLayerFlags();
      applyTransform();
      attachGeoEdit();
      renderLayers();
      if (savedRefs.length && state.geo) {
        state.geo.selectMulti(savedRefs);
      }
      applySourceLens();
      applyIntentLockBadges();
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
      applyIntentLockBadges();
    },
  });
  // инструмент переживает ре-аттач после мутаций
  if (state.tool !== "select") state.geo.setTool(state.tool);
}

/* ---------- слои ---------- */

function propsElements(sec: any) {
  const p = sec.props || {};
  const items: { path: string; label: string; icon: string; depth?: number }[] = [];
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
  if (p.fields) p.fields.forEach((field: any, i: number) => {
    const base = `props.fields.${i}`;
    items.push({
      path: base,
      label: "поле: " + String(field.label || field.placeholder || `№ ${i + 1}`).slice(0, 24),
      icon: "◇",
    });
    items.push({ path: `${base}.parts.label`, label: "подпись", icon: "T", depth: 3 });
    items.push({ path: `${base}.parts.control`, label: "поле ввода", icon: "▭", depth: 3 });
  });
  if (sec.type === "contact-form" && (p.submit || p.submitText)) items.push({
    path: "props.submit",
    label: "кнопка: " + String(p.submit?.text ?? p.submitText ?? "Отправить").slice(0, 24),
    icon: "▰",
  });
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
      addLayerItem(tree, getByPath(sec, pe.path) || {}, { secIdx: si, path: pe.path }, pe.depth || 2, pe.label, pe.icon);
    });
    const sourceAddressed = sec.type === "source-block" || sec.variant === "dom-capture";
    renderChildLayers(tree, sec.children || [], si, "children", 2, sourceAddressed);
  });
}

function layerLabel(el: any, maxText: number) {
  const sourceMeta = el.sourceMeta || {};
  if (sourceMeta.componentBoundary) {
    const role = String(sourceMeta.componentRole || el.role || el.type || "component");
    const name = String(sourceMeta.componentLabel || role);
    return `компонент · ${name}`.slice(0, Math.max(18, maxText + 14));
  }
  const base = el.type === "card" && el.role ? "div" : el.type;
  const suffix = el.text ? ` · ${String(el.text).slice(0, maxText)}`
    : el.title ? ` · ${String(el.title).slice(0, maxText)}`
    : el.placeholder ? ` · ${String(el.placeholder).slice(0, maxText)}`
    : "";
  return base + suffix;
}

function renderChildLayers(
  tree: HTMLElement, children: any[], secIdx: number, basePath: string, depth: number, sourceAddressed = false,
) {
  children.forEach((el, i) => {
    const numericPath = `${basePath}.${i}`;
    const path = sourceAddressed && typeof el.sourceKey === "string" && el.sourceKey
      ? el.sourceKey
      : numericPath;
    addLayerItem(tree, el, { secIdx, path }, depth, layerLabel(el, depth > 2 ? 14 : 16));
    if (el.children && el.children.length) {
      renderChildLayers(tree, el.children, secIdx, `${numericPath}.children`, depth + 1, sourceAddressed);
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
  div.tabIndex = 0;
  div.setAttribute("role", "button");
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
      const parentOf = (x: { si: string; p: string | null }) => {
        if (!x.p) return null;
        return isSourceKeyPath(x.p)
          ? parentKeyByKey(state!.ir.tree[Number(x.si)], x.p)
          : x.p.split(".").slice(0, -2).join(".");
      };
      const fromRef = { secIdx: a.si === "null" ? null : Number(a.si), path: a.p } as GeoRef;
      const toRef = { secIdx: b.si === "null" ? null : Number(b.si), path: b.p } as GeoRef;
      const section = state.ir.tree[Number(b.si)];
      const targetNode: any = toRef.path == null
        ? section
        : (section && isSourceKeyPath(String(toRef.path))
            ? findByKey(section, String(toRef.path))
            : getByPath(section, String(toRef.path)));
      // Цель-контейнер (секция или card) принимает узел внутрь — как в Figma.
      // reparent сам откажется, если цель уже родитель источника: тогда это
      // обычная перестановка соседей ниже.
      const targetIsContainer = toRef.path == null || (targetNode && (targetNode.type === "card" || targetNode.type === "frame"));
      if (targetIsContainer && state.geo.reparent(fromRef, toRef)) return;
      // тот же родитель — reorder по индексу цели
      if (a.si === b.si && parentOf(a) === parentOf(b)) {
        const located: any = section && b.p && isSourceKeyPath(b.p) ? locateByKey(section, b.p) : null;
        const to = located ? located.index : parseInt((b.p || "0").split(".").pop()!);
        if (!Number.isInteger(to)) return;
        state.geo.moveSibling(fromRef, to);
        return;
      }
      toast("Перетащите на секцию или карточку — внутрь текста и картинки вложить нельзя");
    });
  }
  if (fl.hidden) div.classList.add("flag-hidden");
  if (fl.locked) div.classList.add("flag-locked");
  const isSelected = state.sel.some((s) => s.ref.secIdx === ref.secIdx && s.ref.path === ref.path);
  if (isSelected) div.classList.add("selected");
  div.setAttribute("aria-pressed", String(isSelected));
  const icons: Record<string, string> = {
    navbar: "☰", hero: "◈", card: "▢", heading: "H", text: "T", button: "⬛", image: "▣",
    badge: "•", pricing: "$", faq: "?", footer: "⊥", frame: "◻", composition: "◫",
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
    `<button class="fe-lbtn" data-flag="hidden" title="Скрыть/показать слой" aria-label="${fl.hidden ? "Показать слой" : "Скрыть слой"}" aria-pressed="${fl.hidden ? "true" : "false"}">${fl.hidden ? "🚫" : "👁"}</button>` +
    `<button class="fe-lbtn" data-flag="locked" title="Залочить/разлочить" aria-label="${fl.locked ? "Разлочить слой" : "Залочить слой"}" aria-pressed="${fl.locked ? "true" : "false"}">${fl.locked ? "🔒" : "🔓"}</button>`;
  const selectLayer = (e: Pick<MouseEvent | KeyboardEvent, "target" | "shiftKey" | "ctrlKey" | "metaKey">) => {
    if (!state) return;
    const btn = (e.target as HTMLElement).closest("[data-flag]") as HTMLElement | null;
    if (btn) { toggleLayerFlag(ref, btn.dataset.flag as "hidden" | "locked"); return; }
    if (refFlag(ref, "locked")) return; // залочен — не выделяется
    if (state.geo) {
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        const selected = state.sel.some((sel) => refKeyOf(sel.ref) === key);
        const refs = selected
          ? state.sel.filter((sel) => refKeyOf(sel.ref) !== key).map((sel) => sel.ref)
          : [...state.sel.map((sel) => sel.ref), ref];
        if (refs.length) state.geo.selectMulti(refs); else state.geo.clear();
      } else state.geo.select(ref);
    }
  };
  div.addEventListener("click", selectLayer);
  div.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    selectLayer(e);
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

/** Снимок текущего IR (с черновыми правками) — для «Сохранить как вариант ДС». */
export function currentIrSnapshot(): any | null {
  return state ? deepClone(state.ir) : null;
}

/** Вставить секцию-мастер ДС после выделенной секции или в конец: один шаг undo,
 * черновик сохраняется, шрифты мастера доезжают через meta.fontFaces. */
export function insertDesignSystemSection(section: any, meta?: any): boolean {
  if (!state || !section || typeof section !== "object") return false;
  pushHistory();
  if (!Array.isArray(state.ir.tree)) state.ir.tree = [];
  const copy = deepClone(section);
  const ids = new Set(state.ir.tree.map((s: any) => s && s.id));
  const base = String(copy.id || "ds-section");
  let id = base;
  let n = 2;
  while (ids.has(id)) id = `${base}-${n++}`;
  copy.id = id;
  const selectedSection = state.sel.find((item) => Number.isInteger(item.ref.secIdx))?.ref.secIdx;
  const insertAt = selectedSection == null
    ? state.ir.tree.length
    : Math.min(state.ir.tree.length, selectedSection + 1);
  state.ir.tree.splice(insertAt, 0, copy);
  const faces = meta && Array.isArray(meta.fontFaces) ? meta.fontFaces : [];
  if (faces.length) {
    if (!state.ir.meta || typeof state.ir.meta !== "object") state.ir.meta = {};
    const have = new Set((state.ir.meta.fontFaces || []).map((f: any) => JSON.stringify(f)));
    state.ir.meta.fontFaces = [
      ...(state.ir.meta.fontFaces || []),
      ...faces.filter((f: any) => !have.has(JSON.stringify(f))),
    ];
  }
  persistDraft();
  renderLayers();
  rerenderEditorCanvas();
  updateUndoBtn();
  ui.bumpInspector();
  return true;
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
  if (node && ref.path) node = isSourceKeyPath(ref.path) ? findByKey(node, ref.path) : getByPath(node, ref.path);
  return node || null;
}

function activeSelectionNode(sel: GeoSel) {
  if (!state) return null;
  return (state.sel.find((item) => item.ref.secIdx === sel.ref.secIdx && item.ref.path === sel.ref.path) || sel).node || null;
}

function finishResponsiveMutation() {
  if (!state) return;
  persistDraft();
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
  if (target.editable === false) return; // editable:false (raster fallback): геометрия заблокирована
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
  if (target.editable === false) return; // editable:false (raster fallback): геометрия заблокирована
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
  if (target.editable === false) return; // editable:false (raster fallback): геометрия заблокирована
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
  // Legacy token controls mutate their object before requesting a redraw.
  // Fingerprint-gated persistence converts that into a new Zustand identity.
  // AI preview must never write previewIr into the canonical draft.
  if (!aiAssistState) persistDraft();
  const inner = dom.canvasInner;
  let canvasIr = buildActiveIR();
  if (aiAssistState?.previewIr) {
    canvasIr = aiAssistState.previewIr?.responsive?.viewports
      ? IRRenderer.materializeResponsiveIR(aiAssistState.previewIr, state.viewport)
      : aiAssistState.previewIr;
  }
  IRRenderer.renderIR(inner, canvasIr, { fit: false, viewport: state.viewport, incremental: true });
  // Incremental render preserves untouched DOM nodes; preview highlighting is
  // controller-owned transient state and must not leak after accept/cancel.
  inner.querySelectorAll(".ai-changed-node").forEach((element) => element.classList.remove("ai-changed-node"));
  if (aiAssistState?.ops?.length) {
    const marked = new Set<string>();
    aiAssistState.ops.forEach((op) => {
      const parts = op.path.split("/").filter(Boolean);
      if (parts[0] !== "tree" || !/^\d+$/.test(parts[1] || "")) return;
      const sectionIndex = Number(parts[1]);
      const nodeParts = parts.slice(2);
      const marker = `${sectionIndex}:${nodeParts.join(".")}`;
      if (marked.has(marker)) return;
      marked.add(marker);
      // В source-секциях DOM адресуется sourceKey, а op-пути бэкенда числовые:
      // резолвим узел в отрендеренном IR и подсвечиваем его sourceKey-элемент.
      // Правило адресации — как в annotatePaths: только внутри source-block/
      // dom-capture; в generic-секциях DOM остаётся числовым (узлы могут нести
      // sourceKey, но data-ir-path там числовой).
      const opSection = (canvasIr.tree || [])[sectionIndex];
      const opSourceSec = !!(opSection && (opSection.type === "source-block" || opSection.variant === "dom-capture"));
      let target: HTMLElement | null = null;
      while (nodeParts.length && !target) {
        const numericPath = nodeParts.join(".");
        const node = opSection ? getByPath(opSection, numericPath) : null;
        const domPath = opSourceSec && node && node.sourceKey ? node.sourceKey : numericPath;
        target = domAtCanvas({ secIdx: sectionIndex, path: domPath });
        if (!target) nodeParts.pop();
      }
      if (!target) target = domAtCanvas({ secIdx: sectionIndex, path: null });
      target?.classList.add("ai-changed-node");
    });
  }
  applyLayerFlags();
  applyTransform();
  attachGeoEdit();
  applySourceLens();
  applyIntentLockBadges();
  renderLayers();
  if (state.sel.length && state.geo) state.geo.selectMulti(state.sel.map((s) => s.ref));
  renderInspector();
}

/** Persist direct inspector edits made against the materialized viewport IR.
 * Geometry/style mutations already flow through GeoEdit.onMutated; text and
 * type-specific controls mutate the selected active node directly. */
export function commitActiveIrEdits() {
  if (!state) return;
  syncActiveIR();
  persistDraft();
}

/* ---------- картинка в выделенный элемент ----------
 * Заглушка генератора (imagePrompt без src) — место для своей картинки:
 * инспектор («Загрузить…») и двойной клик по заглушке зовут одно и то же. */
function selectedImageNode(): any | null {
  if (!state || !state.sel.length) return null;
  const node = state.sel[0].node;
  if (!node || node.type !== "image") return null;
  return node;
}

export function selectedIsImage(): boolean {
  return !!selectedImageNode();
}

export async function uploadImageForSelection(file?: File | null): Promise<boolean> {
  const node = selectedImageNode();
  if (!node) return false;
  const { pickImageFile, prepareImageForIr, formatBytes } = await import("../lib/imageUpload");
  const picked = file ?? (await pickImageFile());
  if (!picked) return false;
  // Сессия могла смениться, пока открыт диалог выбора файла
  if (selectedImageNode() !== node) return false;
  try {
    const prepared = await prepareImageForIr(picked);
    if (selectedImageNode() !== node) return false;
    pushHistory();
    node.src = prepared.dataUrl;
    if (!node.alt && node.imagePrompt) node.alt = String(node.imagePrompt).slice(0, 160);
    commitActiveIrEdits();
    rerenderEditorCanvas();
    ui.bumpInspector();
    toast(`Картинка вставлена · ${prepared.width}×${prepared.height}, ${formatBytes(prepared.bytes)}`, "ok");
    return true;
  } catch (error) {
    toast(`Не удалось загрузить картинку: ${error instanceof Error ? error.message : String(error)}`, "error");
    return false;
  }
}

export function clearImageForSelection(): boolean {
  const node = selectedImageNode();
  if (!node || !node.src) return false;
  pushHistory();
  delete node.src;
  commitActiveIrEdits();
  rerenderEditorCanvas();
  ui.bumpInspector();
  return true;
}

/* ---------- клавиатура ---------- */

function dismissOpenOverlays(): boolean {
  if (closeConfirmOpen) {
    dismissCloseConfirm();
    return true;
  }
  if (aiAssistAbort || aiAssistState) {
    cancelAiAssist();
    return true;
  }
  if (dom.dnaPanel?.classList.contains("open")) {
    closeStyleDnaInspector();
    return true;
  }
  const overlay = document.querySelector(
    ".fe-smart-axis-card, .fe-quality-card, .fe-harmonize-card, .fe-responsive-card, .fe-locks-card, .fe-semantic-card",
  );
  if (!overlay) return false;
  if (overlay.classList.contains("fe-smart-axis-card")) dismissSmartAxisProposal();
  else if (overlay.classList.contains("fe-quality-card")) dismissQualityProposal();
  else if (overlay.classList.contains("fe-harmonize-card")) dismissHarmonizerProposal();
  else if (overlay.classList.contains("fe-responsive-card")) dismissResponsiveProposal();
  else if (overlay.classList.contains("fe-locks-card")) closeIntentLocks();
  else if (overlay.classList.contains("fe-semantic-card")) closeSemanticSelect();
  return true;
}

export function onKeydown(e: KeyboardEvent) {
  if (!state) return;
  const ae = document.activeElement as HTMLElement | null;
  const typing = !!(ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)));
  if (e.key === "Escape") {
    e.preventDefault();
    if (dismissOpenOverlays()) return;
    if (state.geo && state.geo.consumeEscape()) return;
    requestClose();
    return;
  }
  if (typing) return;
  if (e.key === "v" || e.key === "V" || e.key === "м" || e.key === "М") setTool("select");
  if (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р") setTool("hand");
  if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") setTool("rect");
  if (e.key === "t" || e.key === "T" || e.key === "е" || e.key === "Е") setTool("text");
  if (e.key === "f" || e.key === "F" || e.key === "а" || e.key === "А") setTool("frame");
  if (e.key === "o" || e.key === "O" || e.key === "щ" || e.key === "Щ") setTool("ellipse");
  if (e.key === "l" || e.key === "L" || e.key === "д" || e.key === "Д") setTool("line");
  if (e.key === "i" || e.key === "I" || e.key === "ш" || e.key === "Ш") setTool("image");
  if (e.key === "]" || e.key === "ъ") { e.preventDefault(); handleAct("forward"); }
  if (e.key === "[" || e.key === "х") { e.preventDefault(); handleAct("backward"); }
  if ((e.key === "s" || e.key === "S" || e.key === "ы") && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    save();
  }
  if ((e.key === "z" || e.key === "Z" || e.key === "я" || e.key === "Я") && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (e.shiftKey) redo(); else undo();
  }
  if ((e.key === "y" || e.key === "Y" || e.key === "н" || e.key === "Н") && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    redo();
  }
}

/* ---------- утилиты ---------- */

function esc(s: any) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
