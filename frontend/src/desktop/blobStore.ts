/* Вынос inline-блобов (data:image/...) из localStorage в десктопе.
 *
 * localStorage в профиле десктопа вырастал до 18+ МБ на inline-картинках:
 * каждый бут парсит блоб целиком (FCP ~3 c), каждый автосейв его сериализует.
 * Здесь: длинные data:-URL кладём в main-процесс (userData/data/blobs) и
 * заменяем на короткие ссылки ddna://blobs/<id>.<ext>, которые рендерер
 * подгружает через привилегированный протокол. Web-режим не затронут.
 *
 * Отправка воркеру: fidelity/QA-рендеры должны видеть настоящие картинки,
 * поэтому мост (desktop/bridge.ts) разворачивает ddna://blobs обратно в
 * data:-URL во всех исходящих /api-телах, кроме /api/project/*. */

const OFFLOAD_MIN_LENGTH = 32_768; // data:-URL короче 32 КБ оставляем как есть
const BLOB_PREFIX = "ddna://blobs/";

const SUPPORTED_MIME = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]);
const CONTENT_ADDRESSED_NAME = /^[a-f0-9]{64}\.(?:png|jpg|gif|webp|svg)$/;

export function blobBridgesAvailable(): boolean {
  return typeof window !== "undefined" && !!window.designDNA?.blobs;
}

export function isDesktopBlobUrl(value: string): boolean {
  return value.startsWith(BLOB_PREFIX);
}

export async function offloadDataUrl(dataUrl: string, minLength = OFFLOAD_MIN_LENGTH): Promise<string | null> {
  if (!blobBridgesAvailable() || !dataUrl.startsWith("data:") || dataUrl.length < minLength) return null;
  const comma = dataUrl.indexOf(",");
  if (comma < 0) return null;
  const header = dataUrl.slice(5, comma).split(";").map((part) => part.trim());
  const mime = String(header.shift() || "").toLowerCase();
  if (!SUPPORTED_MIME.has(mime) || header.at(-1)?.toLowerCase() !== "base64") return null;
  const base64 = dataUrl.slice(comma + 1);
  try {
    const stored = await window.designDNA!.blobs.put(mime, base64);
    if (!CONTENT_ADDRESSED_NAME.test(stored.name) || stored.sha256 !== stored.name.slice(0, 64)) {
      throw new Error("Desktop blob bridge returned a non-canonical object name");
    }
    return BLOB_PREFIX + stored.name;
  } catch {
    return null; // битый мост — данные остаются inline
  }
}

/** Заменяет все ddna://blobs/<name> в теле запроса на полные data:-URL. */
type SourceEvidenceBlock = {
  preview?: unknown;
  previews?: Record<string, unknown> | null;
};

/**
 * Persist Source Import screenshots before the generic project walk starts.
 *
 * A parsed page can contain tens of thousands of editable IR objects before the
 * top-level `previews` field is reached. The generic autosave walk is
 * deliberately time-boxed, so it may expire first and compactForStorage then
 * drops the remaining inline data URLs. Compare would therefore lose its only
 * raster evidence after restart.
 *
 * Source evidence is a small, explicit set (one screenshot per viewport and
 * block). Resolve it eagerly, deduplicate identical screenshots, and mutate the
 * response in place before it enters editor state.
 */
export async function offloadSourceEvidenceInPlace(blocks: SourceEvidenceBlock[]): Promise<number> {
  if (!blobBridgesAvailable() || !Array.isArray(blocks)) return 0;

  const slots: Array<{ owner: Record<string, unknown>; key: string; value: string }> = [];
  for (const block of blocks) {
    if (!block || typeof block !== "object") continue;
    if (typeof block.preview === "string" && block.preview.startsWith("data:")) {
      slots.push({ owner: block as Record<string, unknown>, key: "preview", value: block.preview });
    }
    if (block.previews && typeof block.previews === "object") {
      for (const [key, value] of Object.entries(block.previews)) {
        if (typeof value === "string" && value.startsWith("data:")) {
          slots.push({ owner: block.previews, key, value });
        }
      }
    }
  }

  // compactForStorage intentionally drops every inline reference image,
  // including small screenshots. Source evidence therefore cannot use the
  // generic 32 KiB optimisation threshold: every valid capture must become
  // an immutable blob reference before project state is serialised. Blob puts
  // are content-addressed and concurrency-safe, so independent screenshots do
  // not need to pay a serial IPC round-trip.
  const unique = Array.from(new Set(slots.map((slot) => slot.value)));
  const stored = await Promise.all(unique.map(async (value) => [value, await offloadDataUrl(value, 0)] as const));
  const refs = new Map<string, string | null>(stored);

  let replaced = 0;
  for (const slot of slots) {
    const ref = refs.get(slot.value);
    if (!ref) continue;
    slot.owner[slot.key] = ref;
    replaced++;
  }
  return replaced;
}

export async function expandBlobRefs(body: string): Promise<string> {
  if (!blobBridgesAvailable() || !body.includes(BLOB_PREFIX)) return body;
  const names = Array.from(new Set(body.match(/ddna:\/\/blobs\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/g) || []))
    .map((ref) => ref.slice(BLOB_PREFIX.length));
  if (!names.length) return body;
  const map = await window.designDNA!.blobs.getMany(names);
  for (const name of names) {
    const dataUrl = map[name];
    if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:")) {
      throw new Error(`Desktop blob is missing or corrupt: ${name}`);
    }
  }
  // Один проход вместо split().join() на каждый блоб: тело бывает многомегабайтным,
  // и пере-сборка всей строки N раз подряд подвешивала UI-поток внутри patched fetch.
  return body.replace(/ddna:\/\/blobs\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/g, (ref) => {
    const dataUrl = map[ref.slice(BLOB_PREFIX.length)];
    return typeof dataUrl === "string" ? dataUrl : ref;
  });
}

/** Обходит payload и выносит все длинные data:-URL (мутирует объекты на месте:
 *  компоненты продолжают работать — <img src> грузит блоб по протоколу). */
export async function offloadBlobsInPlace(payload: unknown, budgetMs = 800): Promise<boolean> {
  if (!blobBridgesAvailable()) return false;
  const started = performance.now();
  let replaced = 0;
  const walk = async (value: unknown): Promise<void> => {
    if (performance.now() - started > budgetMs) return; // сейв не должен виснуть
    if (Array.isArray(value)) {
      for (const item of value) await walk(item);
      return;
    }
    if (value && typeof value === "object") {
      for (const key of Object.keys(value as Record<string, unknown>)) {
        const v = (value as Record<string, unknown>)[key];
        if (typeof v === "string" && v.startsWith("data:") && v.length >= OFFLOAD_MIN_LENGTH) {
          const ref = await offloadDataUrl(v);
          if (ref) {
            (value as Record<string, unknown>)[key] = ref;
            replaced++;
          }
        } else {
          await walk(v);
        }
      }
    }
  };
  await walk(payload);
  return replaced > 0;
}
