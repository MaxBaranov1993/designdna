import { readable, type Readable } from "svelte/store";
import type { StoreApi } from "zustand/vanilla";

/* Адаптер zustand vanilla store → Svelte readable: позволяет компонентам
 * подписываться на состояние графа через $-автоподписку, сохраняя единый
 * источник истины в zustand (поведение стора не менялось при миграции). */
export function asReadable<T>(store: StoreApi<T>): Readable<T> {
  return readable(store.getState(), (set) => store.subscribe(set));
}

/* Поверхностное сравнение записей: значения по ключам — по ссылке. */
export function shallowRecordEquals(
  a: Record<string | number, unknown>,
  b: Record<string | number, unknown>,
): boolean {
  if (a === b) return true;
  const keysA = Object.keys(a);
  if (keysA.length !== Object.keys(b).length) return false;
  return keysA.every((key) => a[key] === b[key]);
}

/* Selector-подписка: читаемая проекция среза стора, которая эмитит только
 * когда сам срез изменился. Глобальный asReadable будит каждый $derived на
 * любой set — включая runtime-поля busy/statuses, обновляемые во время
 * длинных операций, — что пересчитывает производные всех компонентов.
 * Селекторная подписка отсекает этот каскад: запись busy одной ноды не
 * инвалидирует компоненты, читающие nodes/edges, и наоборот. */
export function selectReadable<T, S>(
  store: StoreApi<T>,
  selector: (state: T) => S,
  equals: (a: S, b: S) => boolean = Object.is,
): Readable<S> {
  let current = selector(store.getState());
  return readable(current, (set) => {
    // между созданием readable и первой подпиской стор мог измениться
    current = selector(store.getState());
    set(current);
    return store.subscribe((state) => {
      const next = selector(state);
      if (equals(current, next)) return;
      current = next;
      set(next);
    });
  });
}
