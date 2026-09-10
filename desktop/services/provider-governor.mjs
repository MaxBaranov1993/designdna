/* Регулятор параллелизма подписочных провайдеров.
 *
 * Ни Anthropic, ни OpenAI не документируют лимит одновременных запросов по
 * подписке, а генератор с count=5 и очередь ревью ДС запускают несколько
 * `claude -p` / Codex-тредов разом. Каждый провайдер получает небольшой лимит
 * слотов и честную FIFO-очередь; отменённый в очереди запрос не занимает
 * слот. Лимиты настраиваются DESIGNDNA_PROVIDER_CONCURRENCY="claude=2,codex=2". */

export const DEFAULT_PROVIDER_LIMITS = Object.freeze({ claude: 2, codex: 2, openai: 4 });

export function parseProviderLimits(spec, defaults = DEFAULT_PROVIDER_LIMITS) {
  const limits = { ...defaults };
  for (const part of String(spec || "").split(",")) {
    const [name, value] = part.split("=").map((item) => item.trim());
    if (!name || !/^[a-z]+$/.test(name)) continue;
    const limit = Number.parseInt(value, 10);
    if (Number.isInteger(limit) && limit >= 1 && limit <= 32) limits[name] = limit;
  }
  return Object.freeze(limits);
}

export class ProviderGovernor {
  async run(provider, task, { signal } = {}) {
    const slot = await this.acquire(provider, { signal });
    try {
      if (signal?.aborted) throw this.#cancelled();
      return await task(slot);
    } finally {
      slot.release();
    }
  }
  constructor({ limits = DEFAULT_PROVIDER_LIMITS, now = Date.now } = {}) {
    this.limits = limits;
    this.now = now;
    this.active = new Map();
    this.queues = new Map();
  }

  limit(provider) {
    return this.limits[provider] ?? this.limits.codex ?? 2;
  }

  snapshot() {
    const out = {};
    for (const provider of new Set([...Object.keys(this.limits), ...this.active.keys(), ...this.queues.keys()])) {
      out[provider] = { limit: this.limit(provider), active: this.active.get(provider) || 0, queued: (this.queues.get(provider) || []).length };
    }
    return out;
  }

  /** Ждёт слот провайдера. Возвращает {release, queuedMs}; signal — отмена ожидания. */
  acquire(provider, { signal = null } = {}) {
    const startedAt = this.now();
    const active = this.active.get(provider) || 0;
    if (active < this.limit(provider)) {
      this.active.set(provider, active + 1);
      return Promise.resolve({ release: this.#releaser(provider), queuedMs: 0 });
    }
    if (signal?.aborted) return Promise.reject(this.#cancelled());
    return new Promise((resolve, reject) => {
      const queue = this.queues.get(provider) || [];
      const entry = {
        grant: () => {
          signal?.removeEventListener?.("abort", entry.abort);
          this.active.set(provider, (this.active.get(provider) || 0) + 1);
          resolve({ release: this.#releaser(provider), queuedMs: this.now() - startedAt });
        },
        abort: () => {
          const pending = this.queues.get(provider) || [];
          const index = pending.indexOf(entry);
          if (index >= 0) pending.splice(index, 1);
          reject(this.#cancelled());
        },
      };
      queue.push(entry);
      this.queues.set(provider, queue);
      signal?.addEventListener?.("abort", entry.abort, { once: true });
    });
  }

  #cancelled() {
    const error = new Error("Provider request cancelled while queued");
    error.code = "PROVIDER_CANCELLED";
    return error;
  }

  #releaser(provider) {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.active.set(provider, Math.max(0, (this.active.get(provider) || 1) - 1));
      const queue = this.queues.get(provider) || [];
      const next = queue.shift();
      if (next) next.grant();
    };
  }
}
