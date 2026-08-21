const MAX_COOKIE_COUNT = 128;
const MAX_COOKIE_VALUE = 4096;

export function validateSourceAuthUrl(rawUrl) {
  const url = new URL(String(rawUrl || ""));
  if (!new Set(["https:", "http:"]).has(url.protocol)) {
    throw new Error("Source login accepts only http/https URLs");
  }
  if (url.username || url.password) throw new Error("Source login URL must not contain credentials");
  return url.toString();
}

function decodeRequestBody(request) {
  const body = String(request?.body || "");
  const text = request?.encoding === "base64"
    ? Buffer.from(body, "base64").toString("utf8")
    : body;
  if (!text) return {};
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Source Import request body must be a JSON object");
  }
  return parsed;
}

export function sourceAuthIntent(request) {
  if (String(request?.path || "").split("?", 1)[0] !== "/api/block-parse") return null;
  const payload = decodeRequestBody(request);
  if (payload.useAuthenticatedSession !== true) return null;
  return { url: validateSourceAuthUrl(payload.url), payload };
}

export function normalizeSourceAuthCookies(cookies, targetUrl) {
  const target = new URL(validateSourceAuthUrl(targetUrl));
  const host = target.hostname.toLowerCase();
  return (Array.isArray(cookies) ? cookies : []).slice(0, MAX_COOKIE_COUNT).flatMap((cookie) => {
    const name = String(cookie?.name || "");
    const value = String(cookie?.value || "");
    const domain = String(cookie?.domain || host).replace(/^\./, "").toLowerCase();
    if (!name || name.length > 256 || /[\x00-\x20;=]/.test(name)) return [];
    if (value.length > MAX_COOKIE_VALUE || /[\x00-\x08\x0A-\x1F\x7F]/.test(value)) return [];
    if (domain !== host && !host.endsWith(`.${domain}`)) return [];
    const path = String(cookie?.path || "/");
    if (!path.startsWith("/") || path.length > 1024) return [];
    if (cookie?.secure === true && target.protocol !== "https:") return [];
    const sameSite = ({ strict: "Strict", lax: "Lax", no_restriction: "None" })[cookie?.sameSite];
    return [{
      name,
      value,
      domain: cookie?.domain || host,
      path,
      secure: cookie?.secure === true,
      httpOnly: cookie?.httpOnly === true,
      ...(sameSite ? { sameSite } : {}),
    }];
  });
}

export function attachSourceAuthCookies(request, cookies, targetUrl) {
  const payload = decodeRequestBody(request);
  delete payload.useAuthenticatedSession;
  const authCookies = normalizeSourceAuthCookies(cookies, targetUrl);
  if (authCookies.length) payload.authCookies = authCookies;
  else payload.authSessionFallback = true;
  const body = Buffer.from(JSON.stringify(payload), "utf8").toString("base64");
  return {
    ...request,
    body,
    encoding: "base64",
    headers: { ...(request.headers || {}), "content-length": String(Buffer.byteLength(body, "base64")) },
  };
}
