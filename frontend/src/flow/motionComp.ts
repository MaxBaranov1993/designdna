export type CompPose = { opacity: number; x: number; y: number; scale: number; rotate: number };
export type CompKeyframe = Partial<CompPose> & { t: number };
export type CompLayer = {
  id: string;
  name: string;
  sectionIndex: number;
  sourceKey?: string;
  enabled: boolean;
  keyframes: CompKeyframe[];
};

const DEFAULT_POSE: CompPose = { opacity: 1, x: 0, y: 0, scale: 1, rotate: 0 };

export function interpolatePose(keyframes: CompKeyframe[], timeMs: number): CompPose {
  const pose = { ...DEFAULT_POSE };
  const ordered = [...(keyframes || [])].filter((frame) => Number.isFinite(frame.t)).sort((a, b) => a.t - b.t);
  if (!ordered.length) return pose;
  const apply = (src: CompKeyframe) => {
    (Object.keys(DEFAULT_POSE) as (keyof CompPose)[]).forEach((key) => {
      const value = src[key];
      if (typeof value === "number") pose[key] = value;
    });
  };
  if (timeMs <= ordered[0].t) { apply(ordered[0]); return pose; }
  if (timeMs >= ordered[ordered.length - 1].t) { apply(ordered[ordered.length - 1]); return pose; }
  let start = ordered[0];
  let end = ordered[ordered.length - 1];
  for (let i = 1; i < ordered.length; i += 1) {
    if (timeMs <= ordered[i].t) { start = ordered[i - 1]; end = ordered[i]; break; }
  }
  const mix = Math.min(1, Math.max(0, (timeMs - start.t) / Math.max(1, end.t - start.t)));
  const smooth = mix * mix * (3 - 2 * mix);
  (Object.keys(DEFAULT_POSE) as (keyof CompPose)[]).forEach((key) => {
    const a = typeof start[key] === "number" ? (start[key] as number) : DEFAULT_POSE[key];
    const b = typeof end[key] === "number" ? (end[key] as number) : DEFAULT_POSE[key];
    pose[key] = a + (b - a) * smooth;
  });
  return pose;
}

export function applyCompPreview(root: HTMLElement | null, motion: Record<string, unknown> | null, timeMs: number) {
  if (!root || !motion) return;
  const layers = Array.isArray(motion.layers) ? motion.layers as CompLayer[] : [];
  const camera = interpolatePose(((motion.camera as { keyframes?: CompKeyframe[] } | undefined)?.keyframes) || [], timeMs);
  const art = root.querySelector<HTMLElement>("[class^='ir-']");
  if (art) {
    const current = art.style.transform || "";
    const base = current.includes("scale(") && !current.includes("translate(") ? current : "";
    art.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})${base ? "" : ""}`;
  }
  const bySection = new Map<number, CompPose>();
  layers.forEach((layer) => {
    if (!layer.enabled) return;
    bySection.set(layer.sectionIndex, interpolatePose(layer.keyframes || [], timeMs));
  });
  root.querySelectorAll<HTMLElement>("[data-ir-sec]").forEach((el) => {
    const pose = bySection.get(Number(el.dataset.irSec));
    if (!pose) {
      el.style.opacity = "1";
      el.style.transform = "none";
      return;
    }
    el.style.opacity = String(pose.opacity);
    el.style.transformOrigin = "center top";
    el.style.transform = `translate(${pose.x}px, ${pose.y}px) scale(${pose.scale}) rotate(${pose.rotate}deg)`;
  });
}
