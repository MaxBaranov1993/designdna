import { writable, get } from "svelte/store";

export type ToastKind = "ok" | "error" | "info";

export type ToastAction = { label: string; run: () => void };

export type ToastOptions = {
  /** Не скрывать автоматически — для критических сообщений. */
  sticky?: boolean;
  /** Переопределяет длительность по умолчанию (ok/info 3.5 с, error 7 с). */
  durationMs?: number;
  /** Кнопка действия; после клика тост закрывается. */
  action?: ToastAction;
  /** Ключ дедупликации: повторный toast() с тем же key заменяет тост на месте. */
  key?: string;
};

export type ToastItem = {
  id: number;
  msg: string;
  kind?: ToastKind;
  sticky: boolean;
  action?: ToastAction;
  key?: string;
};

/** Не больше стольких тостов видно одновременно. */
export const TOAST_MAX_VISIBLE = 5;

const DEFAULT_MS: Record<ToastKind, number> = { ok: 3500, info: 3500, error: 7000 };

let seq = 1;

/* Список активных тостов — читает ToastViewport.svelte */
export const toastItems = writable<ToastItem[]>([]);

/* Таймеры автоскрытия: remaining хранится для паузы по наведению. */
type Timer = { handle: ReturnType<typeof setTimeout> | null; remaining: number; startedAt: number };
const timers = new Map<number, Timer>();

function clearTimer(id: number) {
  const t = timers.get(id);
  if (!t) return;
  if (t.handle !== null) clearTimeout(t.handle);
  timers.delete(id);
}

function startTimer(id: number, ms: number) {
  clearTimer(id);
  if (!Number.isFinite(ms) || ms <= 0) return;
  const t: Timer = { handle: null, remaining: ms, startedAt: Date.now() };
  t.handle = setTimeout(() => dismissToast(id), ms);
  timers.set(id, t);
}

function resolveDuration(kind: ToastKind | undefined, opts?: ToastOptions): number {
  if (opts?.sticky) return 0;
  if (typeof opts?.durationMs === "number") return opts.durationMs;
  return DEFAULT_MS[kind ?? "info"];
}

/**
 * Показать тост. Совместимо со старыми вызовами toast(msg) / toast(msg, "ok"|"error").
 * Возвращает id для dismissToast().
 */
export function toast(msg: string, kind?: ToastKind, opts?: ToastOptions): number {
  const sticky = !!opts?.sticky;
  const duration = resolveDuration(kind, opts);

  // Дедупликация по key: обновляем существующий тост на месте, перезапуская таймер.
  if (opts?.key) {
    const existing = get(toastItems).find((t) => t.key === opts.key);
    if (existing) {
      const id = existing.id;
      toastItems.update((items) =>
        items.map((t) => (t.id === id ? { ...t, msg, kind, sticky, action: opts.action } : t)),
      );
      startTimer(id, duration);
      return id;
    }
  }

  const id = seq++;
  const item: ToastItem = { id, msg, kind, sticky, action: opts?.action, key: opts?.key };

  toastItems.update((items) => {
    const next = [...items, item];
    // Лимит очереди: вытесняем самые старые не-sticky, пока не влезем.
    while (next.length > TOAST_MAX_VISIBLE) {
      const idx = next.findIndex((t) => !t.sticky && t.id !== id);
      if (idx === -1) break;
      clearTimer(next[idx].id);
      next.splice(idx, 1);
    }
    return next;
  });

  startTimer(id, duration);
  return id;
}

export function dismissToast(id: number): void {
  clearTimer(id);
  toastItems.update((items) => (items.some((t) => t.id === id) ? items.filter((t) => t.id !== id) : items));
}

export function dismissToastByKey(key: string): void {
  const hit = get(toastItems).find((t) => t.key === key);
  if (hit) dismissToast(hit.id);
}

/** Пауза автоскрытия (наведение мыши / фокус). */
export function pauseToast(id: number): void {
  const t = timers.get(id);
  if (!t || t.handle === null) return;
  clearTimeout(t.handle);
  t.handle = null;
  t.remaining = Math.max(0, t.remaining - (Date.now() - t.startedAt));
}

/** Возобновить автоскрытие после паузы. */
export function resumeToast(id: number): void {
  const t = timers.get(id);
  if (!t || t.handle !== null) return;
  if (t.remaining <= 0) {
    dismissToast(id);
    return;
  }
  t.startedAt = Date.now();
  t.handle = setTimeout(() => dismissToast(id), t.remaining);
}
