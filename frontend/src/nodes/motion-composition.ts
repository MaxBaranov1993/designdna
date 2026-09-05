import type { MotionCompLayer, MotionNodeData } from "../flow/types";
import { layerVals, scenesOf } from "./motion-utils";

export const COMP_CARD_STYLE = "display:inline-block;max-width:100%;padding:0.55em 1.4em;border-radius:0.5em;background:#222;border:1px solid #444;color:#eee;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 10px 30px rgba(0,0,0,0.28)";

/** Shared by the workspace and the video renderer: no hidden intro opacity. */
export function compositionFrame(data: MotionNodeData, layers: MotionCompLayer[], time: number) {
  const scenes = scenesOf(data);
  const index = scenes.findIndex((s, i) => time >= s.start && (time < s.start + s.duration || i === scenes.length - 1));
  const scene = scenes[index];
  if (!scene) return [];
  const local = Math.max(0, Math.min(time - scene.start, scene.duration));
  const transition = scene.transition;
  let progress = index > 0 && transition.duration > 0 ? Math.min(1, local / transition.duration) : 1;
  if (transition.easing === "ease-in") progress *= progress;
  else if (transition.easing === "ease-out") progress = 1 - (1 - progress) ** 2;
  else if (["ease", "ease-in-out"].includes(transition.easing)) progress = progress * progress * (3 - 2 * progress);
  const visible = progress < 1 && transition.type !== "cut" ? [scenes[index - 1], scene] : [scene];
  const width = Number(data.composition?.width || (data.motion?.composition as any)?.width || 1920);
  const height = Number(data.composition?.height || (data.motion?.composition as any)?.height || 1080);
  return visible.flatMap((current) => {
    const isCurrent = current.id === scene.id;
    const local = Math.max(0, Math.min(time - current.start, current.duration));
    const easing = current.transition.easing;
    return layers.filter((layer) => (layer.sceneId ?? scenes[0]?.id) === current.id).map((layer) => {
      const values = layerVals(layer, local, easing === "linear" ? "linear" : "smoothstep");
      if (progress < 1) {
        if (transition.type === "fade" || transition.type === "zoom") values.o *= isCurrent ? progress : 1 - progress;
        if (transition.type === "slide-left") values.p = [values.p[0] + width * (isCurrent ? 1 - progress : -progress), values.p[1]];
        if (transition.type === "slide-up") values.p = [values.p[0], values.p[1] + height * (isCurrent ? 1 - progress : -progress)];
        if (transition.type === "zoom") {
          const scale = isCurrent ? 0.92 + 0.08 * progress : 1 + 0.04 * progress;
          values.p = [(values.p[0] - width / 2) * scale + width / 2, (values.p[1] - height / 2) * scale + height / 2];
          values.s *= scale;
        }
      }
      return { layer, values };
    });
  });
}

/** DOM adapter for the headless export, using the same solver as the editor. */
export async function mountComposition(host: HTMLElement, data: MotionNodeData, layers: MotionCompLayer[]) {
  host.style.background = "#fff";
  host.style.fontFamily = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  const elements = new Map<string, HTMLElement>();
  const images: Promise<unknown>[] = [];
  for (const layer of layers) {
    const el = document.createElement("div");
    el.style.cssText = "position:absolute;text-align:center;line-height:1.08;letter-spacing:-0.02em;display:none";
    if (layer.type === "image") {
      const img = document.createElement("img");
      img.style.cssText = "display:block;width:100%;aspect-ratio:3/2;border-radius:18px;object-fit:contain";
      img.src = layer.src || "";
      images.push(img.decode());
      el.appendChild(img);
    } else {
      if (layer.type === "comp") {
        const card = document.createElement("span");
        card.style.cssText = COMP_CARD_STYLE;
        card.textContent = layer.name;
        el.appendChild(card);
      } else el.textContent = layer.text || "";
    }
    host.appendChild(el);
    elements.set(layer.id, el);
  }
  await Promise.all(images);
  return (time: number) => {
    for (const el of elements.values()) el.style.display = "none";
    let zIndex = 0;
    for (const { layer, values: v } of compositionFrame(data, layers, time)) {
      const el = elements.get(layer.id)!;
      Object.assign(el.style, {
        zIndex: String(zIndex++), display: "block", left: `${v.p[0]}px`, top: `${v.p[1]}px`, width: `${layer.w}px`,
        transform: `translate(-50%,-50%) scale(${v.s}) rotate(${v.r}deg)`,
        opacity: String(v.o), fontSize: `${layer.size}px`, fontWeight: String(layer.weight), color: layer.color,
      });
    }
  };
}
