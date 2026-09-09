/** Refill a free request slot immediately; a slow sibling must not stall it.
 * Stop dispatching on the first failure. The caller cancels in-flight requests. */
export async function runDesktopAiQueue<T>(tasks: readonly T[], concurrency: number,
  run: (task: T, index: number) => Promise<void>): Promise<void> {
  let next = 0;
  let failed = false;
  const worker = async () => {
    while (!failed && next < tasks.length) {
      const index = next++;
      try { await run(tasks[index], index); }
      catch (error) { failed = true; throw error; }
    }
  };
  await Promise.all(Array.from({ length: Math.min(Math.max(1, concurrency), tasks.length) }, worker));
}
