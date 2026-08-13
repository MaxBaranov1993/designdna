/* Типы для legacy-движков, подключённых глобальными скриптами (index.html):
 * GeoEdit (geoedit.js), IRHistory (irhistory.js), Inspector (inspector.js),
 * каталог шрифтов (font_catalog.js). IRRenderer уже описан в IrPreview.tsx.
 * Движки остаются императивными «островами» — React-редактор только оркестрирует. */

export type GeoRef = { secIdx: number | null; path: string | null };
export type GeoSel = { ref: GeoRef; label: string; node: any };

export interface GeoHandle {
  select: (ref: GeoRef) => void;
  selectMulti: (refs: GeoRef[]) => void;
  clear: () => void;
  consumeEscape: () => boolean;
  setFrame: (f: Record<string, unknown>) => void;
  setFrameProps: (f: Record<string, unknown>) => void;
  setNodeStyle: (s: Record<string, unknown>) => void;
  frameOf: (ref: GeoRef) => any;
  posOf: (ref: GeoRef) => any;
  sizeOf: (ref: GeoRef) => any;
  setTool: (t: string) => void;
  getTool: () => string;
  syncZoom: () => void;
  resetFrame: () => void;
  alignLeft: () => void;
  alignCenterH: () => void;
  alignRight: () => void;
  alignTop: () => void;
  alignCenterV: () => void;
  alignBottom: () => void;
  distributeH: () => void;
  distributeV: () => void;
  bringForward: () => void;
  sendBackward: () => void;
  moveSibling: (ref: GeoRef, to: number) => void;
  groupSelection: () => void;
  ungroupSelection: () => void;
  destroy: () => void;
  readonly selection: GeoSel | null;
  readonly selections: GeoSel[];
}

export interface GeoAttachOpts {
  previewEl: HTMLElement;
  getIR: () => any;
  getScale: () => number;
  onCommit: () => void;
  onMutated: () => void;
  onSelect: (sels: GeoSel[]) => void;
  tools?: boolean;
  escapeViaHandle?: boolean;
  isLocked?: (ref: GeoRef) => boolean;
  scrollEl?: { scrollLeft: number; scrollTop: number } | null;
  onToolChange?: (tool: string) => void;
}

export interface IRHistoryHandle {
  push: (snapshotFn: () => any, selKey?: string) => boolean;
  undo: (currentFn: () => any) => any;
  redo: (currentFn: () => any) => any;
  canUndo: () => boolean;
  canRedo: () => boolean;
  clear: () => void;
}

declare global {
  interface Window {
    GeoEdit?: { attach: (opts: GeoAttachOpts) => GeoHandle };
    IRHistory?: {
      createHistory: (opts?: { limit?: number; coalesceMs?: number }) => IRHistoryHandle;
    };
    Inspector?: {
      render: (
        container: HTMLElement,
        ctx: { ir: any; selections: GeoSel[]; geo: GeoHandle | null },
      ) => void;
      scrubbing?: boolean;
    };
    DesignAIFontCatalog?: {
      families: string[];
      groups?: { label: string; fonts: string[] }[];
    };
  }
}
