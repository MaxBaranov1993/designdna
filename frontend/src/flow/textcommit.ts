/* Дебаунс-коммит текстовых полей нод.
 *
 * setNodeData на каждый keystroke мапит весь массив нод, будит подписки
 * всех компонентов и автосейв; здесь 100 мс трейлинг-дебаунс + мгновенный
 * flush по blur/change. Playwright fill() шлёт только input (без change
 * и blur), поэтому трейлинг-дебаунс обязателен — чистый blur-коммит
 * сломал бы UI-тесты. */
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const pending = new Map<string, () => void>();

function fire(key: string): void {
  timers.delete(key);
  const fn = pending.get(key);
  pending.delete(key);
  fn?.();
}

export function commitNodeText(key: string, apply: () => void, delay = 100): void {
  pending.set(key, apply);
  const prev = timers.get(key);
  if (prev) clearTimeout(prev);
  timers.set(
    key,
    setTimeout(() => fire(key), delay),
  );
}

export function flushNodeText(key: string): void {
  const t = timers.get(key);
  if (t) clearTimeout(t);
  if (pending.has(key)) fire(key);
}


/** Commit edits to their current sheet before navigation or running the graph. */
export function flushAllNodeText(): void {
  for (const key of [...pending.keys()]) flushNodeText(key);
}
