import { TimelineEngine } from "../engine/timeline";

type Doc = Record<string, any>;

/** Trim animated tracks at the sampled boundary; preserve strict key ordering. */
export function resizeTimeline(doc: Doc, value: number): void {
  if (!Number.isFinite(value)) return;
  const oldDuration = doc.composition.duration;
  const storyEnd = (doc.story?.actions || []).reduce((sum: number, action: Doc) => sum + action.duration, 0);
  const duration = Math.max(250, storyEnd, Math.min(600000, Math.round(value)));
  const sampled = new TimelineEngine(doc as any).seek(duration);
  doc.composition.duration = duration;
  for (const layer of doc.layers) {
    if (layer.out === oldDuration || layer.out > duration) layer.out = duration;
    if (layer.in >= layer.out) layer.in = Math.max(0, layer.out - 1);
    for (const [prop, track] of Object.entries(layer.transform?.properties || {}) as [string, Doc][]) {
      if (!track.keyframes.some((key: Doc) => key.t > duration)) continue;
      const value = (sampled[layer.id] as unknown as Doc)?.[prop];
      track.keyframes = track.keyframes.filter((key: Doc) => key.t < duration);
      if (Number.isFinite(value)) track.keyframes.push({ t: duration, value, easing: "linear" });
    }
  }
}

/** A dragged key stops before its neighbours instead of creating duplicate times. */
export function moveTimelineKey(doc: Doc, layerId: string, prop: string, oldT: number, newT: number): number {
  const keys = doc.layers.find((layer: Doc) => layer.id === layerId)?.transform?.properties?.[prop]?.keyframes;
  if (!Array.isArray(keys) || !Number.isFinite(newT)) return oldT;
  const index = keys.findIndex((key: Doc) => key.t === oldT);
  if (index < 0) return oldT;
  const min = index ? keys[index - 1].t + 1 : 0;
  const max = index < keys.length - 1 ? keys[index + 1].t - 1 : doc.composition.duration;
  const t = Math.max(min, Math.min(max, Math.round(newT)));
  keys[index].t = t;
  return t;
}

export function setTimelineKeyValue(doc: Doc, layerId: string, prop: string, t: number, value: number): void {
  if (!Number.isFinite(value)) return;
  const key = doc.layers.find((layer: Doc) => layer.id === layerId)?.transform?.properties?.[prop]?.keyframes?.find((key: Doc) => key.t === t);
  if (key) key.value = prop === "opacity" ? Math.max(0, Math.min(1, value)) : prop === "scale" ? Math.max(0, value) : value;
}
