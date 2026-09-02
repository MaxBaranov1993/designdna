/* Загрузка картинки в элемент IR: выбор файла и ужатие до разумного размера.
 *
 * src хранится как data:-URL внутри IR (десктоп при сейве выносит его в
 * blob-store, браузер держит в localStorage/SQLite), поэтому оригинал в 12 МП
 * нельзя класть как есть — даунскейл до MAX_SIDE и перекодирование. PNG с
 * прозрачностью остаётся PNG, остальное — JPEG. */

export const IMAGE_MAX_SIDE = 1600;
export const IMAGE_JPEG_QUALITY = 0.86;

export function pickImageFile(accept = "image/*"): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.style.display = "none";
    document.body.appendChild(input);
    const done = (file: File | null) => {
      input.remove();
      resolve(file);
    };
    input.addEventListener("change", () => done(input.files?.[0] ?? null), { once: true });
    // отмена диалога: change не приходит — снимаем input по возврату фокуса
    window.addEventListener("focus", () => setTimeout(() => { if (input.isConnected && !input.files?.length) done(null); }, 400), { once: true });
    input.click();
  });
}

async function decode(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file);
    } catch {
      /* fallback ниже: часть форматов (SVG) createImageBitmap не берёт */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("Не удалось прочитать изображение"));
      img.src = url;
    });
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

function hasAlpha(ctx: CanvasRenderingContext2D, width: number, height: number): boolean {
  // Выборка по сетке: полный проход по мегапикселям не нужен
  const step = Math.max(1, Math.floor(Math.min(width, height) / 64));
  const data = ctx.getImageData(0, 0, width, height).data;
  for (let y = 0; y < height; y += step) {
    for (let x = 0; x < width; x += step) {
      if (data[(y * width + x) * 4 + 3] < 250) return true;
    }
  }
  return false;
}

export type PreparedImage = { dataUrl: string; width: number; height: number; bytes: number; mime: string };

/** Файл → data:-URL с даунскейлом. SVG отдаём как есть (векторный, без канваса). */
export async function prepareImageForIr(file: File, maxSide = IMAGE_MAX_SIDE): Promise<PreparedImage> {
  if (!file.type.startsWith("image/")) throw new Error("Это не изображение");
  if (file.type === "image/svg+xml" && file.size <= 512 * 1024) {
    const text = await file.text();
    const dataUrl = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(text)));
    return { dataUrl, width: 0, height: 0, bytes: dataUrl.length, mime: file.type };
  }
  const source = await decode(file);
  const srcW = "naturalWidth" in source ? source.naturalWidth : source.width;
  const srcH = "naturalHeight" in source ? source.naturalHeight : source.height;
  const scale = Math.min(1, maxSide / Math.max(srcW, srcH));
  const width = Math.max(1, Math.round(srcW * scale));
  const height = Math.max(1, Math.round(srcH * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas недоступен");
  ctx.drawImage(source as CanvasImageSource, 0, 0, width, height);
  if ("close" in source && typeof source.close === "function") source.close();
  const keepPng = file.type === "image/png" && hasAlpha(ctx, width, height);
  const mime = keepPng ? "image/png" : "image/jpeg";
  const dataUrl = keepPng ? canvas.toDataURL(mime) : canvas.toDataURL(mime, IMAGE_JPEG_QUALITY);
  return { dataUrl, width, height, bytes: dataUrl.length, mime };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}
