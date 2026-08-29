import type { MotionCompLayer, MotionNodeData, MotionSceneSettings, SourceViewport } from "../flow/types";

export type MotionScene = {
  id: string;
  interactionSceneId: string;
  start: number;
  duration: number;
  viewport: SourceViewport;
  transition: {
    type: MotionSceneSettings["transition"];
    duration: number;
    easing: MotionSceneSettings["easing"];
  };
};

export function scenesOf(data: MotionNodeData): MotionScene[] {
  return Array.isArray(data.motion?.scenes) ? (data.motion.scenes as MotionScene[]) : [];
}

export function durationOf(data: MotionNodeData): number {
  const composition = data.motion?.composition as Record<string, unknown> | undefined;
  return Number(composition?.duration || 0);
}

export function previewFor(data: MotionNodeData, scene: MotionScene | undefined) {
  if (!scene) return null;
  return data.sceneIrs.find((item) => item.sceneId === scene.id)?.ir || null;
}

/* ---------- кейфреймы (чистые функции — зеркало прототипа хендоффа) ---------- */

export type InterpMode = "linear" | "smoothstep";
export type Keyframe1 = { t: number; v: number };
export type Keyframe2 = { t: number; v: [number, number] };

/* smoothstep из README: u<.5 ? 2u² : 1−(−2u+2)²/2 */
export function smoothstepU(u: number): number {
  return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
}

/* Индекс ближайшего предшествующего кейфрейма (последний с t <= lt). */
export function keyIdxAt(keys: Array<{ t: number }>, lt: number): number {
  let i = 0;
  keys.forEach((k, j) => {
    if (k.t <= lt) i = j;
  });
  return i;
}

export function interpProp(keys: Keyframe2[], lt: number, dims: 2, mode?: InterpMode): [number, number];
export function interpProp(keys: Keyframe1[], lt: number, dims: 1, mode?: InterpMode): number;
export function interpProp(
  keys: Array<{ t: number; v: number | [number, number] }>,
  lt: number,
  dims: 1 | 2,
  mode: InterpMode = "linear",
): number | [number, number] {
  if (!keys.length) return dims === 2 ? [960, 540] : 0;
  if (lt <= keys[0].t) return keys[0].v;
  if (lt >= keys[keys.length - 1].t) return keys[keys.length - 1].v;
  let i = 0;
  for (let j = 0; j < keys.length - 1; j++) if (lt >= keys[j].t && lt < keys[j + 1].t) i = j;
  const a = keys[i];
  const b = keys[i + 1];
  let u = (lt - a.t) / Math.max(1, b.t - a.t);
  if (mode !== "linear") u = smoothstepU(u);
  if (dims === 2) {
    const av = a.v as [number, number];
    const bv = b.v as [number, number];
    return [av[0] + (bv[0] - av[0]) * u, av[1] + (bv[1] - av[1]) * u];
  }
  return (a.v as number) + ((b.v as number) - (a.v as number)) * u;
}

export type LayerValues = { p: [number, number]; s: number; r: number; o: number };

export function layerVals(layer: MotionCompLayer, lt: number, mode: InterpMode = "linear"): LayerValues {
  return {
    p: interpProp(layer.props.p.keys, lt, 2, mode),
    s: layer.props.s.keys.length ? interpProp(layer.props.s.keys, lt, 1, mode) : 1,
    r: interpProp(layer.props.r.keys, lt, 1, mode),
    o: layer.props.o.keys.length ? interpProp(layer.props.o.keys, lt, 1, mode) : 1,
  };
}
