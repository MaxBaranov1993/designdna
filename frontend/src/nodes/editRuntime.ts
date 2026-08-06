import { useFlowStore } from "../flow/store";
import type { EditNodeData, IRObject } from "../flow/types";

/* Runtime-обвязка Edit-нод: глобалы legacy-ядра (GeoEdit/Inspector/IRHistory/Editor),
 * per-node история IR (undo/redo) и клавиатурная развязка с React Flow.
 * Всё — runtime-поля, в сохраняемый data не попадают (Б3, п.5). */

/* ---------- типы legacy-глобалов (объявлены как у IRRenderer в IrPreview.tsx) ---------- */

export type GeoEditRef = { secIdx: number | null; path: string | null };
export type GeoEditSelection = { ref: GeoEditRef; label: string };

export type GeoEditHandle = {
  selectMulti: (refs: GeoEditRef[]) => void;
  clear: () => void;
  syncZoom: () => void;
  resetFrame: () => void;
  destroy: () => void;
  readonly selection: GeoEditSelection | null;
  readonly selections: GeoEditSelection[];
};

export type GeoEditAttachOptions = {
  previewEl: HTMLElement;
  getIR: () => IRObject | null;
  getScale: () => number;
  onCommit?: () => void;
  onMutated?: () => void;
  onSelect?: (selections: GeoEditSelection[]) => void;
};

export type IRHistoryHandle = {
  push: (snapshotFn: () => IRObject | null, selKey?: string | null) => boolean;
  undo: (currentFn: () => IRObject | null) => IRObject | null;
  redo: (currentFn: () => IRObject | null) => IRObject | null;
  canUndo: () => boolean;
  canRedo: () => boolean;
  clear: () => void;
};

declare global {
  interface Window {
    /* GeoEdit.attach — geoedit.js:1990 (экспорт attach, контракт в шапке файла) */
    GeoEdit?: { attach: (opts: GeoEditAttachOptions) => GeoEditHandle };
    /* Inspector.render(el, {ir, selections, geo}) — inspector.js:410 */
    Inspector?: {
      render: (
        container: HTMLElement,
        ctx: { ir: IRObject | null; selections: GeoEditSelection[]; geo: GeoEditHandle | null },
      ) => void;
    };
    /* IRHistory.createHistory({limit}) — irhistory.js:66 */
    IRHistory?: { createHistory: (opts?: { limit?: number; coalesceMs?: number }) => IRHistoryHandle };
    /* Editor.open(nodeLike, onSave) / close / isOpen — editor.js:814 */
    Editor?: {
      open: (node: { data: { ir: IRObject | null } }, onSave: (ir: IRObject) => void) => void;
      close: () => void;
      isOpen: () => boolean;
    };
  }
}

/* ---------- per-node runtime: история и активный GeoEdit ---------- */

/* Зеркало n.history (nodes.js:675) — общая snapshot-история IR на ноду, limit 50 */
const histories = new Map<number, IRHistoryHandle>();
/* Активные инстансы GeoEdit по id ноды — для клавиатурной развязки с RF */
const geos = new Map<number, GeoEditHandle>();

export function editHistory(id: number): IRHistoryHandle | null {
  let h = histories.get(id);
  if (!h) {
    if (!window.IRHistory) return null;
    h = window.IRHistory.createHistory({ limit: 50 });
    histories.set(id, h);
  }
  return h;
}

export function registerGeo(id: number, geo: GeoEditHandle) {
  geos.set(id, geo);
}

export function unregisterGeo(id: number) {
  geos.delete(id);
}

/* ---------- undo/redo IR (зеркало nodes.js:600-660) ---------- */

function storeIr(id: number): IRObject | null {
  const n = useFlowStore.getState().nodes.find((x) => Number(x.id) === id);
  return n && n.type === "edit" ? (n.data as EditNodeData).ir : null;
}

/* Зеркало applyEditSnapshot (nodes.js:646-651): замена ir → перерисовка → propagate → save.
 * В новом UI: setNodeData даёт новую ссылку (эффект EditNode перерисовывает),
 * автосейв срабатывает по подписке стора. */
function applyEditSnapshot(id: number, snap: IRObject) {
  const st = useFlowStore.getState();
  st.setNodeData(id, { ir: snap });
  st.propagate(id);
}

export function undoEditNode(id: number) {
  const h = histories.get(id);
  const cur = storeIr(id);
  if (!h || !cur) return;
  const snap = h.undo(() => cur);
  if (snap) applyEditSnapshot(id, snap);
}

export function redoEditNode(id: number) {
  const h = histories.get(id);
  const cur = storeIr(id);
  if (!h || !cur) return;
  const snap = h.redo(() => cur);
  if (snap) applyEditSnapshot(id, snap);
}

/* ---------- клавиатура (зеркало onKeydown nodes.js:1134-1146 + развязка с RF) ---------- */

function isEditableTarget() {
  const ae = document.activeElement as HTMLElement | null;
  return !!ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName));
}

let keysInstalled = false;

export function installEditKeys() {
  if (keysInstalled) return;
  keysInstalled = true;

  /* Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z — undo/redo IR в выделенной Edit-ноде */
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && "zyяnн".includes(e.key.toLowerCase())) {
      if (isEditableTarget()) return;
      if (window.Editor && window.Editor.isOpen()) return; // у полноэкранного редактора своя история
      const selected = useFlowStore.getState().nodes.filter((x) => x.selected && x.type === "edit");
      if (!selected.length) return;
      const id = Number(selected[selected.length - 1].id);
      if (!histories.get(id) || !storeIr(id)) return;
      e.preventDefault();
      const isRedo = e.shiftKey || "yн".includes(e.key.toLowerCase());
      if (isRedo) redoEditNode(id);
      else undoEditNode(id);
    }
  });

  /* Конфликт стрелок: RF двигает выделенную ноду стрелками через keydown на своём
   * сфокусированном обёрточном div. Пока у GeoEdit есть выделение IR, стрелки двигают
   * элементы IR (geoedit.js сам делает nudge в capture-фазе) — не пускаем событие до
   * обёртки RF. Delete/Backspace при выделении IR гасит сам GeoEdit (capture +
   * stopPropagation, geoedit.js:1838); без выделения — RF удаляет ноду, как в legacy. */
  document.addEventListener(
    "keydown",
    (e) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
      if (isEditableTarget()) return;
      for (const geo of geos.values()) {
        if (geo.selections.length) {
          e.stopPropagation();
          return;
        }
      }
    },
    true,
  );
}
