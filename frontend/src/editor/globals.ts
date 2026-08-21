/* Типы движков (frontend/src/engine): GeoEdit, IRHistory. Движки — императивные
 * TS-модули внутри React-сборки; React-редактор оркестрирует их. */

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
  stretchWidth: () => void;
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
  /** Отменить последний push, если мутация после него не применилась. */
  cancelLast: () => void;
}
