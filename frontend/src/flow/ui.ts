import { writable } from "svelte/store";

/* UI-состояние графового экрана (дизайн-хендофф): свёрнутость левой панели
 * и программное открытие меню «Создать ноду» из кнопки «+ Нода» в полосе
 * контекста. Не сохраняется в проект — чистая презентация. */
export const leftPanelOpen = writable(true);

export const OPEN_NODE_MENU_EVENT = "designdna:open-node-menu";

export function requestNodeMenu() {
  window.dispatchEvent(new CustomEvent(OPEN_NODE_MENU_EVENT));
}
