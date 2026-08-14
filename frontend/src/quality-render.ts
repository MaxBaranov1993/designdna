import { IRRenderer } from "./engine/renderer";

declare global {
  interface Window {
    renderQualityIR: (ir: Record<string, unknown>, viewport: "desktop" | "mobile") => Promise<void>;
  }
}

window.renderQualityIR = async (ir, viewport) => {
  const root = document.getElementById("quality-root");
  if (!root) throw new Error("quality root missing");
  root.innerHTML = "";
  IRRenderer.renderIR(root, structuredClone(ir), { viewport });
  const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
  await Promise.race([document.fonts.ready.then(() => undefined), wait(1200)]);
  const imagesReady = Promise.all(Array.from(root.querySelectorAll("img")).map((img) => {
    if (img.complete) return Promise.resolve();
    return new Promise<void>((resolve) => {
      img.addEventListener("load", () => resolve(), { once: true });
      img.addEventListener("error", () => resolve(), { once: true });
    });
  }));
  await Promise.race([imagesReady.then(() => undefined), wait(1200)]);
};
