import { expandBlobRefs, isDesktopBlobUrl } from "../desktop/blobStore";

export function isImageSource(value: unknown): value is string {
  return typeof value === "string" && (value.startsWith("data:image/") || isDesktopBlobUrl(value));
}

export async function imageDataUrl(value: string): Promise<string> {
  const resolved = isDesktopBlobUrl(value) ? JSON.parse(await expandBlobRefs(JSON.stringify(value))) : value;
  if (typeof resolved !== "string" || !resolved.startsWith("data:image/")) throw new Error("Не удалось загрузить изображение");
  return resolved;
}

export async function downloadImage(value: string, name: string): Promise<void> {
  const url = await imageDataUrl(value);
  const desktop = window.designDNA;
  if (desktop?.files?.save) {
    await desktop.files.save(name, url.slice(url.indexOf(",") + 1));
  } else {
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
  }
}
