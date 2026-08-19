import { readable, type Readable } from "svelte/store";
import type { StoreApi } from "zustand/vanilla";

/* Адаптер zustand vanilla store → Svelte readable: позволяет компонентам
 * подписываться на состояние графа через $-автоподписку, сохраняя единый
 * источник истины в zustand (поведение стора не менялось при миграции). */
export function asReadable<T>(store: StoreApi<T>): Readable<T> {
  return readable(store.getState(), (set) => store.subscribe(set));
}
