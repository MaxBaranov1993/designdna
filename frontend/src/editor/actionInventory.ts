/** Explicit DNA Editor action inventory. Tests read `window.__editorActions`.
 * Every listed control must exist in the DOM when its group is visible and
 * must change editor state (not only a label). */
export const EDITOR_ACTION_GROUPS = {
  topbar: ["zoom-out", "zoom-in", "zoom-fit", "close", "save"],
  viewports: ["desktop", "tablet", "mobile"],
  tools: ["select", "hand", "frame", "rect", "text"],
  shapeFlyout: ["rect", "ellipse", "line", "image"],
  inspector: [
    "semantic-select", "smart-axis", "quality-gate", "harmonize",
    "responsive-autopilot", "intent-locks", "style-dna",
    "components", "rules",
    "undo", "redo", "forward", "backward",
  ],
  geometry: [
    "align-left", "align-center-h", "align-right",
    "align-top", "align-center-v", "align-bottom",
    "distribute-h", "distribute-v", "group", "ungroup",
    "stretch-width", "reset-frame",
  ],
  responsive: ["reset", "all", "mobile", "tablet", "desktop"],
  ai: ["run", "apply", "cancel"],
  styleDna: [
    "close-style-dna", "reset-style-dna", "apply-style-dna",
    "preview-normalize", "apply-normalize", "tailwind-exact",
    "tailwind-normalized", "copy-tailwind",
  ],
  overlays: [
    "apply-smart-axis", "apply-quality-fixes", "apply-harmonizer",
    "apply-responsive-autopilot", "apply-intent-locks", "run-semantic-select",
  ],
} as const;

export type EditorActionGroup = keyof typeof EDITOR_ACTION_GROUPS;

declare global {
  interface Window {
    __editorActions?: typeof EDITOR_ACTION_GROUPS;
  }
}
