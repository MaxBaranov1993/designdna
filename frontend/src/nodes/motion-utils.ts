import type { MotionNodeData, MotionSceneSettings, SourceViewport } from "../flow/types";

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
