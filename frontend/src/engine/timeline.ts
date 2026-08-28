/* timeline.ts — солвер Timeline IR: детерминированная интерполяция кейфреймов.
 *
 * Единственный источник правды для превью редактора и headless-рендера
 * (engine.js): покадровое состояние слоя в момент времени t вычисляется
 * одинаково в обоих контурах, поэтому ролик совпадает с превью.
 *
 * Дисциплина рендера: во время проигрывания меняются ТОЛЬКО композитные
 * свойства (transform/opacity/visibility) на обёртке слоя; содержимое слоя
 * рендерится один раз. Это держит скраб и проигрывание в рамках
 * GPU-композитора Chromium без перерисовки контента.
 */

export type TimelineEasing =
  | "linear"
  | "ease"
  | "ease-in"
  | "ease-out"
  | "ease-in-out"
  | "cubic-bezier";

export interface TimelineKeyframe {
  t: number;
  value: number;
  easing?: TimelineEasing;
  bezier?: number[];
}

export interface TimelineTrack {
  keyframes: TimelineKeyframe[];
}

export type TimelineProperty = "x" | "y" | "scale" | "rotation" | "opacity";

export interface TimelineTransform {
  anchor: { x: number; y: number };
  properties: Partial<Record<TimelineProperty, TimelineTrack>>;
}

export interface TimelineLayer {
  id: string;
  name: string;
  type: "component" | "group" | "camera" | "overlay";
  ref?: string;
  parent?: string | null;
  in: number;
  out: number;
  locked?: boolean;
  transform: TimelineTransform;
}

export interface TimelineGroup {
  id: string;
  name: string;
  parent?: string | null;
  locked?: boolean;
}

export interface TimelineComposition {
  width: number;
  height: number;
  fps: number;
  duration: number;
  background: string;
  aspect: string;
}

export interface TimelineDocument {
  version: string;
  source?: { designIrHash: string; layerManifestHash: string; createdAt?: string };
  composition: TimelineComposition;
  groups: TimelineGroup[];
  layers: TimelineLayer[];
}

export interface SolvedTransform {
  x: number;
  y: number;
  scale: number;
  rotation: number;
  opacity: number;
  visible: boolean;
}

export const TIMELINE_PROPERTY_DEFAULTS: Record<TimelineProperty, number> = {
  x: 0,
  y: 0,
  scale: 1,
  rotation: 0,
  opacity: 1,
};

/* CSS-совместимые кривые именованных изингов (паритет с контрактом
 * в app/ir/timeline.py — EASING_BEZIERS). */
const EASING_BEZIERS: Record<Exclude<TimelineEasing, "cubic-bezier">, [number, number, number, number]> = {
  linear: [0.0, 0.0, 1.0, 1.0],
  ease: [0.25, 0.1, 0.25, 1.0],
  "ease-in": [0.42, 0.0, 1.0, 1.0],
  "ease-out": [0.0, 0.0, 0.58, 1.0],
  "ease-in-out": [0.42, 0.0, 0.58, 1.0],
};

function cubicBezierY(x1: number, y1: number, x2: number, y2: number, progress: number): number {
  if (progress <= 0) return 0;
  if (progress >= 1) return 1;
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const sampleX = (u: number) => ((ax * u + bx) * u + cx) * u;
  const sampleY = (u: number) => ((ay * u + by) * u + cy) * u;
  const sampleDX = (u: number) => (3 * ax * u + 2 * bx) * u + cx;

  // Ньютоновские шаги от хорошего старта; бинарный поиск как страховка.
  let u = progress;
  for (let i = 0; i < 8; i++) {
    const x = sampleX(u) - progress;
    if (Math.abs(x) < 1e-6) return sampleY(u);
    const d = sampleDX(u);
    if (Math.abs(d) < 1e-6) break;
    u -= x / d;
    if (u < 0) u = 0;
    if (u > 1) u = 1;
  }
  let lo = 0;
  let hi = 1;
  u = progress;
  while (hi - lo > 1e-6) {
    if (sampleX(u) < progress) lo = u;
    else hi = u;
    u = (lo + hi) / 2;
  }
  return sampleY(u);
}

export function easingProgress(
  easing: TimelineEasing | undefined,
  bezier: number[] | undefined,
  progress: number,
): number {
  if (progress <= 0) return 0;
  if (progress >= 1) return 1;
  const name: TimelineEasing = easing || "linear";
  if (name === "linear") return progress;
  let points: [number, number, number, number];
  if (name === "cubic-bezier") {
    points = bezier && bezier.length === 4
      ? [bezier[0], bezier[1], bezier[2], bezier[3]]
      : EASING_BEZIERS["ease-in-out"];
  } else {
    points = EASING_BEZIERS[name];
  }
  return cubicBezierY(points[0], points[1], points[2], points[3], progress);
}

/** Значение трека в момент t. Пустой трек — константа ``fallback``. */
export function solveTrack(track: TimelineTrack | undefined, t: number, fallback: number): number {
  const kfs = track && track.keyframes;
  if (!kfs || kfs.length === 0) return fallback;
  if (t <= kfs[0].t) return kfs[0].value;
  const last = kfs[kfs.length - 1];
  if (t >= last.t) return last.value;
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i];
    const b = kfs[i + 1];
    if (t >= a.t && t <= b.t) {
      if (b.t === a.t) return b.value;
      const progress = (t - a.t) / (b.t - a.t);
      const eased = easingProgress(a.easing, a.bezier, progress);
      return a.value + (b.value - a.value) * eased;
    }
  }
  return last.value;
}

/** Полное состояние слоя в момент времени (включая окно видимости in..out). */
export function solveLayer(layer: TimelineLayer, t: number): SolvedTransform {
  const props = (layer.transform && layer.transform.properties) || {};
  return {
    x: solveTrack(props.x, t, TIMELINE_PROPERTY_DEFAULTS.x),
    y: solveTrack(props.y, t, TIMELINE_PROPERTY_DEFAULTS.y),
    scale: Math.max(0, solveTrack(props.scale, t, TIMELINE_PROPERTY_DEFAULTS.scale)),
    rotation: solveTrack(props.rotation, t, TIMELINE_PROPERTY_DEFAULTS.rotation),
    opacity: Math.min(1, Math.max(0, solveTrack(props.opacity, t, TIMELINE_PROPERTY_DEFAULTS.opacity))),
    visible: t >= layer.in && t <= layer.out,
  };
}

export class TimelineEngine {
  readonly document: TimelineDocument;
  private layersById: Map<string, TimelineLayer>;

  constructor(document: TimelineDocument) {
    this.document = document;
    this.layersById = new Map();
    for (const layer of document.layers || []) {
      this.layersById.set(layer.id, layer);
    }
  }

  get duration(): number {
    return this.document.composition.duration;
  }

  get fps(): number {
    return this.document.composition.fps;
  }

  get width(): number {
    return this.document.composition.width;
  }

  get height(): number {
    return this.document.composition.height;
  }

  layer(id: string): TimelineLayer | undefined {
    return this.layersById.get(id);
  }

  layerIds(): string[] {
    return (this.document.layers || []).map((layer) => layer.id);
  }

  frameIndex(t: number): number {
    return Math.round((Math.max(0, Math.min(this.duration, t)) / 1000) * this.fps);
  }

  timeOfFrame(index: number): number {
    return Math.min(this.duration, (index / this.fps) * 1000);
  }

  totalFrames(): number {
    return this.frameIndex(this.duration) + 1;
  }

  /** Детерминированное состояние всех слоёв в момент времени. */
  seek(t: number): Record<string, SolvedTransform> {
    const clamped = Math.max(0, Math.min(this.duration, t));
    const out: Record<string, SolvedTransform> = {};
    for (const layer of this.document.layers || []) {
      out[layer.id] = solveLayer(layer, clamped);
    }
    return out;
  }
}

/** Применить решённое состояние к DOM: только композитные свойства.
 *  Слои помечаются атрибутом ``data-timeline-layer="<id>"``. */
export function applySolvedToDom(root: ParentNode, solved: Record<string, SolvedTransform>): void {
  const nodes = root.querySelectorAll("[data-timeline-layer]");
  nodes.forEach((node) => {
    const el = node as HTMLElement;
    const id = el.getAttribute("data-timeline-layer") || "";
    const state = solved[id];
    if (!state) {
      el.style.visibility = "hidden";
      return;
    }
    el.style.visibility = state.visible ? "visible" : "hidden";
    el.style.opacity = state.opacity.toFixed(4);
    el.style.transform =
      `translate3d(${state.x.toFixed(3)}px, ${state.y.toFixed(3)}px, 0) ` +
      `rotate(${state.rotation.toFixed(4)}deg) scale(${state.scale.toFixed(6)})`;
  });
}

export const Timeline = {
  easingProgress,
  solveTrack,
  solveLayer,
  applySolvedToDom,
  propertyDefaults: TIMELINE_PROPERTY_DEFAULTS,
};
