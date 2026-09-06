import type { VideoStory, StoryAction } from "./video-story";
export type StoryEasing = "soft" | "ease-in" | "ease-out" | "linear";
export function motionEase(value: number, easing: StoryEasing = "soft"): number {
  const p = Math.max(0, Math.min(1, value));
  if (easing === "linear") return p;
  if (easing === "ease-in") return p * p * p;
  if (easing === "ease-out") return 1 - (1 - p) ** 3;
  return p * p * p * (p * (p * 6 - 15) + 10);
}
export const motionDurations: Record<StoryAction["type"], number> = { move: 900, click: 850, type: 1800, scroll: 1400, navigate: 1100, wait: 600 };
/** Explicit, undoable restyling keeps IDs, page snapshots, text and existing longer timings. */
export function softenStory(story: VideoStory): VideoStory {
  return { ...story, actions: story.actions.map((action) => ({ ...action, easing: "soft",
    duration: Math.max(action.duration, action.type === "type" ? Math.max(1400, Array.from(action.text || "").length * 120 + 700) : motionDurations[action.type]),
    ...(action.type === "navigate" ? { transition: "motion" as const } : {}),
  })) };
}
