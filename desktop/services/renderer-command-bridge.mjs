import { randomUUID } from "node:crypto";

const MIN_TIMEOUT_MS = 100;
const MAX_TIMEOUT_MS = 120_000;

function bridgeError(code, message) {
  return Object.assign(new Error(message), { code });
}

export class RendererCommandBridge {
  constructor({ getTarget, maxPending = 128 } = {}) {
    if (typeof getTarget !== "function") throw new TypeError("getTarget must be a function");
    if (!Number.isInteger(maxPending) || maxPending < 1 || maxPending > 1_000) throw new TypeError("maxPending is invalid");
    this.getTarget = getTarget;
    this.maxPending = maxPending;
    this.pending = new Map();
    this.disposed = false;
  }

  request(command, timeoutMs = 30_000) {
    if (this.disposed) return Promise.reject(bridgeError("RENDERER_BRIDGE_DISPOSED", "Renderer command bridge is disposed"));
    if (this.pending.size >= this.maxPending) return Promise.reject(bridgeError("RENDERER_BUSY", "Too many renderer commands are pending"));
    const target = this.getTarget();
    if (!target || typeof target.id !== "string" || typeof target.send !== "function") {
      return Promise.reject(bridgeError("RENDERER_UNAVAILABLE", "The DesignDNA editor renderer is unavailable"));
    }
    const boundedTimeout = Math.max(MIN_TIMEOUT_MS, Math.min(Number(timeoutMs) || 30_000, MAX_TIMEOUT_MS));
    const requestId = `renderer-${randomUUID()}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(bridgeError("RENDERER_TIMEOUT", `Renderer command ${requestId} timed out`));
      }, boundedTimeout);
      this.pending.set(requestId, { rendererId: target.id, resolve, reject, timer });
      try {
        target.send("live-command:request", { requestId, command: structuredClone(command) });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(requestId);
        reject(bridgeError("RENDERER_SEND_FAILED", error instanceof Error ? error.message : String(error)));
      }
    });
  }

  respond(rendererId, payload) {
    const requestId = typeof payload?.requestId === "string" ? payload.requestId : "";
    const entry = this.pending.get(requestId);
    if (!entry) return { accepted: false };
    if (entry.rendererId !== String(rendererId)) throw bridgeError("RENDERER_MISMATCH", "A different renderer tried to resolve the command");
    this.pending.delete(requestId);
    clearTimeout(entry.timer);
    if (payload?.ok === true) entry.resolve(structuredClone(payload.result));
    else entry.reject(bridgeError(String(payload?.error?.code || "RENDERER_COMMAND_FAILED"), String(payload?.error?.message || "Renderer command failed")));
    return { accepted: true };
  }

  detach(rendererId) {
    let rejected = 0;
    for (const [requestId, entry] of this.pending) {
      if (entry.rendererId !== String(rendererId)) continue;
      clearTimeout(entry.timer);
      this.pending.delete(requestId);
      entry.reject(bridgeError("RENDERER_DETACHED", "The editor renderer was reloaded or closed"));
      rejected += 1;
    }
    return rejected;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(bridgeError("RENDERER_BRIDGE_DISPOSED", "Renderer command bridge is disposed"));
    }
    this.pending.clear();
  }
}
