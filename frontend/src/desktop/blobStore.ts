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

const EXT_OF_MIME: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/svg+xml": "svg",
};

export function blobBridgesAvailable(): boolean {
  return typeof window !== "undefined" && !!window.designDNA?.blobs;
}

export function isDesktopBlobUrl(value: string): boolean {
  return value.startsWith(BLOB_PREFIX);
}

/** Дешёвый устойчивый id: два 32-битных FNV-1a (голова+хвост) + длина.
 *  Полное хеширование 18 МБ не нужно — цель дедупликации, не криптография. */
function blobId(dataUrl: string): string {
  const fnv = (from: number, to: number) => {
    let h = 0x811c9dc5;
    for (let i = from; i < to; i++) {
      h ^= dataUrl.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h.toString(36);
  };
  const head = fnv(0, Math.min(4096, dataUrl.length));
  const tail = fnv(Math.max(0, dataUrl.length - 4096), dataUrl.length);
  return `${head}${tail}${dataUrl.length.toString(36)}`;
}

export async function offloadDataUrl(dataUrl: string): Promise<string | null> {
  if (!blobBridgesAvailable() || !dataUrl.startsWith("data:") || dataUrl.length < OFFLOAD_MIN_LENGTH) return null;
  const mime = dataUrl.slice(5, dataUrl.indexOf(";"));
  const ext = EXT_OF_MIME[mime];
  if (!ext) return null;
  const name = `${blobId(dataUrl)}.${ext}`;
  const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  try {
    await window.designDNA!.blobs.put(name, base64);
    return BLOB_PREFIX + name;
  } catch {
    return null; // битый мост — данные остаются inline
  }
}

/** Заменяет все ddna://blobs/<name> в теле запроса на полные data:-URL. */
export async function expandBlobRefs(body: string): Promise<string> {
  if (!blobBridgesAvailable() || !body.includes(BLOB_PREFIX)) return body;
  const names = Array.from(new Set(body.match(/ddna:\/\/blobs\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/g) || []))
    .map((ref) => ref.slice(BLOB_PREFIX.length));
  if (!names.length) return body;
  let map: Record<string, string>;
  try {
    map = await window.designDNA!.blobs.getMany(names);
  } catch {
    return body;
  }
  let expanded = body;
  for (const [name, dataUrl] of Object.entries(map)) {
    expanded = expanded.split(BLOB_PREFIX + name).join(dataUrl);
  }
  return expanded;
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
