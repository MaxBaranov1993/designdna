import { pathToFileURL } from "node:url";

/* Exact URL policy for the renderer window.
 *
 * Shared by the will-navigate handler and the IPC sender-trust check so both
 * enforce the SAME allowlist: the dev-server URL (when DESIGNDNA_RENDERER_URL
 * is set) or the exact packaged renderer entry file. Anything else — including
 * arbitrary file: URLs — is not the trusted UI. */

function normalize(url) {
  try {
    const parsed = new URL(String(url));
    return { protocol: parsed.protocol, host: parsed.host, pathname: parsed.pathname };
  } catch {
    return null;
  }
}

function expectedTargets({ devUrl, rendererEntry }) {
  const targets = [];
  if (devUrl) {
    const dev = normalize(devUrl);
    if (dev) targets.push(dev);
  } else if (rendererEntry) {
    targets.push(normalize(pathToFileURL(rendererEntry).href));
  }
  return targets.filter(Boolean);
}

/** True only when `url` is the exact trusted renderer URL (query/hash ignored,
 *  so Vite reloads and in-app hash routing keep working). */
export function isAllowedRendererUrl(url, policy) {
  const candidate = normalize(url);
  if (!candidate) return false;
  return expectedTargets(policy).some(
    (target) =>
      candidate.protocol === target.protocol &&
      candidate.host === target.host &&
      candidate.pathname === target.pathname,
  );
}
