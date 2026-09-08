import { writable } from "svelte/store";
import { useFlowStore } from "./store";

/* UI-состояние графового экрана: чистая презентация, в проект не сохраняется.
 * Меню создания ноды и меню действий ноды открываются событиями window, чтобы
 * рельса и карточки (вне SvelteFlowProvider) могли дёргать FlowCanvas. */

export const OPEN_NODE_MENU_EVENT = "designdna:open-node-menu";
export const OPEN_NODE_ACTIONS_EVENT = "designdna:open-node-actions";

export type NodeMenuRequest = {
  /** экранные координаты; без них — центр канваса */
  x?: number;
  y?: number;
  /** label группы из CTX_GROUPS: меню откроется с фильтром по стадии */
  group?: string;
};

export type NodeActionsRequest = { nodeId: string; x: number; y: number };

export function requestNodeMenu(detail: NodeMenuRequest = {}) {
  window.dispatchEvent(new CustomEvent<NodeMenuRequest>(OPEN_NODE_MENU_EVENT, { detail }));
}

export function requestNodeActions(detail: NodeActionsRequest) {
  window.dispatchEvent(new CustomEvent<NodeActionsRequest>(OPEN_NODE_ACTIONS_EVENT, { detail }));
}

/** Снять выделение со всех нод (Esc в инспекторе, клик по ✕). */
export function deselectAllNodes() {
  const st = useFlowStore.getState();
  if (!st.nodes.some((node) => node.selected)) return;
  st.syncFromCanvas(st.nodes.map((node) => (node.selected ? { ...node, selected: false } : node)), st.edges);
}

/** Выделить одну ноду (из очереди задач, из инспектора Page Bridge). */
export function selectOnlyNode(id: number | string) {
  const st = useFlowStore.getState();
  const target = String(id);
  st.syncFromCanvas(st.nodes.map((node) => ({ ...node, selected: node.id === target })), st.edges);
}

/** Свёрнут ли плавающий инспектор (кнопка ✕ прячет его до следующего выделения). */
export const inspectorHidden = writable(false);
