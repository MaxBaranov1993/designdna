/* Один общий тикер на все ноды с активным прогрессом.
 *
 * Раньше каждый NodeShell с прогрессом заводил собственный setInterval(500ms):
 * при нескольких параллельных операциях это N независимых таймеров, каждый из
 * которых будит реактивность Svelte по своему расписанию. Здесь интервал один
 * на приложение; он стартует с первым подписчиком и гаснет с последним.
 */
type Listener = (now: number) => void;

const listeners = new Set<Listener>();
let timer: ReturnType<typeof setInterval> | null = null;

export function subscribeTick(listener: Listener): () => void {
  listeners.add(listener);
  listener(Date.now());
  if (timer === null) {
    timer = setInterval(() => {
      const now = Date.now();
      for (const fn of [...listeners]) fn(now);
    }, 500);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}
