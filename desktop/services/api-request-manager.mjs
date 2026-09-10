/** A renderer request owns one queued/active operation, never the worker process.
 * Cancellation releases the renderer immediately. The scheduler still holds the
 * actual worker slot until cooperative work settles, so repeated cancellations
 * cannot create an unbounded number of running operations.
 */
export class ApiRequestManager {
  constructor() {
    this.requests = new Map();
    this.sequence = 0;
  }

  run(requestId, scope, worker, operation) {
    const id = requestId || `anonymous-${++this.sequence}`;
    if (this.requests.has(id)) return Promise.reject(new Error('Duplicate API requestId'));
    const controller = new AbortController();
    const entry = { scope, controller, worker, frameId: null };
    this.requests.set(id, entry);
    const cancelled = new Promise((_, reject) => controller.signal.addEventListener('abort', () => {
      if (entry.frameId) worker.sendControl({ type: 'cancel', requestId: entry.frameId });
      reject(Object.assign(new Error('cancelled'), { code: 'cancelled', cancelled: true }));
    }, { once: true }));
    const dispatch = async (params, timeout) => {
      controller.signal.throwIfAborted();
      entry.frameId = `api-${++this.sequence}`;
      try { return await worker.request('http.request', params, timeout, { id: entry.frameId }); }
      finally { entry.frameId = null; }
    };
    const pending = Promise.resolve().then(() => operation({ signal: controller.signal, dispatch }));
    const settled = pending.finally(() => {
      if (this.requests.get(id) === entry) this.requests.delete(id);
    });
    return Promise.race([settled, cancelled]);
  }

  cancel(requestId) {
    const entry = this.requests.get(requestId);
    if (!entry) return { cancelled: false, requestId, mode: 'not-found' };
    entry.controller.abort();
    return { cancelled: true, scope: entry.scope, requestId, mode: entry.frameId ? 'cooperative' : 'queued' };
  }
}
