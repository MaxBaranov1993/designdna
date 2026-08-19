import { writable } from "svelte/store";

export type ToastKind = "ok" | "error";

export type ToastItem = { id: number; msg: string; kind?: ToastKind };

let seq = 1;

/* Список активных тостов — читает ToastViewport.svelte */
export const toastItems = writable<ToastItem[]>([]);

/* Зеркало toast() (nodes.js:53-59): error висит 7 с, остальные 3.5 с */
export function toast(msg: string, kind?: ToastKind) {
  const id = seq++;
  toastItems.update((items) => [...items, { id, msg, kind }]);
  setTimeout(() => {
    toastItems.update((items) => items.filter((t) => t.id !== id));
  }, kind === "error" ? 7000 : 3500);
}
