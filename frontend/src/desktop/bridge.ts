import { expandBlobRefs } from "./blobStore";

type DesktopHttpResponse = {
  status: number;
  headers: Record<string, string>;
  body: string | Uint8Array;
  encoding: "utf8" | "base64" | "raw";
};

function decodeBase64(value: string): ArrayBuffer {
  const binary = window.atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0)).buffer as ArrayBuffer;
}

export function installDesktopFetchBridge(): void {
  const bridge = window.designDNA?.api;
  if (!bridge || (window as Window & { __designDNAFetchBridge?: boolean }).__designDNAFetchBridge) return;
  (window as Window & { __designDNAFetchBridge?: boolean }).__designDNAFetchBridge = true;
  const browserFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    let url: URL;
    try {
      url = new URL(rawUrl, "http://designdna.local");
    } catch {
      return browserFetch(input, init);
    }
    if (url.origin !== "http://designdna.local" || !url.pathname.startsWith("/api/")) {
      return browserFetch(input, init);
    }

    const request = new Request(input instanceof Request ? input : url.toString(), init);
    const signal = request.signal;
    signal.throwIfAborted();
    const method = request.method.toUpperCase();
    // Тело — UTF-8 JSON (все DesignDNA API): текст нужен для разворота блобов,
    // в IPC уходит Uint8Array (structured clone, без base64-инфляции)
    let requestText = new Set(["GET", "HEAD"]).has(method) ? "" : await request.text();
    // В LS блобы живут короткими ddna://-ссылками; серверный рендер (fidelity,
    // QA, reproduce) должен видеть настоящие data:-URL — разворачиваем во всех
    // исходящих телах, кроме persist-путей проекта (там ссылки и должны храниться)
    // Project and Design System documents persist compact ddna:// evidence
    // handles. Expanding them would re-inflate Source screenshots into IPC JSON
    // and immutable SQLite revisions. One-shot render/QA APIs still get pixels.
    const keepsBlobRefs = url.pathname.startsWith("/api/project/")
      || url.pathname.startsWith("/api/export/")
      || url.pathname.startsWith("/api/design-system/");
    if (requestText && !keepsBlobRefs) {
      requestText = await expandBlobRefs(requestText);
    }
    signal.throwIfAborted();
    const requestBody = requestText ? new TextEncoder().encode(requestText) : "";
    // runId из flow/api.ts → requestId IPC-фрейма: main.mjs шлёт воркеру
    // адресный cancel по нему (cancel_token), без рестарта всего воркера.
    const requestId = request.headers.get("x-designdna-run-id") || crypto.randomUUID();
    let abort: () => void = () => {};
    const cancelled = new Promise<never>((_, reject) => {
      abort = () => {
        void bridge.cancel('long', requestId).catch(() => undefined);
        reject(signal.reason || new DOMException('Запрос отменён', 'AbortError'));
      };
      signal.addEventListener('abort', abort, { once: true });
    });
    let response: DesktopHttpResponse;
    try {
      response = await Promise.race([bridge.request({
      method,
      path: `${url.pathname}${url.search}`,
      headers: Object.fromEntries(request.headers.entries()),
      body: requestBody,
      encoding: "raw",
      requestId,
    }) as Promise<DesktopHttpResponse>, cancelled]);
      signal.throwIfAborted();
    } finally {
      signal.removeEventListener('abort', abort);
    }
    // main отдаёт бинарные тела уже Uint8Array (structured clone без base64);
    // строка с encoding=base64 — fallback для старых main-процессов
    let body: ArrayBuffer | string;
    const rawBody: unknown = response.body;
    if (rawBody instanceof Uint8Array) body = rawBody.slice().buffer as ArrayBuffer;
    else if (response.encoding === "base64" && typeof response.body === "string") body = decodeBase64(response.body);
    else if (typeof response.body === "string") body = response.body;
    else body = "";
    return new Response(body, { status: response.status, headers: response.headers });
  };

  // beforeunload-флэш сейва идёт через navigator.sendBeacon — под file:// он
  // не доходит ни до воркера, ни куда-либо ещё; гоняем его через IPC-мост.
  const navigatorWithBeacon = navigator as Navigator & { __designDNABeaconBridge?: boolean };
  if (!navigatorWithBeacon.__designDNABeaconBridge) {
    navigatorWithBeacon.__designDNABeaconBridge = true;
    const nativeBeacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (url: string | URL, data?: BodyInit): boolean => {
      let parsed: URL;
      try {
        parsed = new URL(String(url), "http://designdna.local");
      } catch {
        return nativeBeacon(url, data);
      }
      if (parsed.origin !== "http://designdna.local" || !parsed.pathname.startsWith("/api/")) {
        return nativeBeacon(url, data);
      }
      void (async () => {
        try {
          const text = typeof data === "string" ? data : data instanceof Blob ? await data.text() : null;
          if (text == null) return;
          await bridge.request({
            method: "POST",
            path: `${parsed.pathname}${parsed.search}`,
            headers: { "Content-Type": "application/json" },
            body: text,
            encoding: "utf8",
          });
        } catch {
          // best-effort: компакт-копия уже в localStorage
        }
      })();
      return true;
    };
  }
}
