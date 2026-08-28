import { SerialRequestQueue } from "../lib/serial-request-queue.mjs";

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

  async run(operation) {
    while (this.active >= this.limit) {
      await new Promise((resolve) => this.waiters.push(resolve));
    }
    this.active += 1;
    try {
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
    this.exclusiveQueue = new SerialRequestQueue();
    this.projectQueue = new SerialRequestQueue();
    this.workerLimits = new Map();
    this.semaphores = new Map();
  }

  /** Лимит одновременных запросов для конкретного воркера. */
  registerWorker(worker, limit) {
    this.workerLimits.set(worker, Math.max(1, Number(limit) || 1));
  }

  lane(path) {
    if (this.exclusivePaths.has(path)) return "exclusive";
    if (path === this.projectPathPrefix.replace(/\/$/, "") || path.startsWith(this.projectPathPrefix)) return "project";
    return "concurrent";
  }

  run(path, worker, operation) {
    const lane = this.lane(path);
    if (lane === "exclusive") return this.exclusiveQueue.run(operation);
    if (lane === "project") return this.projectQueue.run(operation);
    let semaphore = this.semaphores.get(worker);
    if (!semaphore) {
      semaphore = new Semaphore(this.workerLimits.get(worker) ?? 3);
      this.semaphores.set(worker, semaphore);
    }
    return semaphore.run(operation);
  }
}
