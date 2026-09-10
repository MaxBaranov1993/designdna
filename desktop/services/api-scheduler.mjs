// Status/cancellation stays on the owning worker (jobs are process-local), with
// reserved capacity mirrored by the worker's small control pool.
export const isControlPath = path => /^\/api\/(?:block-parse\/job\/[^/]+(?:\/cancel)?|runs\/[^/]+(?:\/cancel)?|(?:motion|timeline)\/render\/[^/]+(?:\/cancel)?)$/.test(path);

/* Планировщик /api-трафика: три полосы вместо одного глобального мьютекса.
 *
 *  - exclusive  — тяжёлые capture-конвейеры (/api/block-parse): строго по
 *    одному, Chromium×viewports не параллелится.
 *  - project    — /api/project/*: строго по одному. Инвариант single-writer
 *    для projects.db и монотонность ревизий Live Project Session требуют,
 *    чтобы save/load не перегонялись между собой.
 *  - concurrent — всё остальное: выполняется сразу, ограничено семафором на
 *    воркер (лимит = размер ThreadPoolExecutor в desktop_worker.py), чтобы
 *    забитый воркер не копил неограниченную очередь in-flight запросов.
 *
 * Раньше все не-exclusive запросы шли через один SerialRequestQueue: любой
 * долгий запрос (генерация, quality-pass) замораживал ВЕСЬ API-трафик UI.
 */

export class Semaphore {
  constructor(limit) {
    this.limit = Math.max(1, Number(limit) || 1);
    this.active = 0;
    this.waiters = [];
  }

  async run(operation, signal) {
    signal?.throwIfAborted();
    if (this.active >= this.limit || this.waiters.length) {
      await new Promise((resolve, reject) => {
        const abort = () => {
          this.waiters = this.waiters.filter(item => item !== resume);
          reject(signal.reason);
        };
        const resume = () => { signal?.removeEventListener('abort', abort); this.active += 1; resolve(); };
        this.waiters.push(resume);
        signal?.addEventListener('abort', abort, { once: true });
      });
    } else this.active += 1;
    try {
      signal?.throwIfAborted();
      return await operation();
    } finally {
      this.active -= 1;
      const next = this.waiters.shift();
      if (next) next();
    }
  }
}

export class ApiScheduler {
  constructor({ exclusivePaths = [], projectPathPrefix = "/api/project/" } = {}) {
    this.exclusivePaths = new Set(exclusivePaths);
    this.projectPathPrefix = projectPathPrefix;
    this.exclusiveQueue = new Semaphore(1);
    this.projectQueue = new Semaphore(1);
    this.workerLimits = new Map();
    this.semaphores = new Map();
    this.controlSemaphores = new Map();
  }

  /** Лимит одновременных запросов для конкретного воркера. */
  registerWorker(worker, limit) {
    this.workerLimits.set(worker, Math.max(1, Number(limit) || 1));
  }

  lane(path) {
    if (isControlPath(path)) return "control";
    if (this.exclusivePaths.has(path)) return "exclusive";
    if (path === this.projectPathPrefix.replace(/\/$/, "") || path.startsWith(this.projectPathPrefix)) return "project";
    return "concurrent";
  }

  run(path, worker, operation, signal) {
    const lane = this.lane(path);
    if (lane === "exclusive") return this.exclusiveQueue.run(operation, signal);
    if (lane === "project") return this.projectQueue.run(operation, signal);
    if (lane === "control") {
      if (!this.controlSemaphores.has(worker)) this.controlSemaphores.set(worker, new Semaphore(1));
      return this.controlSemaphores.get(worker).run(operation, signal);
    }
    let semaphore = this.semaphores.get(worker);
    if (!semaphore) {
      semaphore = new Semaphore(this.workerLimits.get(worker) ?? 3);
      this.semaphores.set(worker, semaphore);
    }
    return semaphore.run(operation, signal);
  }
}
