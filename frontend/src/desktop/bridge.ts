type DesktopHttpResponse = {
  status: number;
  headers: Record<string, string>;
  body: string;
  encoding: "utf8" | "base64";
};

function decodeBase64(value: string): ArrayBuffer {
  const binary = window.atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0)).buffer as ArrayBuffer;
}

function encodeBase64(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32_768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
  }
  return window.btoa(binary);
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

    const request = input instanceof Request ? input.clone() : new Request(url.toString(), init);
    const method = request.method.toUpperCase();
    const requestBody = new Set(["GET", "HEAD"]).has(method) ? "" : encodeBase64(await request.arrayBuffer());
    const response = await bridge.request({
      method,
      path: `${url.pathname}${url.search}`,
      headers: Object.fromEntries(request.headers.entries()),
      body: requestBody,
      encoding: "base64",
    }) as DesktopHttpResponse;
    const body = response.encoding === "base64" ? decodeBase64(response.body) : response.body;
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
