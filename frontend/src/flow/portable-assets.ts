/** Export binary objects beside the graph, preserving canonical IR and master hashes. */
type EmbeddedBlobs = { version: "design-assets-export/1.0"; objects: Record<string, string> };
const MAX_BYTES = 128 * 1024 * 1024;
const EXT: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "image/svg+xml": "svg", "video/mp4": "mp4", "video/webm": "webm" };

function namesIn(value: unknown): string[] {
  const refs = [...new Set(Array.from(JSON.stringify(value).matchAll(/ddna:\/\/blobs\/([A-Za-z0-9._-]+)/g), match => match[1]))];
  if (refs.length > 500 || refs.some(name => !/^[a-f0-9]{64}\.(png|jpg|gif|webp|svg|mp4|webm)$/.test(name))) throw new Error("В графе слишком много ресурсов или некорректные ссылки на файлы");
  return refs;
}

async function validate(name: string, data: unknown) {
  if (typeof data !== "string" || data.length > MAX_BYTES * 4 / 3) throw new Error(`Ресурс отсутствует или слишком большой: ${name}`);
  const match = /^data:([^;,]+);base64,([A-Za-z0-9+/=]+)$/.exec(data);
  if (!match || !EXT[match[1]] || !name.endsWith('.' + EXT[match[1]])) throw new Error(`Неверный формат ресурса: ${name}`);
  const binary = atob(match[2]), bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(value => value.toString(16).padStart(2, "0")).join("");
  if (hash !== name.slice(0, 64)) throw new Error(`Ресурс повреждён: ${name}`);
  return { mime: match[1], base64: match[2], size: bytes.length };
}

export async function embedGraphAssets<T extends object>(payload: T): Promise<T & { embeddedBlobs?: EmbeddedBlobs }> {
  const graph = structuredClone(payload), names = namesIn(graph);
  if (!names.length) return graph;
  const bridge = window.designDNA?.blobs;
  if (!bridge) throw new Error("Откройте граф в DesignDNA, чтобы экспортировать локальные ресурсы");
  const objects: Record<string, string> = {}; let size = 0;
  for (const name of names) {
    const batch = await bridge.getMany([name]);
    const result = await validate(name, batch[name]);
    size += result.size;
    if (size > MAX_BYTES) throw new Error("Ресурсы графа превышают 128 МБ. Экспортируйте отдельный лист");
    objects[name] = batch[name];
  }
  return { ...graph, embeddedBlobs: { version: "design-assets-export/1.0", objects } };
}

export async function restoreGraphAssets<T extends object>(payload: T & { embeddedBlobs?: EmbeddedBlobs }): Promise<T> {
  const { embeddedBlobs, ...graph } = payload, names = namesIn(graph);
  if (!names.length) return graph as T;
  const bridge = window.designDNA?.blobs;
  if (!bridge) throw new Error("Локальные ресурсы графа можно восстановить в DesignDNA");
  if (!embeddedBlobs) {
    for (const name of names) await validate(name, (await bridge.getMany([name]))[name]);
    return graph as T;
  }
  if (embeddedBlobs.version !== "design-assets-export/1.0" || !embeddedBlobs.objects || typeof embeddedBlobs.objects !== "object") throw new Error("Неизвестный формат вложенных ресурсов");
  let size = 0;
  const verified = [];
  // Validate the whole set before writing any blobs or replacing the current graph.
  for (const name of names) {
    const data = await validate(name, embeddedBlobs.objects[name]);
    size += data.size;
    if (size > MAX_BYTES) throw new Error("Вложенные ресурсы превышают 128 МБ");
    verified.push({ name, ...data });
  }
  for (const object of verified) {
    const saved = await bridge.put(object.mime, object.base64);
    if (saved.name !== object.name) throw new Error(`Не удалось восстановить ресурс: ${object.name}`);
  }
  return graph as T;
}
